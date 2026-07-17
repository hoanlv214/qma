"""Shared query payload schemas."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class QueryModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    symbol: str = Field(..., min_length=1, max_length=32)
    fundingRate: Optional[float] = 0.0
    marketCap: Optional[float] = Field(default=None, gt=0)
    FDV: Optional[float] = Field(default=None, gt=0)
    circRatio: Optional[float] = Field(default=None, gt=0, le=1.5)
    fromATH: Optional[float] = None
    volume24h: Optional[float] = Field(default=None, gt=0)
    amount: Optional[float] = Field(default=None, gt=0)
    openInterest: Optional[float] = Field(default=None, gt=0)
    openInterestChange24h: Optional[float] = None
    longShortRatio: Optional[float] = Field(default=None, gt=0)
    price: Optional[float] = Field(default=None, gt=0)

