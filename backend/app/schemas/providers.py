"""Provider, creator, and claim request schemas."""

from typing import List, Optional

from pydantic import BaseModel, Field


class CreatorApplicationRequest(BaseModel):
    creator_wallet: str = Field(..., min_length=8, max_length=80)
    provider_id: str = Field(..., min_length=3, max_length=64, pattern="^[a-z0-9_\\-]+$")
    provider_name: str = Field(..., min_length=3, max_length=120)
    contact: str = Field(..., min_length=3, max_length=160)
    category: str = Field(default="market_memory", max_length=64)
    description: str = Field(..., min_length=20, max_length=800)
    data_source: str = Field(..., min_length=3, max_length=240)
    api_base_url: Optional[str] = Field(default=None, max_length=240)
    sample_schema: Optional[str] = Field(default=None, max_length=1200)
    revenue_wallet: Optional[str] = Field(default=None, max_length=80)
    revenue_share_bps: int = Field(default=8000, ge=1000, le=9500)


class CreatorReviewRequest(BaseModel):
    status: str = Field(..., pattern="^(approved|rejected|needs_changes|pending)$")
    admin_note: Optional[str] = Field(default=None, max_length=600)


class ProviderToggleRequest(BaseModel):
    enabled: bool
    admin_note: Optional[str] = Field(default=None, max_length=300)


class CreatorClaimRequest(BaseModel):
    claimant_address: str = Field(..., min_length=8, max_length=80)
    provider_ids: List[str] = Field(default_factory=list)
    amount_usdc: Optional[float] = Field(default=None, gt=0)
    nonce: str = Field(..., min_length=8, max_length=120)
    issued_at: int = Field(..., gt=0)
    signature: str = Field(..., min_length=20, max_length=300)
