"""Chat request schemas."""

from typing import List, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    invoice_id: str
    message: str
    history: Optional[List[ChatMessage]] = Field(default_factory=list)
