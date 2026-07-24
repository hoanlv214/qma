from pydantic import BaseModel, Field
from typing import Optional, Any, Dict, List
from datetime import datetime
from uuid import UUID

from enum import Enum

class SessionStatus(str, Enum):
    draft = "draft"
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    stopped = "stopped"

class AgentSessionBase(BaseModel):
    title: str
    task: str
    budget_usdc: float = Field(..., ge=0)
    owner_wallet: Optional[str] = None

class AgentSessionCreate(AgentSessionBase):
    pass

class AgentSessionUpdate(BaseModel):
    status: Optional[SessionStatus] = None
    runtime_state: Optional[Dict[str, Any]] = None
    task: Optional[str] = None
    budget_usdc: Optional[float] = Field(None, ge=0)

class AgentSessionResponse(AgentSessionBase):
    id: UUID
    user_id: UUID
    status: SessionStatus
    runtime_state: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class AgentSessionEventBase(BaseModel):
    event_type: str
    payload: Optional[Dict[str, Any]] = None

class AgentSessionEventCreate(AgentSessionEventBase):
    pass

class AgentSessionEventResponse(AgentSessionEventBase):
    id: int
    session_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True
