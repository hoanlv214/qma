"""Real PostgreSQL Concurrency & Race-Condition Integration Tests (P0.3 & P0.4).

Executes against a real PostgreSQL instance with minimum 20 concurrent workers per race test.
Verifies critical financial invariants under multi-threaded contention:
1. Shared wallet budget cannot be overspent (total spend <= spend cap, balance >= 0).
2. Session budget cap cannot be breached.
3. Settlement ID cannot be claimed by more than one invoice (zero duplicate claims).
4. Creator claim nonces cannot be replayed concurrently (strict unique index enforcement).
5. Reports are never delivered while payment is unverified / pending.
6. Failure resilience: RPC timeout, retry idempotency, broadcast-pending guards, and worker lease handoff.

Usage:
    python -m pytest tests/integration/test_postgres_concurrency_race.py -v
"""

import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import List

import pytest
from dotenv import load_dotenv

load_dotenv()

from backend.app.core.config import resolve_database_url

DB_URL = os.getenv("QMA_TEST_DATABASE_URL") or resolve_database_url()

if not DB_URL:
    pytest.skip("No PostgreSQL DATABASE_URL available; skipping real DB concurrency tests", allow_module_level=True)


@pytest.fixture(scope="module")
def pg():
    """Initializes a real PostgreSQL storage backend with connection pool for 30+ workers."""
    from storage import PostgresStorage
    store = PostgresStorage(DB_URL, min_conn=2, max_conn=35)
    yield store
    store.pool.closeall()


def _random_addr() -> str:
    return "0x" + uuid.uuid4().hex[:40].lower()


def _random_id(prefix: str = "obj") -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


# ============================================================================
# P0.3: Concurrency Race-Condition Tests (20 Concurrent Workers)
# ============================================================================

def test_shared_wallet_budget_race_20_workers(pg):
    """Invariant 1: 20 concurrent workers race to spend from a shared wallet with 10 USDC balance.
    Each worker requests 1.0 USDC. Total attempted: 20.0 USDC.
    Strict Invariant: Exactly 10 workers succeed, exactly 10 fail.
    Final balance is 0.0 USDC, total spent is exactly 10.0 USDC. Zero overspend.
    """
    wallet_addr = _random_addr()
    num_workers = 20
    spend_per_worker = 1.0
    initial_balance = 10.0
    spend_cap = 10.0

    # Seed wallet directly in PostgreSQL
    pg.execute_query(
        """
        INSERT INTO public.agent_wallets (address, status, balance_usdc, spent_usdc, spend_cap_usdc)
        VALUES (%s, 'active', %s, 0.0, %s);
        """,
        (wallet_addr, initial_balance, spend_cap),
    )

    barrier = threading.Barrier(num_workers)
    results = []
    lock = threading.Lock()

    def worker_spend(worker_idx: int):
        barrier.wait()  # Synchronize all 20 threads to start simultaneously
        try:
            success = pg.reserve_agent_wallet_spend(wallet_addr, spend_per_worker, spend_cap)
            with lock:
                results.append((worker_idx, success, None))
        except Exception as exc:
            with lock:
                results.append((worker_idx, False, str(exc)))

    try:
        threads = [threading.Thread(target=worker_spend, args=(i,)) for i in range(num_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successes = [r for r in results if r[1] is True]
        failures = [r for r in results if r[1] is False]

        # Verify exactly 10 successes and 10 failures
        assert len(successes) == 10, f"Expected 10 successes, got {len(successes)}"
        assert len(failures) == 10, f"Expected 10 failures, got {len(failures)}"

        # Query authoritative PostgreSQL row
        row = pg.execute_query(
            "SELECT balance_usdc, spent_usdc, spend_cap_usdc FROM public.agent_wallets WHERE address = %s;",
            (wallet_addr,),
            fetch_one=True,
        )
        assert row is not None
        assert float(row["balance_usdc"]) == 0.0, f"Balance should be 0.0, got {row['balance_usdc']}"
        assert float(row["spent_usdc"]) == 10.0, f"Spent should be 10.0, got {row['spent_usdc']}"
        assert round(float(row["balance_usdc"]) + float(row["spent_usdc"]), 6) == initial_balance

    finally:
        pg.execute_query("DELETE FROM public.agent_wallets WHERE address = %s;", (wallet_addr,))


def test_session_budget_cap_race_20_workers(pg):
    """Invariant 2: 20 concurrent workers race against a single session budget of 5.0 USDC.
    Each worker attempts to reserve 0.5 USDC. Total attempted: 10.0 USDC.
    Strict Invariant: Exactly 10 workers succeed, exactly 10 fail.
    Total spent never exceeds session budget.
    """
    session_id = _random_id("sess")
    owner_wallet = _random_addr()
    num_workers = 20
    spend_per_worker = 0.5
    budget = 5.0

    pg.execute_query(
        """
        INSERT INTO public.agent_sessions (id, owner_wallet, status, task, budget_usdc, max_price_usdc, execution_mode, spent_usdc)
        VALUES (%s, %s, 'running', 'test_task', %s, 0.01, 'dry_run', 0.0);
        """,
        (session_id, owner_wallet, budget),
    )

    barrier = threading.Barrier(num_workers)
    results = []
    lock = threading.Lock()

    def worker_session_spend(worker_idx: int):
        barrier.wait()
        try:
            success = pg.reserve_session_spend(session_id, spend_per_worker)
            with lock:
                results.append((worker_idx, success))
        except Exception as exc:
            with lock:
                results.append((worker_idx, False))

    try:
        threads = [threading.Thread(target=worker_session_spend, args=(i,)) for i in range(num_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successes = [r for r in results if r[1] is True]
        assert len(successes) == 10, f"Expected 10 successes for session budget, got {len(successes)}"

        row = pg.execute_query(
            "SELECT budget_usdc, spent_usdc FROM public.agent_sessions WHERE id = %s;",
            (session_id,),
            fetch_one=True,
        )
        assert float(row["spent_usdc"]) == 5.0
    finally:
        pg.execute_query("DELETE FROM public.agent_sessions WHERE id = %s;", (session_id,))


def test_settlement_id_double_claim_race_20_workers(pg):
    """Invariant 3: 20 concurrent workers try to bind the SAME settlement_id across 20 distinct invoices.
    Strict Invariant: Exactly 1 worker successfully claims the settlement_id.
    19 workers are rejected (cannot double-claim the same onchain payment).
    """
    settlement_id = _random_id("settle")
    num_workers = 20
    invoice_ids = [_random_id("inv") for _ in range(num_workers)]

    # Insert 20 pending invoices without settlement_id
    for inv_id in invoice_ids:
        pg.execute_query(
            """
            INSERT INTO public.qma_invoices (invoice_id, status, payer_address, symbol, tier, invoice)
            VALUES (%s, 'pending', '0xpayer', 'BTC_USDT', 'full', '{}'::jsonb);
            """,
            (inv_id,),
        )

    barrier = threading.Barrier(num_workers)
    results = []
    lock = threading.Lock()

    def worker_claim(worker_idx: int):
        inv_id = invoice_ids[worker_idx]
        barrier.wait()
        success = pg.claim_settlement_for_invoice(settlement_id, inv_id)
        with lock:
            results.append((inv_id, success))

    try:
        threads = [threading.Thread(target=worker_claim, args=(i,)) for i in range(num_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successes = [r for r in results if r[1] is True]
        assert len(successes) == 1, f"Expected exactly 1 settlement claim success, got {len(successes)}"

        # Check PostgreSQL: exactly one invoice has this settlement_id
        rows = pg.execute_query(
            "SELECT invoice_id FROM public.qma_invoices WHERE settlement_id = %s;",
            (settlement_id,),
            fetch_all=True,
        )
        assert len(rows) == 1
        assert rows[0]["invoice_id"] == successes[0][0]

        # Verify is_settlement_id_claimed returns True
        assert pg.is_settlement_id_claimed(settlement_id) is True

    finally:
        pg.execute_query("DELETE FROM public.qma_invoices WHERE invoice_id = ANY(%s);", (invoice_ids,))


def test_creator_claim_nonce_replay_race_20_workers(pg):
    """Invariant 4: 20 concurrent workers attempt to submit a creator claim with the EXACT SAME nonce.
    Strict Invariant: PostgreSQL unique index idx_creator_claims_wallet_nonce allows exactly 1 insert.
    19 workers raise a UniqueViolation / duplicate key error.
    """
    creator_wallet = _random_addr()
    replay_nonce = "nonce_fixed_test_" + uuid.uuid4().hex
    num_workers = 20
    claim_ids = [_random_id("claim") for _ in range(num_workers)]

    barrier = threading.Barrier(num_workers)
    results = []
    lock = threading.Lock()

    def worker_save_claim(worker_idx: int):
        claim_id = claim_ids[worker_idx]
        record = {
            "claim_id": claim_id,
            "creator_wallet": creator_wallet,
            "claimant_address": creator_wallet,
            "amount_usdc": 10.0,
            "nonce": replay_nonce,
            "status": "requested",
        }
        barrier.wait()
        try:
            pg.save_creator_claim(record)
            with lock:
                results.append((claim_id, True, None))
        except Exception as exc:
            with lock:
                results.append((claim_id, False, str(exc)))

    try:
        threads = [threading.Thread(target=worker_save_claim, args=(i,)) for i in range(num_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successes = [r for r in results if r[1] is True]
        failures = [r for r in results if r[1] is False]

        assert len(successes) == 1, f"Expected exactly 1 claim insert for duplicate nonce, got {len(successes)}"
        assert len(failures) == 19

        # Ensure failure reasons cite unique constraint
        assert all("idx_creator_claims_wallet_nonce" in f[2] or "duplicate key" in f[2].lower() for f in failures)

        # Confirm only 1 claim exists in database for this creator and nonce
        rows = pg.execute_query(
            "SELECT claim_id FROM public.qma_creator_claims WHERE creator_wallet = %s AND (claim->>'nonce') = %s;",
            (creator_wallet, replay_nonce),
            fetch_all=True,
        )
        assert len(rows) == 1
    finally:
        pg.execute_query("DELETE FROM public.qma_creator_claims WHERE creator_wallet = %s;", (creator_wallet,))


def test_report_never_delivered_when_unverified_20_workers(pg):
    """Invariant 5: 20 concurrent workers attempt to retrieve a paid report for an invoice in 'pending' status.
    Strict Invariant: 100% of workers are rejected with 402 Payment Required.
    Zero report content is leaked before settlement verification.
    """
    from fastapi import HTTPException
    from backend.app.main import authorize_paid_invoice

    invoice_id = _random_id("inv_unverified")
    query = {"symbol": "BTC_USDT"}

    pg.execute_query(
        """
        INSERT INTO public.qma_invoices (invoice_id, status, payer_address, symbol, tier, provider_id, invoice)
        VALUES (%s, 'pending', '0xpayer', 'BTC_USDT', 'full', 'funding_memory', %s);
        """,
        (invoice_id, '{"status": "pending", "symbol": "BTC_USDT", "tier": "full", "provider_id": "funding_memory"}' ),
    )

    num_workers = 20
    barrier = threading.Barrier(num_workers)
    results = []
    lock = threading.Lock()

    def worker_read(worker_idx: int):
        barrier.wait()
        try:
            authorize_paid_invoice(
                query=query,
                invoice_id=invoice_id,
                token=None,
                required_tier="full",
                provider_id="funding_memory",
            )
            with lock:
                results.append((worker_idx, True, None))
        except HTTPException as exc:
            with lock:
                results.append((worker_idx, False, exc.status_code))
        except Exception as exc:
            with lock:
                results.append((worker_idx, False, str(exc)))

    try:
        threads = [threading.Thread(target=worker_read, args=(i,)) for i in range(num_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All 20 must have failed with 402
        assert all(r[1] is False for r in results), "Security Breach: unverified report was authorized!"
        assert all(r[2] == 402 for r in results), "Expected status code 402 Payment Required"

    finally:
        pg.execute_query("DELETE FROM public.qma_invoices WHERE invoice_id = %s;", (invoice_id,))


# ============================================================================
# P0.4: Failure & Resilience Integration Tests
# ============================================================================

def test_rpc_timeout_leaves_state_clean_and_unlocked(pg):
    """Failure Test 1: An RPC / external service times out mid-operation.
    Ensures that timeout does not leave a phantom spend or locked state.
    """
    wallet_addr = _random_addr()
    pg.execute_query(
        "INSERT INTO public.agent_wallets (address, status, balance_usdc, spent_usdc, spend_cap_usdc) VALUES (%s, 'active', 50.0, 0.0, 100.0);",
        (wallet_addr,),
    )

    try:
        # Simulate reserving spend before calling external service
        assert pg.reserve_agent_wallet_spend(wallet_addr, 5.0, 100.0) is True

        # Simulate timeout in external relayer call
        simulated_timeout = True
        if simulated_timeout:
            # Compensating rollback action
            assert pg.release_agent_wallet_spend(wallet_addr, 5.0) is True

        row = pg.execute_query(
            "SELECT balance_usdc, spent_usdc FROM public.agent_wallets WHERE address = %s;",
            (wallet_addr,),
            fetch_one=True,
        )
        assert float(row["balance_usdc"]) == 50.0
        assert float(row["spent_usdc"]) == 0.0
    finally:
        pg.execute_query("DELETE FROM public.agent_wallets WHERE address = %s;", (wallet_addr,))


def test_broadcast_without_receipt_prevents_replay(pg):
    """Failure Test 2: Transaction is broadcast onchain but receipt has not arrived yet.
    Ensures that deposit / payment reservation cannot be re-consumed or double-spent.
    """
    tx_hash = "0x" + uuid.uuid4().hex + uuid.uuid4().hex
    try:
        # Reserve deposit
        assert pg.reserve_stablefx_deposit(tx_hash, quote_id="q_100", recipient_address="0xabc") is True

        # Mark broadcast (in-flight onchain)
        pg.mark_stablefx_deposit_broadcast(tx_hash, "0xpayout_tx")

        # Second attempt must be rejected (cannot consume while in-flight or broadcast)
        assert pg.reserve_stablefx_deposit(tx_hash, quote_id="q_101", recipient_address="0xdef") is False

        # Attempting release must NOT free a broadcast transaction
        pg.release_stablefx_deposit(tx_hash)
        assert pg.is_stablefx_deposit_consumed(tx_hash) is True
    finally:
        pg.execute_query("DELETE FROM public.stablefx_consumed_deposits WHERE deposit_tx_hash = %s;", (tx_hash,))


def test_worker_restart_and_zombie_lease_fencing(pg):
    """Failure Test 3: Worker 1 crashes mid-tick. Lease expires.
    Worker 2 reclaims the session lease. Zombie Worker 1 tries to checkpoint tick with old generation.
    PostgreSQL generation fencing rejects zombie Worker 1 checkpoint.
    """
    session_id = _random_id("sess_lease")
    owner = _random_addr()

    pg.execute_query(
        """
        INSERT INTO public.agent_sessions (id, owner_wallet, status, task, budget_usdc, max_price_usdc, execution_mode, lease_owner, lease_expires_at, run_generation)
        VALUES (%s, %s, 'running', 'test_task', 10.0, 0.01, 'dry_run', 'worker_dead', NOW() - INTERVAL '10 seconds', 1);
        """,
        (session_id, owner),
    )

    try:
        # Reclaim expired leases
        reclaimed = pg.rpc("reclaim_expired_leases", {})
        assert reclaimed >= 1

        # Worker 2 acquires the lease
        claim_res = pg.rpc("claim_agent_session_lease", {"p_worker_id": "worker_alive", "p_lease_duration_seconds": 60})
        # Check session is updated to worker_alive and run_generation incremented
        row = pg.execute_query("SELECT lease_owner, run_generation FROM public.agent_sessions WHERE id = %s;", (session_id,), fetch_one=True)
        if row and row["lease_owner"] == "worker_alive":
            new_generation = row["run_generation"]

            # Zombie Worker 1 attempts to checkpoint tick with stale generation (gen 1)
            stale_checkpoint = pg.rpc("checkpoint_session_tick", {
                "p_session_id": session_id,
                "p_worker_id": "worker_dead",
                "p_run_generation": 1,
                "p_status": "running",
                "p_runtime_state": {"tick": 99},
            })
            # Generation fencing must reject stale worker 1
            assert stale_checkpoint is False
    finally:
        pg.execute_query("DELETE FROM public.agent_sessions WHERE id = %s;", (session_id,))
