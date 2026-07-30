"""``POST /payments/donation`` — a vaquinha da premiação (rota PÚBLICA).

Esta é a única rota do sistema que é, ao mesmo tempo, sem gate de admin e
disparadora de uma chamada externa a um provedor de pagamento em nome da nossa
conta. Os aceites aqui existem para que essas duas propriedades sejam
deliberadas e não acidentais:

* a rota é pública de propósito (o front chama direto do browser) — mas o irmão
  ``/admin/payments/*`` continua atrás de ``require_scope("tournaments:write")``.
  Se alguém "consertar" o gate no router errado, um destes quebra;
* os limites de valor (R$1–R$1.000) são validados ANTES de qualquer I/O — um
  valor fora da faixa nunca vira uma chamada à InfinitePay;
* sem handle configurado a rota falha FECHADA (503), não cria cobrança.

Nenhuma chamada real de rede: ``InfinitePayClient.create_link`` é substituída.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from arena.api.app import create_app
from arena.api.routers.payments import DONATION_MAX_CENTS, DONATION_MIN_CENTS
from arena.core.config import settings

_FAKE_URL = "https://checkout.infinitepay.io/fake-link"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Substitui a chamada externa e devolve a lista de chamadas capturadas."""
    calls: list[dict[str, Any]] = []

    async def _fake_create_link(self: Any, **kwargs: Any) -> dict[str, str]:
        calls.append(kwargs)
        return {"url": _FAKE_URL}

    monkeypatch.setattr(
        "arena.services.infinitepay.InfinitePayClient.create_link", _fake_create_link
    )
    monkeypatch.setattr(settings, "infinitepay_handle", "arenarank")
    return calls


def test_donation_is_public_no_admin_key_needed(
    client: TestClient, no_network: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Com uma chave de admin CONFIGURADA e deliberadamente NÃO enviada: se a
    # rota tivesse gate, isto seria 401.
    monkeypatch.setattr(settings, "admin_api_key", "s3cret-admin-key")
    r = client.post("/api/v1/payments/donation", json={"amountCents": 2500})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["checkoutUrl"] == _FAKE_URL
    assert body["amountCents"] == 2500
    assert body["orderNsu"].startswith("arena-doa-")
    assert len(no_network) == 1


def test_admin_payments_sibling_stays_gated(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O router admin de payments NÃO pode ter perdido o gate junto com a doação."""
    monkeypatch.setattr(settings, "admin_api_key", "s3cret-admin-key")
    r = client.post("/api/v1/admin/payments/test-charge", json={})
    assert r.status_code == 401


@pytest.mark.parametrize("amount", [0, -1, DONATION_MIN_CENTS - 1, DONATION_MAX_CENTS + 1])
def test_out_of_range_amounts_are_rejected_before_any_io(
    client: TestClient, no_network: list[dict[str, Any]], amount: int
) -> None:
    r = client.post("/api/v1/payments/donation", json={"amountCents": amount})
    assert r.status_code == 422
    assert not no_network, "valor inválido não pode virar chamada à InfinitePay"


@pytest.mark.parametrize("amount", [DONATION_MIN_CENTS, 5000, DONATION_MAX_CENTS])
def test_boundary_amounts_are_accepted(
    client: TestClient, no_network: list[dict[str, Any]], amount: int
) -> None:
    r = client.post("/api/v1/payments/donation", json={"amountCents": amount})
    assert r.status_code == 201, r.text
    assert r.json()["amountCents"] == amount


def test_missing_amount_is_rejected(
    client: TestClient, no_network: list[dict[str, Any]]
) -> None:
    assert client.post("/api/v1/payments/donation", json={}).status_code == 422
    assert not no_network


def test_fails_closed_without_a_configured_handle(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Handle vazio => 503, nunca uma cobrança meio-configurada."""
    monkeypatch.setattr(settings, "infinitepay_handle", "")
    r = client.post("/api/v1/payments/donation", json={"amountCents": 2500})
    assert r.status_code == 503


def test_redirect_url_points_at_our_own_base(
    client: TestClient, no_network: list[dict[str, Any]]
) -> None:
    """O retorno do checkout tem de voltar para o nosso domínio, não para o provedor."""
    r = client.post("/api/v1/payments/donation", json={"amountCents": 1000})
    assert r.status_code == 201
    redirect = no_network[0]["redirect_url"]
    assert redirect.startswith(settings.public_base_url.rstrip("/"))
    assert "doacao=ok" in redirect
    # O nsu do retorno é o mesmo da cobrança (reconciliação manual até a fatia 2).
    assert r.json()["orderNsu"] in redirect
