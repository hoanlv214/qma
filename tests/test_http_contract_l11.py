"""Isolated HTTP contract tests for L-11 paid report entitlements."""

import copy
import os
import time
import unittest
from unittest.mock import patch

os.environ["SUPABASE_URL"] = ""
os.environ["QMA_SUPABASE_URL"] = ""
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = ""
os.environ["QMA_SUPABASE_SERVICE_ROLE_KEY"] = ""

from fastapi.testclient import TestClient

import backend.app.main as app_module


PAYER = "0x1111111111111111111111111111111111111111"
OTHER_WALLET = "0x4444444444444444444444444444444444444444"


class MemoryReportStorage:
    def __init__(self):
        self.reports = {}

    def save_paid_reports(self, reports):
        self.reports = copy.deepcopy(reports)

    def load_paid_reports(self):
        return copy.deepcopy(self.reports)

    def load_paid_report_by_id(self, address, entitlement_id):
        record = self.reports.get(entitlement_id)
        if record and str(record.get("payer_address", "")).lower() == address.lower():
            return copy.deepcopy(record)
        return None


def paid_invoice(invoice_id: str, tier: str) -> dict:
    query = {"symbol": "APDSTOCK"}
    provider = app_module.get_provider_or_404(app_module.provider_registry, "funding_memory")
    normalized_query = app_module.normalize_query_for_provider(provider, query)
    return {
        "invoice_id": invoice_id,
        "invoice_secret": f"secret_{invoice_id}_123456",
        "status": "paid",
        "created_at": time.time(),
        "expires_at": time.time() + 600,
        "paid_at": time.time(),
        "symbol": "APDSTOCK",
        "provider_id": "funding_memory",
        "owner_wallet": PAYER,
        "buyer_type": "human",
        "tier": tier,
        "resource_type": "qma_signal_report",
        "payer_address": PAYER,
        "settlement_id": f"settle_{invoice_id}",
        "gateway_status": "completed",
        "amount": "0.001000",
        "amount_raw": "1000",
        "pricing": {"amount_usdc": "0.001000"},
        "settlement": {"mode": "x402_direct_split", "currency": "USDC", "decimals": 6},
        "accounting": {"settlement_mode": "x402_direct_split"},
        "query": normalized_query,
        "query_hash": app_module.query_fingerprint(normalized_query),
        "verification_mode": "circle-gateway-x402-direct-split",
    }


class HttpContractL11Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app_module.app)

    def setUp(self):
        self.old_storage = app_module.storage_backend
        self.old_invoices = app_module.state.invoices_db
        self.old_reports = app_module.state.paid_reports
        self.storage = MemoryReportStorage()
        app_module.storage_backend = self.storage
        app_module.state.invoices_db = {}
        app_module.state.paid_reports = {}

    def tearDown(self):
        app_module.storage_backend = self.old_storage
        app_module.state.invoices_db = self.old_invoices
        app_module.state.paid_reports = self.old_reports

    def report_patches(self):
        return [
            patch.object(app_module, "_save_invoice", lambda *_args, **_kwargs: None),
            patch.object(app_module, "refresh_invoice_batch_tx", lambda _invoice: None),
            patch.object(
                app_module,
                "verify_access_token",
                lambda token: app_module.paid_kit.verify_access_token(
                    token,
                    secret=app_module.ACCESS_TOKEN_SECRET,
                ),
            ),
            patch.object(app_module, "verify_wallet_profile_token_service", lambda address, token, **_kwargs: {
                "scope": "wallet_profile",
                "wallet": address,
                "token": token,
            }),
        ]

    def test_preview_and_full_report_persist_and_reopen_by_owner(self):
        for tier in ("preview", "full"):
            invoice = paid_invoice(f"inv_l11_{tier}", tier)
            app_module.state.invoices_db[invoice["invoice_id"]] = invoice
            access_token = app_module.issue_invoice_access_token(invoice["invoice_id"], invoice)
            body = {"symbol": "APDSTOCK"}
            endpoint = f"/api/v1/providers/funding_memory/{tier if tier == 'preview' else 'full-report'}"
            with self.report_patches()[0], self.report_patches()[1], self.report_patches()[2], self.report_patches()[3]:
                response = self.client.post(
                    f"{endpoint}?invoice_id={invoice['invoice_id']}",
                    headers={"X-QMA-Access-Token": access_token},
                    json=body,
                )

            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            self.assertEqual(payload["tier"], tier)
            self.assertEqual(payload["query_symbol"], "APDSTOCK")
            self.assertEqual(payload["invoice"]["invoice_id"], invoice["invoice_id"])
            if tier == "preview":
                self.assertIn("top_analogs", payload)
                self.assertIn("upgrade_cta", payload)
            else:
                self.assertIn("analogs", payload)

            persisted = self.storage.load_paid_reports()
            self.assertTrue(persisted)
            entitlement_id, record = next(
                (item for item in persisted.items() if item[1].get("tier") == tier),
            )
            self.assertEqual(record["payer_address"].lower(), PAYER.lower())
            self.assertEqual(record["tier"], tier)
            self.assertIn("report", record)

            app_module.state.paid_reports = {}
            app_module.state.paid_reports.update(self.storage.load_paid_reports())
            with patch.object(app_module, "verify_wallet_profile_token_service", lambda address, token, **_kwargs: {"wallet": address}):
                reopened = self.client.get(
                    f"/api/v1/wallets/{PAYER}/reports/{entitlement_id}",
                    headers={"X-QMA-Wallet-Token": "wallet-token"},
                )

            self.assertEqual(reopened.status_code, 200)
            reopened_payload = reopened.json()
            self.assertEqual(set(reopened_payload), {"address", "entitlement"})
            self.assertEqual(reopened_payload["address"], PAYER)
            self.assertEqual(reopened_payload["entitlement"]["entitlement_id"], entitlement_id)

            with patch.object(app_module, "verify_wallet_profile_token_service", lambda address, token, **_kwargs: {"wallet": address}):
                wrong_owner = self.client.get(
                    f"/api/v1/wallets/{OTHER_WALLET}/reports/{entitlement_id}",
                    headers={"X-QMA-Wallet-Token": "wallet-token"},
                )
            self.assertEqual(wrong_owner.status_code, 404)

    def test_report_requires_access_token_and_preserves_response_contract(self):
        invoice = paid_invoice("inv_l11_missing_token", "preview")
        app_module.state.invoices_db[invoice["invoice_id"]] = invoice
        response = self.client.post(
            f"/api/v1/providers/funding_memory/preview?invoice_id={invoice['invoice_id']}",
            json={"symbol": "APDSTOCK"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("detail", response.json())

        with patch.object(app_module, "verify_wallet_profile_token_service", lambda *_args, **_kwargs: {"wallet": PAYER}):
            missing_wallet_token = self.client.get(
                "/api/v1/wallets/0x1111111111111111111111111111111111111111/reports/missing",
            )
        self.assertEqual(missing_wallet_token.status_code, 404)


if __name__ == "__main__":
    unittest.main()
