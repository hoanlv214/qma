"""Test that infrastructure storage module and legacy shim export all required classes and factories."""

import tempfile
import os

def test_infrastructure_storage_exports():
    from backend.app.infrastructure.storage import (
        create_storage_backend,
        PostgresStorage,
        SupabaseStorage,
        JsonStorage,
        wallet_matches,
    )
    assert callable(create_storage_backend)
    assert PostgresStorage is not None
    assert SupabaseStorage is not None
    assert JsonStorage is not None
    assert callable(wallet_matches)


def test_legacy_storage_shim_exports():
    from storage import (
        create_storage_backend,
        PostgresStorage,
        SupabaseStorage,
        JsonStorage,
        wallet_matches,
    )
    assert callable(create_storage_backend)
    assert PostgresStorage is not None
    assert SupabaseStorage is not None
    assert JsonStorage is not None
    assert callable(wallet_matches)


def test_json_storage_lifecycle_in_tempdir():
    from backend.app.infrastructure.storage import JsonStorage

    with tempfile.TemporaryDirectory() as tmpdir:
        ledger_path = os.path.join(tmpdir, "ledger.json")
        reports_path = os.path.join(tmpdir, "reports.json")
        invoices_path = os.path.join(tmpdir, "invoices.json")
        creators_path = os.path.join(tmpdir, "creators.json")
        controls_path = os.path.join(tmpdir, "controls.json")

        store = JsonStorage(
            ledger_path=ledger_path,
            reports_path=reports_path,
            invoices_path=invoices_path,
            creators_path=creators_path,
            provider_controls_path=controls_path,
        )

        # Invoices save and load
        invoice = {
            "invoice_id": "inv_infra_test_001",
            "status": "pending",
            "amount": 10.0,
            "payer_address": "0x1111111111111111111111111111111111111111",
        }
        store.save_invoice(invoice)
        loaded = store.load_invoices().get("inv_infra_test_001")
        assert loaded is not None
        assert loaded["invoice_id"] == "inv_infra_test_001"
        assert loaded["status"] == "pending"

        # Update status
        invoice["status"] = "paid"
        store.save_invoice(invoice)
        loaded2 = store.load_invoices().get("inv_infra_test_001")
        assert loaded2["status"] == "paid"
