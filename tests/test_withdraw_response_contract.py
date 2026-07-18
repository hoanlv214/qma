"""Full JSON response contract coverage for the withdraw endpoint."""

from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

import backend.app.main as app_module


def bytes32(address: str) -> str:
    return "0x" + address[2:].lower().zfill(64)


def test_withdraw_response_preserves_full_gateway_json_key_set():
    depositor = "0x1111111111111111111111111111111111111111"
    burn_intent = {
        "spec": {
            "sourceDomain": 26,
            "destinationDomain": 26,
            "sourceContract": bytes32(app_module.ARC_GATEWAY_WALLET),
            "destinationContract": bytes32(app_module.ARC_GATEWAY_MINTER),
            "sourceToken": bytes32(app_module.ARC_TESTNET_USDC),
            "destinationToken": bytes32(app_module.ARC_TESTNET_USDC),
            "sourceDepositor": bytes32(depositor),
            "destinationRecipient": bytes32(depositor),
            "sourceSigner": bytes32(depositor),
            "destinationCaller": bytes32("0x0000000000000000000000000000000000000000"),
            "value": "1000",
        }
    }
    gateway_response = Mock(
        ok=True,
        json=lambda: {
            "success": True,
            "attestation": "0x" + "ab" * 32,
            "signature": "0x" + "cd" * 65,
            "future_gateway_field": "x",
        },
    )

    with (
        patch.object(
            app_module,
            "authorized_gateway_withdraw_depositor",
            return_value={"address": depositor, "role": "platform_treasury", "provider_ids": []},
        ),
        patch.object(app_module, "WITHDRAW_MODE", "seller_wallet"),
        patch("requests.post", return_value=gateway_response),
    ):
        response = TestClient(app_module.app).post(
            "/api/v1/payment/withdraw",
            json={"burnIntent": burn_intent, "signature": "0x" + "ef" * 65},
        )

    assert response.status_code == 200, response.text
    assert set(response.json()) == {
        "success",
        "attestation",
        "signature",
        "future_gateway_field",
        "withdraw_mode",
        "relayed",
        "amount_usdc",
        "withdraw_owner",
    }
