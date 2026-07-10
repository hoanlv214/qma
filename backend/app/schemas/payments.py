"""Payment request schemas."""

from typing import List, Optional

from pydantic import BaseModel, Field

from backend.app.schemas.query import QueryModel


class InvoiceRequest(QueryModel):
    provider_id: str = Field(default="funding_memory", max_length=64)
    tier: str = Field(default="full", pattern="^(preview|full)$")
    resource_type: str = Field(default="qma_signal_report", max_length=64)
    buyer_type: str = Field(default="human", pattern="^(human|agent)$")
    synthetic: bool = False
    agent_label: Optional[str] = Field(default=None, max_length=120)
    run_source: Optional[str] = Field(default=None, max_length=120)


class QuoteRequest(QueryModel):
    provider_id: str = Field(default="funding_memory", max_length=64)
    tier: str = Field(default="full", pattern="^(preview|full)$")


class SplitSettlementProof(BaseModel):
    leg_id: str = Field(..., min_length=2, max_length=32)
    settlement_id: str = Field(..., min_length=8)
    pay_to: str = Field(..., min_length=8, max_length=80)
    amount_raw: str = Field(..., min_length=1, max_length=80)
    sidecar_receipt: str = Field(..., min_length=20, max_length=300)


class PaymentVerifyRequest(BaseModel):
    settlement_id: Optional[str] = Field(default=None, min_length=8)
    invoice_secret: str = Field(..., min_length=16)
    payer_address: Optional[str] = None
    amount_usdc: Optional[float] = None
    split_settlements: List[SplitSettlementProof] = Field(default_factory=list)
