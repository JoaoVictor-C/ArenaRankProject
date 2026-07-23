"""InfinitePay Checkout Links client (tournament entry payments).

Thin async wrapper over the InfinitePay **Checkout Links** API. This API is
**handle-only** — the merchant's InfiniteTag identifies the account; there is no
client id / secret. The account's real secret in *our* system is the webhook
token (see ``Settings.infinitepay_webhook_token``), not anything sent here.

Two calls are exposed:

* :meth:`create_link`  → ``POST /links``  → returns the hosted checkout URL.
* :meth:`payment_check` → ``POST /payment_check`` → confirms a payment out-of-band
  (the trust anchor: never trust a raw webhook payload; always re-check here).

The checkout page itself sets ``X-Frame-Options: SAMEORIGIN`` + a restrictive
``frame-ancestors`` CSP, so the product flow is a redirect/new-tab to the hosted
URL, never an iframe embed. And ``api.checkout.infinitepay.io`` returns no CORS
headers, so this MUST run server-side (a browser fetch is blocked) — hence this
module rather than a direct frontend call.

Pure I/O adapter: no DB, no business rules. Amount/idempotency/authorization
decisions live in the calling service/router.
"""

from __future__ import annotations

from typing import Any

import httpx

from arena.core.config import Settings, settings
from arena.core.logging import get_logger

_log = get_logger("arena.infinitepay")

#: Network timeout (seconds) for a single InfinitePay call.
_DEFAULT_TIMEOUT_S = 15.0


class InfinitePayError(RuntimeError):
    """Raised when InfinitePay is unconfigured or returns a non-success response."""


class InfinitePayClient:
    """Async client for the InfinitePay Checkout Links API.

    Construct with explicit ``handle``/``base_url`` in tests; the default
    :func:`from_settings` factory reads them from :class:`Settings`.
    """

    def __init__(
        self,
        handle: str,
        base_url: str = "https://api.checkout.infinitepay.io",
        *,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self._handle = handle.lstrip("$").strip()
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    @classmethod
    def from_settings(cls, cfg: Settings = settings) -> InfinitePayClient:
        """Build a client from runtime settings. Raises if the handle is unset."""
        if not cfg.infinitepay_handle:
            raise InfinitePayError(
                "InfinitePay não está configurado (defina INFINITEPAY_HANDLE)."
            )
        return cls(handle=cfg.infinitepay_handle, base_url=cfg.infinitepay_base_url)

    @property
    def handle(self) -> str:
        return self._handle

    async def create_link(
        self,
        *,
        order_nsu: str,
        items: list[dict[str, Any]],
        redirect_url: str,
        webhook_url: str | None = None,
        customer: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a hosted checkout link. Returns the parsed JSON (``{"url": ...}``).

        ``items`` are ``{"quantity": int, "price": <centavos>, "description": str}``.
        Creating a link does **not** charge anyone; a charge only happens if the
        payer completes payment on the hosted page.
        """
        payload: dict[str, Any] = {
            "handle": self._handle,
            "order_nsu": order_nsu,
            "redirect_url": redirect_url,
            "items": items,
        }
        if webhook_url:
            payload["webhook_url"] = webhook_url
        if customer:
            payload["customer"] = customer

        data = await self._post("/links", payload)
        if not isinstance(data, dict) or not data.get("url"):
            raise InfinitePayError(f"Resposta inesperada de /links: {data!r}")
        _log.info(
            "infinitepay.link_created",
            order_nsu=order_nsu,
            handle=self._handle,
        )
        return data

    async def payment_check(
        self,
        *,
        order_nsu: str,
        transaction_nsu: str,
        slug: str,
    ) -> dict[str, Any]:
        """Confirm a payment out-of-band (``POST /payment_check``).

        The authoritative check: a webhook is only a trigger; this call is what we
        trust before granting an entry.
        """
        payload = {
            "handle": self._handle,
            "order_nsu": order_nsu,
            "transaction_nsu": transaction_nsu,
            "slug": slug,
        }
        data = await self._post("/payment_check", payload)
        if not isinstance(data, dict):
            raise InfinitePayError(f"Resposta inesperada de /payment_check: {data!r}")
        return data

    async def _post(self, path: str, payload: dict[str, Any]) -> Any:
        url = f"{self._base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                resp = await client.post(url, json=payload)
        except httpx.HTTPError as exc:  # network/timeout
            _log.warning("infinitepay.request_failed", path=path, error=str(exc))
            raise InfinitePayError(f"Falha de rede ao chamar InfinitePay: {exc}") from exc

        if resp.status_code >= 400:
            _log.warning(
                "infinitepay.request_status",
                path=path,
                status=resp.status_code,
                body=resp.text[:500],
            )
            raise InfinitePayError(
                f"InfinitePay retornou {resp.status_code} em {path}: {resp.text[:200]}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise InfinitePayError(
                f"Corpo não-JSON de InfinitePay em {path}: {resp.text[:200]}"
            ) from exc


def entry_items(
    amount_cents: int,
    description: str,
    *,
    quantity: int = 1,
) -> list[dict[str, Any]]:
    """Build the ``items`` array for a tournament-entry charge.

    ``price`` is per-unit in centavos; total = ``price * quantity``. For the
    captain-pays-all flow use ``quantity = N`` players.
    """
    return [{"quantity": quantity, "price": amount_cents, "description": description}]


__all__ = ["InfinitePayClient", "InfinitePayError", "entry_items"]
