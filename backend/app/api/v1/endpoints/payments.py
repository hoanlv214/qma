"""Payment, invoice, settlement, and withdraw endpoints."""

from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, Query

from backend.app.schemas import InvoiceRequest, PaymentVerifyRequest, QuoteRequest


router = APIRouter(tags=["payments"])


def create_payments_router(deps: SimpleNamespace) -> APIRouter:
    migrated = APIRouter(tags=["payments"])

    @migrated.post("/api/v1/payment/quote")
    def quote_payment(req: QuoteRequest):
        """Returns the complexity-adjusted USDC price for an exact signal snapshot."""
        req_data = deps.model_to_dict(req)
        provider_id = req_data.pop("provider_id", "funding_memory")
        tier = deps.normalize_tier(req_data.pop("tier", "full"))
        provider = deps.get_provider_or_404(provider_id)
        req_data = deps.normalize_query_for_provider(provider, req_data)
        quote = provider.quote_price(req_data, tier)
        return {
            "status": "success",
            "pricing": deps.pricing_config(),
            **quote,
        }

    @migrated.get("/api/v1/payment/settlement/{settlement_id}")
    def get_payment_settlement(settlement_id: str):
        settlement = deps.fetch_circle_settlement(settlement_id)
        batch = deps.find_arc_batch_tx(settlement)
        return {
            "settlement": settlement,
            "batch": batch,
        }

    @migrated.post("/api/v1/payment/invoice")
    def create_invoice(req: InvoiceRequest):
        """Creates a QMA invoice bound to a Circle x402 Arc Testnet payment."""
        return deps.create_invoice(req)

    @migrated.get("/api/v1/payment/invoices/{invoice_id}/status")
    def get_payment_invoice_status(
        invoice_id: str,
        invoice_secret: str = Query(..., min_length=16),
        refresh: bool = Query(default=True),
    ):
        """Returns the authoritative resumable payment state for one invoice."""
        return deps.get_payment_invoice_status(
            invoice_id=invoice_id,
            invoice_secret=invoice_secret,
            refresh=refresh,
        )

    @migrated.post("/api/v1/payment/verify")
    def verify_payment(invoice_id: str = Query(...), proof: Optional[PaymentVerifyRequest] = None):
        """Verifies a real Circle Gateway x402 settlement on Arc Testnet."""
        return deps.verify_payment(invoice_id=invoice_id, proof=proof)

    @migrated.post("/api/v1/payment/withdraw")
    def submit_withdraw(payload: dict):
        """Submits a signed BurnIntent authorization to Circle Gateway for withdrawal."""
        return deps.submit_withdraw(payload)

    return migrated
