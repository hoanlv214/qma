"""Schemas for the shared QMA agent decision boundary."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class AgentDecisionRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    wallet: Optional[str] = Field(default=None, max_length=80)
    budget_usdc: Optional[float] = Field(default=None, ge=0)
    max_price_usdc: Optional[float] = Field(default=None, ge=0)
    limit: int = Field(default=25, ge=1, le=25)
    allowed_providers: Optional[List[str]] = Field(default=None, max_length=10)
    allowed_tiers: Optional[List[Literal["preview", "full"]]] = Field(default=None, max_length=2)
    minimum_score: Optional[float] = Field(default=None, ge=0, le=100)
    use_llm: bool = True
