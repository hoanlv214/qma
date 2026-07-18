"""Schemas for the shared QMA agent decision boundary."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class AgentDecisionRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000, examples=["Find the best preview report under 0.01 USDC."])
    wallet: Optional[str] = Field(default=None, max_length=80, examples=["0x4859d0d0babdcc8c4d8d2d116258fd0e5f7ff67d"])
    budget_usdc: Optional[float] = Field(default=None, ge=0, examples=[0.01])
    max_price_usdc: Optional[float] = Field(default=None, ge=0, examples=[0.005])
    limit: int = Field(default=25, ge=1, le=25, examples=[10])
    allowed_providers: Optional[List[str]] = Field(default=None, max_length=10, examples=[["funding_memory", "oi_memory"]])
    allowed_tiers: Optional[List[Literal["preview", "full"]]] = Field(default=None, max_length=2, examples=[["preview", "full"]])
    minimum_score: Optional[float] = Field(default=None, ge=0, le=100, examples=[70])
    use_llm: bool = Field(default=True, examples=[True])
