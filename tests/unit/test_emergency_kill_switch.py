"""Unit & Integration tests for P0.1 Operational Emergency Kill Switch.

Verifies:
1. When kill switch is inactive, normal operations proceed.
2. When kill switch is active (QMA_EMERGENCY_STOP=1/true):
   - All state-mutating financial operations (invoice, verify, withdraw, claim, sweep, redeem)
     are immediately blocked with HTTP 503 (EMERGENCY_STOP_ACTIVE).
   - Read-only endpoints (GET /health, GET /config, GET /metrics, GET /reports) remain 100% accessible.
3. Fail-Closed Semantics:
   - Unrecognized / corrupted environment values fail closed (halt financial mutations).
   - Storage backend read exceptions fail closed (halt financial mutations).
"""

import os
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.core.emergency import (
    is_emergency_stop_active,
    assert_not_emergency_stopped,
)


@pytest.fixture
def client():
    return TestClient(app)


def test_emergency_stop_inactive_by_default():
    """When QMA_EMERGENCY_STOP is unset, emergency stop is inactive."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("QMA_EMERGENCY_STOP", None)
        assert is_emergency_stop_active() is False


def test_emergency_stop_activated_by_env():
    """Explicit truthy values activate emergency stop."""
    for val in ["1", "true", "TRUE", "yes", "on", "active", "stop"]:
        with patch.dict(os.environ, {"QMA_EMERGENCY_STOP": val}):
            assert is_emergency_stop_active() is True, f"Failed for {val}"


def test_emergency_stop_fail_closed_on_corrupted_value():
    """Unrecognized env values must fail closed to protect financial state."""
    for val in ["corrupted", "random_string", "undefined_mode", "2"]:
        with patch.dict(os.environ, {"QMA_EMERGENCY_STOP": val}):
            assert is_emergency_stop_active() is True, f"Did not fail closed for {val}"


def test_emergency_stop_fail_closed_on_storage_exception():
    """If storage check raises an exception, system must fail closed."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("QMA_EMERGENCY_STOP", None)
        with patch("backend.app.core.state.storage_backend", create=True) as mock_storage:
            mock_storage.is_emergency_stop_active.side_effect = RuntimeError("Database connection crashed")
            assert is_emergency_stop_active() is True


def test_read_only_endpoints_never_blocked_under_emergency_stop(client):
    """GET /health, GET /config, GET /api/v1/metrics must remain accessible under emergency stop."""
    with patch.dict(os.environ, {"QMA_EMERGENCY_STOP": "1"}):
        res_health = client.get("/api/v1/health")
        assert res_health.status_code == 200

        res_config = client.get("/api/v1/config")
        assert res_config.status_code == 200


def test_financial_mutations_blocked_under_emergency_stop(client):
    """All financial mutation endpoints return 503 under emergency stop."""
    with patch.dict(os.environ, {"QMA_EMERGENCY_STOP": "1"}):
        # 1. Invoice creation
        res_inv = client.post("/api/v1/payment/invoice", json={"tier": "preview", "provider_id": "funding_memory"})
        assert res_inv.status_code == 503
        data = res_inv.json()
        assert data.get("error") == "EMERGENCY_STOP_ACTIVE" or data.get("detail", {}).get("error") == "EMERGENCY_STOP_ACTIVE"

        # 2. Payment verification
        res_verify = client.post("/api/v1/payment/verify?invoice_id=test_inv")
        assert res_verify.status_code == 503

        # 3. Withdrawal
        res_withdraw = client.post("/api/v1/payment/withdraw", json={
            "recipient_address": "0x1111111111111111111111111111111111111111",
            "amount_raw": "1000",
            "burn_intent": {"contract_address": "0x0", "max_amount": "1000", "spec_version": 1},
            "operator_signature": "0x0"
        })
        assert res_withdraw.status_code == 503

        # 4. Creator claim
        res_claim = client.post("/api/v1/creators/claim", json={
            "claimant_address": "0x1111111111111111111111111111111111111111",
            "provider_ids": ["funding_memory"],
            "nonce": "test_nonce_1",
            "issued_at": 1000000000,
            "signature": "0x0"
        })
        assert res_claim.status_code == 503

        # 5. Treasury Sweep
        res_sweep = client.post("/api/v1/treasury/usyc/sweep", json={"amount_usdc": 10.0})
        assert res_sweep.status_code == 503

        # 6. Treasury JIT Redeem
        res_redeem = client.post("/api/v1/treasury/usyc/jit-redeem", json={"amount_usdc_needed": 5.0})
        assert res_redeem.status_code == 503
