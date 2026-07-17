import tempfile
import unittest
from pathlib import Path

from paid_intelligence_kit.core import list_wallet_entitlements, record_entitlement
from storage import JsonStorage
from backend.app.services.payment_signing import sign_split_receipt, verify_split_receipt


AGENT_WALLET = "0x4859d0d0babdcc8c4d8d2d116258fd0e5f7ff67d"
BACKING_EOA = "0x4dbc321e301c82b8f8e6a5193e47c6eca656d514"
CREATOR = "0x2222222222222222222222222222222222222222"


class AgentWalletIdentityTests(unittest.TestCase):
    def test_entitlement_is_findable_by_agent_wallet_and_settlement_payer(self):
        store = {}
        invoice = {
            "provider_id": "oi_memory",
            "owner_wallet": CREATOR,
            "buyer_type": "agent",
            "symbol": "APDSTOCK",
            "tier": "full",
            "query_hash": "query-hash",
            "payer_address": BACKING_EOA,
            "buyer_wallet_address": AGENT_WALLET,
            "settlement_id": "split:inv_identity",
            "amount": "0.005924",
            "paid_at": 1,
        }
        record_entitlement(store, invoice=invoice, report={"symbol": "APDSTOCK"}, saved_at=1)

        self.assertEqual(len(list_wallet_entitlements(store, AGENT_WALLET)), 1)
        self.assertEqual(len(list_wallet_entitlements(store, BACKING_EOA)), 1)

    def test_json_storage_matches_both_wallet_identities_after_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = JsonStorage(
                ledger_path=str(root / "ledger.json"),
                reports_path=str(root / "reports.json"),
                invoices_path=str(root / "invoices.json"),
                creators_path=str(root / "creators.json"),
                provider_controls_path=str(root / "providers.json"),
            )
            record = {
                "entitlement-id": "ignored",
                "payer_address": BACKING_EOA,
                "buyer_wallet_address": AGENT_WALLET,
                "symbol": "APDSTOCK",
                "provider_id": "oi_memory",
                "tier": "full",
                "paid_at": 1,
                "report": {"symbol": "APDSTOCK"},
            }
            storage.save_paid_reports({"entitlement-id": record})
            reloaded = JsonStorage(
                ledger_path=str(root / "ledger.json"),
                reports_path=str(root / "reports.json"),
                invoices_path=str(root / "invoices.json"),
                creators_path=str(root / "creators.json"),
                provider_controls_path=str(root / "providers.json"),
            )

            self.assertEqual(len(reloaded.load_paid_reports_for_wallet(AGENT_WALLET)), 1)
            self.assertEqual(len(reloaded.load_paid_reports_for_wallet(BACKING_EOA)), 1)

    def test_split_receipt_binds_buyer_wallet_without_replacing_payer(self):
        kwargs = {
            "invoice_id": "inv_identity",
            "leg_id": "creator",
            "pay_to": CREATOR,
            "settled_amount_raw": "4739",
            "settlement_id": "settle_identity",
            "payer_address": BACKING_EOA,
            "gateway_status": "received",
            "buyer_wallet_address": AGENT_WALLET,
        }
        receipt = sign_split_receipt(**kwargs)
        self.assertTrue(verify_split_receipt(receipt=receipt, **kwargs))
        self.assertFalse(
            verify_split_receipt(
                receipt=receipt,
                **{**kwargs, "buyer_wallet_address": "0x5555555555555555555555555555555555555555"},
            )
        )


if __name__ == "__main__":
    unittest.main()
