-- ============================================================================
-- Migration: 0016_concurrency_hardening.sql
-- Description: Concurrency hardening for creator claims, spending guardrails,
--              and atomic settlement claiming.
-- Protocol: Controlled Refactoring & Codebase Intelligence Protocol (CRCIP) P0.2
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Creator Claims Nonce Replay Unique Index
-- Prevents race conditions where concurrent workers attempt to replay the same
-- claim nonce for a creator wallet.
-- ----------------------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS idx_creator_claims_wallet_nonce
    ON public.qma_creator_claims (creator_wallet, (claim->>'nonce'))
    WHERE creator_wallet IS NOT NULL AND (claim->>'nonce') IS NOT NULL;

-- ----------------------------------------------------------------------------
-- 2. Invoices Payer & Status Composite Index
-- Optimizes concurrency locking and lookups on wallet-scoped invoice states.
-- ----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_invoices_payer_status
    ON public.qma_invoices (payer_address, status);

-- ----------------------------------------------------------------------------
-- 3. Atomic Spend Policy Hardening (Enforces minimum, wallet spend_cap, and balance)
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.reserve_agent_wallet_spend(
    p_wallet_address TEXT,
    p_amount         NUMERIC,
    p_spend_cap      NUMERIC DEFAULT 10000.0
) RETURNS BOOLEAN AS $$
DECLARE
    v_updated INT;
BEGIN
    IF p_amount <= 0 THEN
        RETURN FALSE;
    END IF;

    UPDATE public.agent_wallets
       SET spent_usdc = ROUND(spent_usdc + p_amount, 6),
           balance_usdc = ROUND(balance_usdc - p_amount, 6),
           updated_at = NOW()
     WHERE address = p_wallet_address
       AND ROUND(spent_usdc + p_amount, 6) <= LEAST(p_spend_cap, spend_cap_usdc)
       AND balance_usdc >= p_amount;

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated > 0;
END;
$$ LANGUAGE plpgsql;

-- ----------------------------------------------------------------------------
-- 4. Atomic Session Spend Reservation & Release
-- ----------------------------------------------------------------------------
ALTER TABLE public.agent_sessions ADD COLUMN IF NOT EXISTS spent_usdc NUMERIC(20,6) NOT NULL DEFAULT 0.0;

CREATE OR REPLACE FUNCTION public.reserve_session_spend(
    p_session_id TEXT,
    p_amount     NUMERIC
) RETURNS BOOLEAN AS $$
DECLARE
    v_updated INT;
BEGIN
    IF p_amount <= 0 THEN
        RETURN FALSE;
    END IF;

    UPDATE public.agent_sessions
       SET spent_usdc = ROUND(spent_usdc + p_amount, 6),
           updated_at = NOW()
     WHERE id = p_session_id
       AND ROUND(spent_usdc + p_amount, 6) <= budget_usdc;

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated > 0;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION public.release_session_spend(
    p_session_id TEXT,
    p_amount     NUMERIC
) RETURNS VOID AS $$
BEGIN
    UPDATE public.agent_sessions
       SET spent_usdc = GREATEST(0, ROUND(spent_usdc - p_amount, 6)),
           updated_at = NOW()
     WHERE id = p_session_id;
END;
$$ LANGUAGE plpgsql;
