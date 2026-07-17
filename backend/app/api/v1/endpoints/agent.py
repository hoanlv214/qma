"""Shared agent decision endpoint for the React UI and external clients."""

from types import SimpleNamespace

from fastapi import APIRouter

from backend.app.schemas.agent import AgentDecisionRequest
from backend.app.services.agent_decision import make_agent_decision


router = APIRouter(tags=["agent"])


def create_agent_router(deps: SimpleNamespace) -> APIRouter:
    migrated = APIRouter(tags=["agent"])

    @migrated.post("/api/v1/agent/decision")
    def create_agent_decision(request: AgentDecisionRequest):
        decision = make_agent_decision(
            deps,
            prompt=request.prompt,
            wallet=request.wallet,
            budget_usdc=request.budget_usdc,
            max_price_usdc=request.max_price_usdc,
            limit=request.limit,
            allowed_providers=request.allowed_providers,
            allowed_tiers=request.allowed_tiers,
            minimum_score=request.minimum_score,
            use_llm=request.use_llm,
        )
        return {"status": "success", **decision}

    return migrated
