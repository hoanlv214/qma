"""HTTP contract tests for the public traction snapshot."""

import unittest
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.v1.endpoints.platform import create_platform_router
from backend.app.services.payment_events_service import build_traction_snapshot
from backend.app.services.payment_ledger import compact_payment_event


NOW = 1_784_000_000.0


def event(invoice_id, settlement_id, amount, status, buyer_type, paid_at, leg=None):
    return {
        "invoice_id": invoice_id,
        "event_id": settlement_id,
        "settlement_id": settlement_id,
        "symbol": "APDSTOCK",
        "provider_id": "oi_memory",
        "tier": "full",
        "buyer_type": buyer_type,
        "amount_usdc": amount,
        "gateway_status": status,
        "paid_at": paid_at,
        "split_leg": leg,
    }


class TractionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = [
            event("inv_final", "settle_creator", 0.004, "completed", "agent", NOW - 86400, {"role": "creator"}),
            event("inv_final", "settle_platform", 0.001, "completed", "agent", NOW - 86400, {"role": "platform"}),
            event("inv_pending", "settle_pending", 0.005, "received", "human", NOW - 3600),
        ]
        summary = {
            "current_paid_count": 2,
            "current_revenue_usdc": 0.01,
            "current_unique_payers": 2,
            "revenue_by_provider": [{"provider_id": "oi_memory", "payments": 2, "revenue_usdc": 0.01}],
        }
        deps = SimpleNamespace(
            build_traction_snapshot=lambda events, summary, _compact_fn, **kwargs: build_traction_snapshot(
                events, summary, compact_payment_event, now=NOW, **kwargs
            ),
            compact_payment_event=compact_payment_event,
            load_platform_payment_events=lambda: cls.events,
            summarize_payment_events=lambda _events: summary,
        )
        app = FastAPI()
        app.include_router(create_platform_router(deps))
        cls.client = TestClient(app)

    def test_traction_response_and_settlement_filter(self):
        response = self.client.get("/api/v1/traction?days=14&recent_limit=10")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            set(payload),
            {"summary", "provenance", "daily_settled", "providers", "recent_settlements", "generated_at"},
        )
        self.assertEqual(payload["summary"]["current_paid_reports"], 2)
        self.assertEqual(payload["summary"]["settled_reports"], 1)
        self.assertEqual(payload["summary"]["settled_volume_usdc"], 0.005)
        self.assertEqual(payload["provenance"]["agent"]["reports"], 1)
        self.assertEqual(len(payload["recent_settlements"]), 2)
        self.assertNotIn("owner_wallet", payload["providers"][0])
        self.assertEqual(len(payload["daily_settled"]), 14)

    def test_traction_query_validation(self):
        self.assertEqual(self.client.get("/api/v1/traction?days=31").status_code, 422)
        self.assertEqual(self.client.get("/api/v1/traction?recent_limit=0").status_code, 422)
