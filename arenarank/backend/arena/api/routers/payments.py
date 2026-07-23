"""Payments router (InfinitePay) — admin test surface.

**Fatia 1** do design de inscrição paga
(``docs/superpowers/specs/2026-07-21-infinitepay-inscricao-pix-design.md``):
um endpoint admin-gated que cria uma cobrança InfinitePay **real** (handle-only)
para provar a integração ao vivo. Ainda NÃO persiste nada — a tabela
``tournament_payments`` e o webhook chegam na fatia 2. Criar o link não cobra
ninguém; a cobrança só ocorre se o pagador concluir o PIX na página hospedada.

Roda server-side de propósito: ``api.checkout.infinitepay.io`` não devolve headers
CORS, então uma chamada direta do browser é bloqueada.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field

from arena.api.security import require_admin
from arena.core.config import settings
from arena.core.logging import get_logger
from arena.schemas.common import ArenaModel
from arena.services.infinitepay import InfinitePayClient, InfinitePayError, entry_items

_log = get_logger("arena.api.payments")

# Self-applies the admin gate on every route (mounted plainly in app.py).
router = APIRouter(
    prefix="/admin/payments",
    tags=["payments"],
    dependencies=[Depends(require_admin)],
)


class TestChargeRequest(ArenaModel):
    """Body de POST /admin/payments/test-charge (tudo opcional)."""

    amount_cents: int | None = Field(
        default=None, ge=1, le=1_000_000,
        description="Valor por unidade em centavos. Ausente => taxa padrão (500).",
    )
    description: str | None = Field(default=None, max_length=200)
    quantity: int = Field(
        default=1, ge=1, le=32,
        description="Quantidade (simula líder-paga-tudo: N jogadores).",
    )


class TestChargeResponse(ArenaModel):
    order_nsu: str
    checkout_url: str
    amount_cents: int
    quantity: int
    total_cents: int
    description: str


@router.post(
    "/test-charge",
    response_model=TestChargeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Criar cobrança InfinitePay de teste (Admin)",
)
async def create_test_charge(body: TestChargeRequest) -> TestChargeResponse:
    """Cria um link de checkout real para teste ao vivo. Não persiste, não cobra."""
    try:
        client = InfinitePayClient.from_settings(settings)
    except InfinitePayError as exc:
        # Handle não configurado => fail closed.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    amount = body.amount_cents or settings.tournament_entry_fee_cents
    description = (body.description or "Inscrição Campeonato ArenaRank (teste)").strip()
    order_nsu = f"arena-test-{uuid.uuid4().hex[:16]}"
    redirect_url = (
        f"{settings.public_base_url.rstrip('/')}/pagamento/retorno?order={order_nsu}"
    )
    items = entry_items(amount, description, quantity=body.quantity)

    try:
        # Webhook omitido de propósito no teste local (InfinitePay não alcança
        # localhost; a confirmação real por webhook chega na fatia 2).
        data = await client.create_link(
            order_nsu=order_nsu,
            items=items,
            redirect_url=redirect_url,
        )
    except InfinitePayError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"InfinitePay: {exc}"
        ) from exc

    _log.info(
        "payments.test_charge",
        order_nsu=order_nsu,
        amount_cents=amount,
        quantity=body.quantity,
    )
    return TestChargeResponse(
        order_nsu=order_nsu,
        checkout_url=data["url"],
        amount_cents=amount,
        quantity=body.quantity,
        total_cents=amount * body.quantity,
        description=description,
    )


__all__ = ["router"]
