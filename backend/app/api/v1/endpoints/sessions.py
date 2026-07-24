import time
import uuid
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends
from backend.app.schemas.sessions import (
    AgentSessionCreate,
    AgentSessionUpdate,
    AgentSessionResponse
)
from storage import SupabaseStorage

router = APIRouter(tags=["Agent sessions"])

def get_storage(deps):
    if not hasattr(deps, "storage_backend"):
        raise HTTPException(status_code=500, detail="Storage backend not configured")
    if not isinstance(deps.storage_backend, SupabaseStorage):
        raise HTTPException(status_code=500, detail="Only Supabase is supported for agent sessions")
    return deps.storage_backend

def create_sessions_router(deps) -> APIRouter:
    migrated = APIRouter()

    @migrated.post(
        "/api/v1/sessions",
        tags=["Agent sessions"],
        response_model=AgentSessionResponse,
        response_model_exclude_unset=True,
    )
    def create_session(req: AgentSessionCreate):
        storage = get_storage(deps)
        session_id = str(uuid.uuid4())
        # Provide a dummy user_id for now if no auth is enforced, or extract from token later
        user_id = "00000000-0000-0000-0000-000000000000" 
        
        runtime_state = None
        if req.owner_wallet:
            runtime_state = {"owner_wallet": req.owner_wallet.lower()}
            
        row = {
            "id": session_id,
            "user_id": user_id,
            "title": req.title,
            "task": req.task,
            "budget_usdc": req.budget_usdc,
            "status": "draft",
            "runtime_state": runtime_state,
        }
        
        # Save to Supabase using _upsert wrapper
        try:
            storage._upsert("agent_sessions", [row], conflict="id")
        except Exception as e:
            if "returned 40" in str(e):
                raise HTTPException(status_code=400, detail=str(e))
            raise HTTPException(status_code=500, detail=str(e))
            
        # Fetch back to get timestamps
        result = storage._request("GET", "agent_sessions", params={"id": f"eq.{session_id}", "limit": "1"})
        if not result:
            raise HTTPException(status_code=500, detail="Failed to retrieve created session")
            
        return result[0]

    @migrated.get(
        "/api/v1/sessions",
        tags=["Agent sessions"],
        response_model=List[AgentSessionResponse],
    )
    def list_sessions(owner_wallet: Optional[str] = None):
        storage = get_storage(deps)
        params = {"order": "created_at.desc.nullslast", "limit": "100"}
        if owner_wallet:
            params["runtime_state->>owner_wallet"] = f"eq.{owner_wallet.lower()}"
            
        result = storage._request("GET", "agent_sessions", params=params)
        return result or []

    @migrated.get(
        "/api/v1/sessions/{session_id}",
        tags=["Agent sessions"],
        response_model=AgentSessionResponse,
    )
    def get_session(session_id: str):
        storage = get_storage(deps)
        result = storage._request("GET", "agent_sessions", params={"id": f"eq.{session_id}", "limit": "1"})
        if not result:
            raise HTTPException(status_code=404, detail="Session not found")
        return result[0]

    @migrated.delete(
        "/api/v1/sessions/{session_id}",
        tags=["Agent sessions"],
    )
    def delete_session(session_id: str):
        storage = get_storage(deps)
        try:
            # PostgREST DELETE
            headers = dict(storage.headers)
            import requests
            resp = requests.delete(
                f"{storage.rest_url}/agent_sessions?id=eq.{session_id}",
                headers=headers,
                timeout=storage.timeout
            )
            if not resp.ok:
                raise RuntimeError(f"Failed to delete: {resp.text}")
        except Exception as e:
            if "returned 40" in str(e):
                raise HTTPException(status_code=400, detail=str(e))
            raise HTTPException(status_code=500, detail=str(e))
            
        return {"status": "deleted", "id": session_id}
        
    @migrated.post(
        "/api/v1/sessions/pick",
        tags=["Agent sessions"],
        response_model=AgentSessionResponse,
    )
    def pick_session():
        storage = get_storage(deps)
        try:
            result = storage._request("POST", "rpc/pick_queued_session")
        except Exception as e:
            if "returned 40" in str(e):
                raise HTTPException(status_code=400, detail=str(e))
            raise HTTPException(status_code=500, detail=str(e))
            
        if not result:
            raise HTTPException(status_code=404, detail="No queued session available")
        return result[0] if isinstance(result, list) else result

    @migrated.patch(
        "/api/v1/sessions/{session_id}",
        tags=["Agent sessions"],
        response_model=AgentSessionResponse,
    )
    def update_session(session_id: str, req: AgentSessionUpdate):
        storage = get_storage(deps)
        row = {"id": session_id}
        if req.status is not None:
            row["status"] = req.status
        if req.runtime_state is not None:
            row["runtime_state"] = req.runtime_state
        if req.task is not None:
            row["task"] = req.task
        if req.budget_usdc is not None:
            row["budget_usdc"] = req.budget_usdc
            
        try:
            # We must use PATCH because upsert (POST) requires all NOT NULL columns.
            storage._request("PATCH", "agent_sessions", params={"id": f"eq.{session_id}"}, json_body=row)
        except Exception as e:
            if "returned 40" in str(e):
                raise HTTPException(status_code=400, detail=str(e))
            raise HTTPException(status_code=500, detail=str(e))
            
        result = storage._request("GET", "agent_sessions", params={"id": f"eq.{session_id}", "limit": "1"})
        if not result:
            raise HTTPException(status_code=404, detail="Session not found")
        return result[0]

    @migrated.post(
        "/api/v1/sessions/{session_id}/start",
        tags=["Agent sessions"],
        response_model=AgentSessionResponse,
    )
    def start_session(session_id: str):
        return update_session(session_id, AgentSessionUpdate(status="queued"))

    @migrated.post(
        "/api/v1/sessions/{session_id}/stop",
        tags=["Agent sessions"],
        response_model=AgentSessionResponse,
    )
    def stop_session(session_id: str):
        return update_session(session_id, AgentSessionUpdate(status="stopped"))

    @migrated.post(
        "/api/v1/sessions/{session_id}/resume",
        tags=["Agent sessions"],
        response_model=AgentSessionResponse,
    )
    def resume_session(session_id: str):
        return update_session(session_id, AgentSessionUpdate(status="queued"))

    from backend.app.schemas.sessions import AgentSessionEventCreate, AgentSessionEventResponse

    @migrated.post(
        "/api/v1/sessions/{session_id}/events",
        tags=["Agent sessions"],
        response_model=AgentSessionEventResponse,
    )
    def create_event(session_id: str, req: AgentSessionEventCreate):
        storage = get_storage(deps)
        row = {
            "session_id": session_id,
            "event_type": req.event_type,
            "payload": req.payload,
        }
        try:
            # We must use POST without id to let identity column generate it
            storage._request("POST", "agent_session_events", json_body=row)
        except Exception as e:
            if "returned 40" in str(e):
                raise HTTPException(status_code=400, detail=str(e))
            raise HTTPException(status_code=500, detail=str(e))
            
        # PostgREST POST with json_body without returning=representation doesn't return the row.
        # But we can query it back by getting the latest event for this session.
        # This is not perfectly atomic for return value, but acceptable for now.
        result = storage._request("GET", "agent_session_events", params={
            "session_id": f"eq.{session_id}",
            "order": "id.desc",
            "limit": "1"
        })
        if not result:
            raise HTTPException(status_code=500, detail="Failed to retrieve created event")
        return result[0]

    return migrated
