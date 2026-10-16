"""
Comprehensive test suite for the 4 Strategic Growth Pillars:
1. ERC-8004 Agent Identity & ERC-8183 Escrowed Jobs
2. Circle Agent Wallet, Marketplace & Spending Policy
3. Core Quantitative Models (Funding Disparity & Open Interest Regime)
4. Dynamic Fee Royalty (Quant Performance) & Proof-of-Spend Reputation Badges
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.providers_meta import (
    compute_dynamic_creator_share_bps,
    compute_proof_of_spend_badge,
)


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Pillar 1 & 2: Agent Standards (ERC-8004, ERC-8183) & Circle Integration
# ---------------------------------------------------------------------------

def test_erc8004_agent_card_well_known_and_identity_endpoints(client):
    """Verifies that ERC-8004 discovery endpoints return valid agent metadata."""
    res1 = client.get("/.well-known/agent.json")
    assert res1.status_code == 200
    card = res1.json()
    assert card["standard"] == "ERC-8004"
    assert card["name"] == "QMA Autonomous Intelligence Agent"
    assert "0x367728bf66Cf962Ce15fD2b65193b7a1466f087c" in card["agent_address"]
    assert card["chain_id"] in (50, 5042, 5042002)
    assert "funding_disparity_analysis" in card["capabilities"]
    assert "open_interest_regime_modeling" in card["capabilities"]
    assert "x402" in card["supported_protocols"]
    assert "erc8183" in card["supported_protocols"]
    assert card["verification"]["engine"] == "GenLayer Intelligent Contract"

    res2 = client.get("/api/v1/agent/identity")
    assert res2.status_code == 200
    assert res2.json()["standard"] == "ERC-8004"


def test_circle_marketplace_service_card(client):
    """Verifies Circle Agent Marketplace descriptor for zero-code discovery."""
    res1 = client.get("/.well-known/circle-service.json")
    assert res1.status_code == 200
    service = res1.json()
    assert service["schema_version"] == "1.0"
    assert service["service_id"] == "qma-market-intelligence"
    assert service["payment_rail"] == "x402"
    assert service["currency"] == "USDC"
    assert "funding_memory" in service["pricing"]
    assert "oi_memory" in service["pricing"]

    res2 = client.get("/api/v1/marketplace/service-card")
    assert res2.status_code == 200
    assert res2.json()["service_id"] == "qma-market-intelligence"


def test_erc8183_unpaid_job_requires_invoice_payment(client):
    """An unpaid job must not fabricate a report, consensus, or reputation."""
    # Submit job for funding_memory
    req = {
        "job_type": "funding_anomaly_detection",
        "provider_id": "funding_memory",
        "query": {
            "symbol": "BTC",
            "fundingRate": -0.005,
        },
        "tier": "preview",
        "max_budget_usdc": 0.01,
        "buyer_agent_id": "claude-autonomous-agent",
    }
    res = client.post("/api/v1/agent/jobs", json=req)
    assert res.status_code == 402
    invoice = res.json()["detail"]["invoice"]
    assert invoice["provider_id"] == "funding_memory"
    assert invoice["invoice_id"].startswith("inv_")
    assert "consensus_verification" not in res.json()
    assert "reputation_points_accrued" not in res.json()
    inspect_res = client.get(f"/api/v1/agent/jobs/job_{invoice['invoice_id']}")
    assert inspect_res.status_code == 402


def test_spending_policy_advisory_evaluation(client):
    """Evaluations read spending without reserving or moving funds."""
    # Check default policy caps
    cfg = client.get("/api/v1/agent/spending-policy").json()
    assert cfg["standard"] == "circle-wallet-policy-v1"
    assert cfg["max_per_tx_usdc"] == 0.05
    assert cfg["daily_cap_usdc"] == 1.00
    assert cfg["enforce_strict"] is False

    test_wallet = "0x8888888888888888888888888888888888888888"

    # Transaction within budget (0.01 USDC <= 0.05)
    eval1 = client.post(
        "/api/v1/agent/spending-policy/evaluate",
        json={"amount_usdc": 0.01, "wallet_address": test_wallet},
    ).json()
    assert eval1["allowed"] is True
    assert eval1["current_spend_today_usdc"] == 0

    # Transaction exceeding single tx cap (0.10 USDC > 0.05)
    eval2 = client.post(
        "/api/v1/agent/spending-policy/evaluate",
        json={"amount_usdc": 0.10, "wallet_address": test_wallet},
    ).json()
    assert eval2["allowed"] is False
    assert "exceeds single transaction cap" in eval2["reason"]


def test_wallet_config_passkey_and_modular(client):
    """Verifies Circle Modular Wallets & WebAuthn passkey configuration."""
    res = client.get("/api/v1/agent/wallet-config")
    assert res.status_code == 200
    data = res.json()
    assert "circle_modular_passkey" in data["supported_methods"]
    assert data["passkey_supported"] is True
    assert data["gasless_transactions"] is True
    assert "Circle Gas Station" in data["paymaster_rail"]


# ---------------------------------------------------------------------------
# Pillar 3: Core Quantitative Models (Funding Disparity & OI Regime)
# ---------------------------------------------------------------------------

def test_quantitative_models_active(client):
    """Verifies that only genuine quantitative models (funding_memory & oi_memory) are active."""
    res = client.get("/api/v1/providers")
    assert res.status_code == 200
    providers = res.json()["providers"]
    provider_ids = {p.get("provider_id") or p.get("id") for p in providers}
    assert provider_ids == {"funding_memory", "oi_memory"}


# ---------------------------------------------------------------------------
# Pillar 4: Dynamic Fee Royalty & Proof-of-Spend Reputation
# ---------------------------------------------------------------------------

def test_dynamic_creator_royalty_bps():
    # Base fee (no verified track record or win rate < 80%)
    assert compute_dynamic_creator_share_bps(8000, win_rate=0.75, total_signals=10) == 8000
    assert compute_dynamic_creator_share_bps(8000, win_rate=0.95, total_signals=2) == 8000

    # Win rate >= 80% with >= 5 signals -> 85%
    assert compute_dynamic_creator_share_bps(8000, win_rate=0.81, total_signals=10) == 8500

    # Win rate >= 85% -> 87.5%
    assert compute_dynamic_creator_share_bps(8000, win_rate=0.86, total_signals=10) == 8750

    # Win rate >= 90% -> 90%
    assert compute_dynamic_creator_share_bps(8000, win_rate=0.92, total_signals=15) == 9000


def test_proof_of_spend_reputation_tiers():
    assert compute_proof_of_spend_badge(50.0)["tier"] == "GENESIS"
    assert compute_proof_of_spend_badge(150.0)["tier"] == "BRONZE"
    assert compute_proof_of_spend_badge(600.0)["tier"] == "SILVER"
    assert compute_proof_of_spend_badge(1200.0)["tier"] == "GOLD"
    assert compute_proof_of_spend_badge(1200.0)["verified_onchain"] is True
