"""Wallet profile request schemas."""

from pydantic import BaseModel, Field


class WalletProfileSessionRequest(BaseModel):
    nonce: str = Field(..., min_length=8, max_length=120)
    issued_at: int = Field(..., gt=0)
    signature: str = Field(..., min_length=20, max_length=300)
