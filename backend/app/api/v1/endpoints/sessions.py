"""
Agent Sessions API Endpoints.

Handles creation, retrieval, updates, and events tracking for autonomous agent
research sessions, as well as managing agent wallet creation, deposit verification,
and withdrawals via the Arc Gateway.
"""

import time
import uuid
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from backend.app.schemas.sessions import (
    AgentSessionCreate,
    AgentSessionUpdate,
    AgentSessionResponse
)
from storage import SupabaseStorage
from backend.app.core.config import ARC_GATEWAY_BASE_URL, ARC_GATEWAY_INTERNAL_SECRET

class WalletWithdrawRequest(BaseModel):
    owner_wallet: str
    amount_usdc: float = Field(..., gt=0)

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
        
        runtime_state = {}
        if req.owner_wallet:
            owner_wallet_lower = req.owner_wallet.lower()
            runtime_state["owner_wallet"] = owner_wallet_lower
            
            # Check if this user has already created an Agent Wallet in a previous session
            params = {
                "runtime_state->>owner_wallet": f"eq.{owner_wallet_lower}",
                "limit": "50"
            }
            try:
                existing_sessions = storage._request("GET", "agent_sessions", params=params)
            except Exception:
                existing_sessions = []
                
            agent_wallet_address = None
            agent_wallet_id = None
            
            if existing_sessions:
                for s in existing_sessions:
                    rstate = s.get("runtime_state") or {}
                    if rstate.get("agent_wallet_address") and rstate.get("agent_wallet_id"):
                        agent_wallet_address = rstate.get("agent_wallet_address")
                        agent_wallet_id = rstate.get("agent_wallet_id")
                        break
            
            # If no wallet exists yet, call the Gateway to create a new one
            if not agent_wallet_address:
                import requests
                headers = {}
                if ARC_GATEWAY_INTERNAL_SECRET:
                    headers["x-qma-internal-secret"] = ARC_GATEWAY_INTERNAL_SECRET
                
                try:
                    resp = requests.post(
                        f"{ARC_GATEWAY_BASE_URL.rstrip('/')}/api/wallet/create",
                        headers=headers,
                        timeout=15
                    )
                    if not resp.ok:
                        raise HTTPException(status_code=502, detail=f"Failed to create agent wallet on Gateway: {resp.text[:300]}")
                    wdata = resp.json()
                    agent_wallet_address = wdata.get("address")
                    agent_wallet_id = wdata.get("walletId")
                except Exception as e:
                    if isinstance(e, HTTPException):
                        raise e
                    raise HTTPException(status_code=500, detail=f"Error contacting wallet relayer: {e}")
            
            runtime_state["agent_wallet_address"] = agent_wallet_address
            runtime_state["agent_wallet_id"] = agent_wallet_id
            
        row = {
            "id": session_id,
            "user_id": user_id,
            "title": req.title,
            "task": req.task,
            "budget_usdc": req.budget_usdc,
            "status": "draft",
            "runtime_state": runtime_state if runtime_state else None,
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

    @migrated.post(
        "/api/v1/sessions/withdraw",
        tags=["Agent sessions"],
    )
    def withdraw_funds(req: WalletWithdrawRequest):
        storage = get_storage(deps)
        owner_wallet_lower = req.owner_wallet.lower()
        
        # 1. Retrieve all user sessions to check their active state (Race condition lock)
        params = {
            "runtime_state->>owner_wallet": f"eq.{owner_wallet_lower}",
            "limit": "100"
        }
        try:
            sessions = storage._request("GET", "agent_sessions", params=params)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to query database: {e}")
            
        # Check for any active sessions (queued or running)
        active_sessions = [s for s in sessions if s.get("status") in ("queued", "running")]
        if active_sessions:
            raise HTTPException(
                status_code=400,
                detail="Cannot withdraw funds while a session is active. Please stop the session first."
            )
            
        # 2. Locate the corresponding agent_wallet_id for the user
        agent_wallet_id = None
        if sessions:
            for s in sessions:
                rstate = s.get("runtime_state") or {}
                if rstate.get("agent_wallet_id"):
                    agent_wallet_id = rstate.get("agent_wallet_id")
                    break
                    
        if not agent_wallet_id:
            raise HTTPException(
                status_code=404,
                detail="No Agent Wallet found for this owner wallet."
            )
            
        # 3. Contact the Gateway to execute the withdraw request
        import requests
        headers = {}
        if ARC_GATEWAY_INTERNAL_SECRET:
            headers["x-qma-internal-secret"] = ARC_GATEWAY_INTERNAL_SECRET
            
        try:
            resp = requests.post(
                f"{ARC_GATEWAY_BASE_URL.rstrip('/')}/api/wallet/withdraw",
                headers=headers,
                json={
                    "walletId": agent_wallet_id,
                    "destinationAddress": owner_wallet_lower,
                    "amountUsdc": f"{req.amount_usdc:.6f}",
                },
                timeout=30
            )
            if not resp.ok:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=f"Failed to execute withdraw on relayer: {resp.text[:300]}"
                )
            return resp.json()
        except Exception as e:
            if isinstance(e, HTTPException):
                raise e
            raise HTTPException(status_code=500, detail=f"Error contacting withdraw relayer: {e}")

    @migrated.get(
        "/api/v1/sessions/owner/{owner_wallet}/wallet",
        tags=["Agent sessions"],
    )
    def get_owner_agent_wallet(owner_wallet: str):
        storage = get_storage(deps)
        owner_wallet_lower = owner_wallet.lower()
        
        # 1. Search existing sessions to retrieve the Agent Wallet details
        params = {
            "runtime_state->>owner_wallet": f"eq.{owner_wallet_lower}",
            "limit": "50"
        }
        try:
            sessions = storage._request("GET", "agent_sessions", params=params)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to query database: {e}")
            
        agent_wallet_address = None
        agent_wallet_id = None
        
        if sessions:
            for s in sessions:
                rstate = s.get("runtime_state") or {}
                if rstate.get("agent_wallet_address") and rstate.get("agent_wallet_id"):
                    agent_wallet_address = rstate.get("agent_wallet_address")
                    agent_wallet_id = rstate.get("agent_wallet_id")
                    break
                    
        if not agent_wallet_address:
            return {"wallet": None}
            
        # 2. Contact the Gateway to retrieve the EOA wallet balances
        import requests
        headers = {}
        if ARC_GATEWAY_INTERNAL_SECRET:
            headers["x-qma-internal-secret"] = ARC_GATEWAY_INTERNAL_SECRET
            
        balance = 0.0
        try:
            resp = requests.get(
                f"{ARC_GATEWAY_BASE_URL.rstrip('/')}/api/wallet/{agent_wallet_id}/balance",
                headers=headers,
                timeout=10
            )
            if resp.ok:
                bdata = resp.json()
                token_balances = bdata.get("tokenBalances") or []
                for tb in token_balances:
                    if (tb.get("token") or {}).get("symbol") == "USDC":
                        balance = float(tb.get("amount") or 0.0)
                        break
        except Exception as e:
            pass
            
        gateway_balance = 0.0
        try:
            resp_gw = requests.get(
                f"{ARC_GATEWAY_BASE_URL.rstrip('/')}/api/balance/{agent_wallet_address}",
                headers=headers,
                timeout=10
            )
            if resp_gw.ok:
                gw_data = resp_gw.json()
                candidates = [
                    gw_data.get("balance"),
                    gw_data.get("available"),
                    gw_data.get("amount"),
                    gw_data.get("total"),
                ]
                if isinstance(gw_data.get("balances"), list) and len(gw_data["balances"]) > 0:
                    candidates.append(gw_data["balances"][0].get("amount"))
                    candidates.append(gw_data["balances"][0].get("balance"))
                if isinstance(gw_data.get("sources"), list) and len(gw_data["sources"]) > 0:
                    candidates.append(gw_data["sources"][0].get("amount"))
                    candidates.append(gw_data["sources"][0].get("balance"))
                if isinstance(gw_data.get("data"), dict):
                    gwd = gw_data["data"]
                    candidates.extend([
                        gwd.get("balance"),
                        gwd.get("available"),
                        gwd.get("amount"),
                        gwd.get("total")
                    ])
                    if isinstance(gwd.get("balances"), list) and len(gwd["balances"]) > 0:
                        candidates.append(gwd["balances"][0].get("amount"))
                        candidates.append(gwd["balances"][0].get("balance"))

                for cand in candidates:
                    if cand is not None:
                        try:
                            raw = float(cand)
                            if raw > 1000:
                                gateway_balance = raw / 1000000.0
                            else:
                                gateway_balance = raw
                            break
                        except ValueError:
                            continue
        except Exception:
            pass

        return {
            "wallet": {
                "address": agent_wallet_address,
                "wallet_id": agent_wallet_id,
                "balance_usdc": balance,
                "gateway_balance_usdc": gateway_balance
            }
        }

    return migrated
