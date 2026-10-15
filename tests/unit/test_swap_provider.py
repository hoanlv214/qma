"""Tests for the non-custodial fund-gateway plan builder in swap_executor."""

import pytest

from backend.app.services import swap_router as sr
from backend.app.services.swap_executor import build_fund_gateway_plan

WALLET = "0x9999999999999999999999999999999999999999"


@pytest.fixture(autouse=True)
def _router_on(monkeypatch):
    monkeypatch.setattr(sr, "SWAP_ROUTER_KILL_SWITCH", True)
    yield


def test_fund_gateway_plan_uniswap_steps(monkeypatch):
    def uni_stub(from_token, to_token, amount_in_raw):
        return {"amount_out_raw": 9_200_000, "path": [sr.SWAP_TOKENS[from_token]["address"], sr.SWAP_TOKENS["USDC"]["address"]], "note": "stub"}

    for venue in sr.VENUES:
        if venue["venue_id"] == "uniswap_v2":
            monkeypatch.setitem(venue, "adapter", uni_stub)
        else:
            monkeypatch.setitem(venue, "adapter", lambda *a, **k: None)

    monkeypatch.setattr(sr, "_anchor_rate", lambda from_token, to_token: None)

    plan = build_fund_gateway_plan("EURC", 10.0, WALLET)
    assert plan["available"] is True
    assert plan["non_custodial"] is True
    assert plan["to_token"] == "USDC"
    assert len(plan["steps"]) == 3  # approve, swap, gateway deposit
    assert plan["steps"][0]["calldata"].startswith("0x095ea7b3")  # approve(address,uint256)
    assert plan["steps"][1]["calldata"].startswith("0x38ed1739")  # swapExactTokensForTokens
    assert plan["steps"][2]["calldata"].startswith("0x")  # gateway deposit
    assert plan["min_out_raw"] == int(9_200_000 * 0.995)
    assert WALLET[2:].lower() in plan["steps"][1]["calldata"]


def test_fund_gateway_plan_usyc_single_redeem_step(monkeypatch):
    for venue in sr.VENUES:
        def stub(from_token, to_token, amount_in_raw, _vid=venue["venue_id"]):
            if _vid == "usyc_nav":
                return {"amount_out_raw": 10_000_000, "path": [], "note": "stub"}
            return None
        monkeypatch.setitem(venue, "adapter", stub)

    plan = build_fund_gateway_plan("USYC", 10.0, WALLET)
    assert plan["available"] is True
    assert len(plan["steps"]) == 2  # redeem + gateway deposit
    assert plan["steps"][0]["calldata"].startswith("0xba087652")


def test_fund_gateway_plan_no_route(monkeypatch):
    for venue in sr.VENUES:
        monkeypatch.setitem(venue, "adapter", lambda *a, **k: None)

    plan = build_fund_gateway_plan("EURC", 10.0, WALLET)
    assert plan["available"] is False
    assert plan["steps"] == []
    assert plan["reason"]
