import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.v1.endpoints.agent import create_agent_router


class FakeProvider:
    def quote_price(self, query, tier):
        return {"amount_usdc": 0.001 if tier == "preview" else 0.005}


class FakeRegistry:
    def require(self, provider_id):
        if provider_id != "funding_memory":
            raise KeyError(provider_id)
        return FakeProvider()


def make_app(entitlements=None, recommendations=None):
    recommendations = recommendations or [{
        "candidate_id": "candidate-1",
        "provider_id": "funding_memory",
        "symbol": "SXT",
        "score": 82.0,
        "suggested_tier": "full",
        "suggested_price_usdc": 0.005,
        "query": {"symbol": "SXT", "fundingRate": -0.01},
        "reasons": ["extreme negative funding"],
    }]
    deps = SimpleNamespace(
        get_agent_recommendations=lambda limit: {"recommendations": recommendations},
        load_wallet_entitlements=lambda wallet: entitlements or [],
        provider_registry=FakeRegistry(),
    )
    app = FastAPI()
    app.include_router(create_agent_router(deps))
    return app


class AgentDecisionContractTests(unittest.TestCase):
    def setUp(self):
        self.previous_key = os.environ.pop("OPENAI_API_KEY", None)

    def tearDown(self):
        if self.previous_key is not None:
            os.environ["OPENAI_API_KEY"] = self.previous_key

    def test_endpoint_returns_validated_purchase_decision(self):
        response = TestClient(make_app()).post(
            "/api/v1/agent/decision",
            json={"prompt": "Find a preview report under 0.002 USDC", "wallet": "0x1111111111111111111111111111111111111111"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["plan"]["action"], "purchase")
        self.assertEqual(body["decision_source"], "deterministic_policy")
        self.assertEqual(body["plan"]["candidate_id"], "candidate-1")
        self.assertEqual(body["resolved_candidate"]["tier"], "preview")
        self.assertEqual(body["resolved_candidate"]["price_usdc"], 0.001)

    def test_endpoint_skips_full_entitlement(self):
        response = TestClient(make_app([{"symbol": "SXT", "tier": "full"}])).post(
            "/api/v1/agent/decision",
            json={"prompt": "Find the best report under 0.01 USDC", "wallet": "0x1111111111111111111111111111111111111111"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["plan"]["action"], "skip")
        self.assertIsNone(body["resolved_candidate"])

    def test_best_preview_uses_normalized_preview_price_before_scoring(self):
        app = make_app()
        app.router.routes.clear()

        deps = SimpleNamespace(
            get_agent_recommendations=lambda limit: {"recommendations": [
                {
                    "candidate_id": "apd-oi",
                    "provider_id": "funding_memory",
                    "symbol": "APDSTOCK",
                    "score": 85.9,
                    "suggested_tier": "full",
                    "suggested_price_usdc": 0.005889,
                    "query": {"symbol": "APDSTOCK"},
                },
                {
                    "candidate_id": "b3-funding",
                    "provider_id": "funding_memory",
                    "symbol": "B3",
                    "score": 57.3,
                    "suggested_tier": "preview",
                    "suggested_price_usdc": 0.001143,
                    "query": {"symbol": "B3"},
                },
            ]},
            load_wallet_entitlements=lambda wallet: [],
            provider_registry=FakeRegistry(),
        )
        app.include_router(create_agent_router(deps))
        response = TestClient(app).post(
            "/api/v1/agent/decision",
            json={"prompt": "Find the best preview report under 0.01 USDC"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["plan"]["action"], "purchase")
        self.assertEqual(body["plan"]["candidate_id"], "apd-oi")
        self.assertEqual(body["resolved_candidate"]["tier"], "preview")

    def test_highest_score_policy_overrides_lower_llm_pick(self):
        recommendations = [
            {"candidate_id": "apd", "provider_id": "funding_memory", "symbol": "APDSTOCK", "score": 85.9, "suggested_tier": "full", "query": {"symbol": "APDSTOCK"}},
            {"candidate_id": "b3", "provider_id": "funding_memory", "symbol": "B3", "score": 56.4, "suggested_tier": "preview", "query": {"symbol": "B3"}},
        ]
        llm_body = {
            "choices": [{"message": {"content": '{"action":"purchase","candidate_id":"b3","requested_tier":"preview","budget_usdc":0.01,"max_price_usdc":0.005,"reason":"lower pick","rejected_candidate_ids":[]}'}}],
        }

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return llm_body

        os.environ["OPENAI_API_KEY"] = "test-only"
        response = None
        with patch("backend.app.services.agent_decision.requests.post", return_value=FakeResponse()):
            response = TestClient(make_app(recommendations=recommendations)).post(
                "/api/v1/agent/decision",
                json={"prompt": "Find the best preview report under 0.01 USDC"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["plan"]["candidate_id"], "apd")

    def test_llm_extra_candidate_fields_are_not_accepted(self):
        recommendations = [
            {"candidate_id": "apd", "provider_id": "funding_memory", "symbol": "APDSTOCK", "score": 85.9, "suggested_tier": "preview", "query": {"symbol": "APDSTOCK"}},
        ]
        llm_body = {"choices": [{"message": {"content": '{"action":"purchase","candidate_id":"apd","requested_tier":"preview","budget_usdc":0.01,"max_price_usdc":0.005,"reason":"pick","rejected_candidate_ids":[],"selected":{"symbol":"APDSTOCK"}}'}}]}

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return llm_body

        os.environ["OPENAI_API_KEY"] = "test-only"
        with patch("backend.app.services.agent_decision.requests.post", return_value=FakeResponse()):
            body = TestClient(make_app(recommendations=recommendations)).post(
                "/api/v1/agent/decision", json={"prompt": "Find the best preview report under 0.01 USDC"}
            ).json()
        self.assertEqual(body["decision_source"], "deterministic_policy")
        self.assertEqual(body["plan"]["candidate_id"], "apd")

    def test_rejection_reason_codes_are_canonical(self):
        body = TestClient(make_app(recommendations=[
            {"candidate_id": "too-high", "provider_id": "funding_memory", "symbol": "HIGH", "score": 90, "suggested_tier": "full", "query": {"symbol": "HIGH"}},
        ])).post(
            "/api/v1/agent/decision", json={"prompt": "Find the best full report under 0.002 USDC"}
        ).json()
        self.assertEqual(body["plan"]["action"], "skip")
        self.assertEqual(body["rejected_candidates"][0]["reason_code"], "PRICE_ABOVE_BUDGET")

    def test_clarify_is_preserved_and_requested_tier_is_not_resolved_tier(self):
        recommendations = [{
            "candidate_id": "candidate-1", "provider_id": "funding_memory", "symbol": "SXT",
            "score": 82.0, "suggested_tier": "preview", "query": {"symbol": "SXT"},
        }]
        llm_body = {"choices": [{"message": {"content": '{"action":"clarify","candidate_id":null,"requested_tier":"auto","budget_usdc":0.01,"max_price_usdc":0.005,"reason":"Need a clearer objective.","rejected_candidate_ids":[]}'}}]}

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return llm_body

        os.environ["OPENAI_API_KEY"] = "test-only"
        with patch("backend.app.services.agent_decision.requests.post", return_value=FakeResponse()):
            body = TestClient(make_app(recommendations=recommendations)).post(
                "/api/v1/agent/decision", json={"prompt": "I need help choosing"}
            ).json()
        self.assertEqual(body["plan"]["action"], "clarify")
        self.assertEqual(body["plan"]["requested_tier"], "auto")
        self.assertIsNone(body["resolved_candidate"])

    def test_entitlement_is_bound_to_provider(self):
        recommendations = [
            {"candidate_id": "funding-sxt", "provider_id": "funding_memory", "symbol": "SXT", "score": 90, "suggested_tier": "preview", "query": {"symbol": "SXT"}},
        ]
        entitlements = [{"symbol": "SXT", "provider_id": "oi_memory", "tier": "preview"}]
        body = TestClient(make_app(entitlements=entitlements, recommendations=recommendations)).post(
            "/api/v1/agent/decision", json={"prompt": "Find the best preview report under 0.01 USDC"}
        ).json()
        self.assertEqual(body["plan"]["action"], "purchase")
        self.assertEqual(body["resolved_candidate"]["provider_id"], "funding_memory")

    def test_session_policy_fields_validate_at_http_boundary(self):
        response = TestClient(make_app()).post(
            "/api/v1/agent/decision",
            json={"prompt": "monitor reports", "allowed_tiers": ["intraday"]},
        )
        self.assertEqual(response.status_code, 422)
