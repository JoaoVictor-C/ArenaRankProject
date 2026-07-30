"""Payments router (InfinitePay) — admin test surface.

**Fatia 1** do design de inscrição paga (o doc de design original não está
neste repo — ver ``arena/services/infinitepay.py`` para o client e
``Settings.infinitepay_*`` para a config): um endpoint admin-gated que cria
uma cobrança InfinitePay **real** (handle-only) para provar a integração ao
vivo. Ainda NÃO persiste nada — a tabela ``tournament_payments`` e o webhook
chegam na fatia 2. Criar o link não cobra ninguém; a cobrança só ocorre se o
pagador concluir o PIX na página hospedada.

Roda server-side de propósito: ``api.checkout.infinitepay.io`` não devolve headers
CORS, então uma chamada direta do browser é bloqueada.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field

from arena.api.rbac import require_scope
from arena.core.config import settings
from arena.core.logging import get_logger
from arena.schemas.common import ArenaModel
from arena.services.infinitepay import InfinitePayClient, InfinitePayError, entry_items

_log = get_logger("arena.api.payments")

# Self-applies the scope gate on every route (mounted plainly in app.py).
# Grouped with tournament provisioning under tournaments:write since a test
# charge only ever makes sense alongside creating/configuring a tournament.
router = APIRouter(
    prefix="/admin/payments",
    tags=["payments"],
    dependencies=[Depends(require_scope("tournaments:write"))],
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


# ─────────────────────────────────────────────────────────────────────────────
# Doação pública para a premiação (vaquinha da Season) — NÃO admin-gated.
# Cria um link de checkout InfinitePay para o valor doado. Criar o link não cobra
# ninguém; a cobrança só ocorre se o doador concluir o PIX na página hospedada.
# Limites defendem o endpoint público de valores absurdos. Persistência do total
# arrecadado (tabela + webhook) é fatia 2 — por ora o front exibe o valor base.
#
# ATENÇÃO — esta é a ÚNICA rota pública do sistema que dispara uma chamada
# externa a um provedor de pagamento. Sem gate e sem rate limit ela é abusável
# como cunhadora de links (cada POST = uma chamada à InfinitePay em nome da
# nossa conta). Colocar rate limit por IP antes de divulgar a rota.
# ─────────────────────────────────────────────────────────────────────────────

#: Faixa aceita para uma doação (centavos): R$1 a R$1.000.
DONATION_MIN_CENTS = 100
DONATION_MAX_CENTS = 100_000

public_router = APIRouter(prefix="/payments", tags=["payments"])


class DonationRequest(ArenaModel):
    """Body de POST /payments/donation."""

    amount_cents: int = Field(
        ...,
        ge=DONATION_MIN_CENTS,
        le=DONATION_MAX_CENTS,
        description="Valor da doação em centavos (R$1–R$1.000).",
    )


class DonationResponse(ArenaModel):
    order_nsu: str
    checkout_url: str
    amount_cents: int


@public_router.post(
    "/donation",
    response_model=DonationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Criar link de doação para a premiação (InfinitePay)",
)
async def create_donation(body: DonationRequest) -> DonationResponse:
    """Cria um link de checkout real para uma doação à premiação. Não persiste,
    não cobra até o doador concluir o PIX na página hospedada."""
    try:
        client = InfinitePayClient.from_settings(settings)
    except InfinitePayError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    order_nsu = f"arena-doa-{uuid.uuid4().hex[:16]}"
    redirect_url = (
        f"{settings.public_base_url.rstrip('/')}/leaderboard?doacao=ok&order={order_nsu}"
    )
    items = entry_items(body.amount_cents, "Doação — Premiação Season I ArenaRank")

    try:
        data = await client.create_link(
            order_nsu=order_nsu,
            items=items,
            redirect_url=redirect_url,
        )
    except InfinitePayError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"InfinitePay: {exc}"
        ) from exc

    _log.info("payments.donation", order_nsu=order_nsu, amount_cents=body.amount_cents)
    return DonationResponse(
        order_nsu=order_nsu,
        checkout_url=data["url"],
        amount_cents=body.amount_cents,
    )


__all__ = ["router", "public_router"]
