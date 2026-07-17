"""Pydantic schemas for migrated endpoint groups."""

from backend.app.schemas.chat import ChatMessage, ChatRequest
from backend.app.schemas.payments import (
    InvoiceRequest,
    PaymentVerifyRequest,
    QuoteRequest,
    SplitSettlementProof,
)
from backend.app.schemas.providers import (
    CreatorApplicationRequest,
    CreatorClaimRequest,
    CreatorReviewRequest,
    ProviderToggleRequest,
)
from backend.app.schemas.query import QueryModel
from backend.app.schemas.wallets import WalletProfileSessionRequest

__all__ = [
    "ChatMessage",
    "ChatRequest",
    "CreatorApplicationRequest",
    "CreatorClaimRequest",
    "CreatorReviewRequest",
    "InvoiceRequest",
    "PaymentVerifyRequest",
    "ProviderToggleRequest",
    "QueryModel",
    "QuoteRequest",
    "SplitSettlementProof",
    "WalletProfileSessionRequest",
]
