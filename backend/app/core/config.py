"""Configuration anchors for the QMA backend."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import logging
import os
import time


from backend.app.core.static_config import NETWORKS, ROOT_DIR, app_setting

def load_local_env(env_path: Path | None = None) -> None:
    """Load root .env values without overriding real environment variables."""
    target = env_path or ROOT_DIR / ".env"
    if not target.exists():
        return
    with target.open("r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key_clean = key.strip()
            if key_clean in ("DATABASE_URL", "POSTGRES_URL", "QMA_DATABASE_URL") and (
                "PYTEST_CURRENT_TEST" in os.environ
                or "PYTEST_VERSION" in os.environ
                or os.getenv("QMA_STORAGE_BACKEND") == "json"
            ):
                continue
            os.environ.setdefault(key_clean, value.strip().strip('"').strip("'"))


# Load env FIRST so all os.getenv() calls below see .env values
load_local_env()
DATA_DIR = Path(os.getenv("QMA_DATA_DIR") or ROOT_DIR)


# ---------------------------------------------------------------------------
# Brand & Project Identity (Single Source of Truth)
# Decision 2026-10-07: the public brand stays "QMA", repositioned as
# Intelligence, Decisions, Receipts. Code identifiers (QMA_* env prefix,
# qma_* tables, the qma CLI, GenQMAShield) are intentionally unchanged.
# ---------------------------------------------------------------------------
BRAND_NAME: str = str(app_setting("brand", "name"))
BRAND_CODENAME: str = "QMA"
BRAND_TITLE: str = str(app_setting("brand", "title"))
BRAND_TAGLINE: str = "Intelligence, decisions, receipts: per-query market memory for autonomous agents on Arc"
BRAND_DESCRIPTION: str = (
    "QMA sells intelligence: historical analog evidence for live market dislocations, "
    "purchased per query in sub-cent USDC. It powers decisions: autonomous agents and a "
    "policy-bounded treasury CFO acting inside deterministic spending caps. And it issues "
    "receipts: every query, GenLayer SLA verdict and payout lands on a SHA-256 hash-chained "
    "audit trail with on-chain settlement proof."
)
INTERNAL_QUANT_ENGINE: str = "QMA"  # Internal market-memory & anomaly matching engine
INTERNAL_TREASURY_MODULE: str = "QMA Treasury Engine"  # Internal corporate treasury & liquidity engine

# Centralized deployment URLs loaded from config/app.json (Single Source of Truth)
PUBLIC_API_URL: str = str(os.getenv("QMA_PUBLIC_API_URL") or app_setting("deployments", "publicApiUrl"))
PUBLIC_APP_URL: str = str(os.getenv("QMA_PUBLIC_APP_URL") or app_setting("deployments", "publicAppUrl"))
PUBLIC_MCP_URL: str = str(os.getenv("QMA_MCP_PUBLIC_URL") or app_setting("deployments", "publicMcpUrl"))
PUBLIC_DOCS_URL: str = str(os.getenv("QMA_PUBLIC_DOCS_URL") or app_setting("deployments", "publicDocsUrl"))


@dataclass(frozen=True)
class Settings:
    root_dir: Path = ROOT_DIR
    public_dir: Path = ROOT_DIR / "public"
    payment_ledger_path: Path = DATA_DIR / "payment_ledger.json"
    paid_reports_path: Path = DATA_DIR / "paid_reports.json"
    invoices_path: Path = DATA_DIR / "invoices.json"
    creator_applications_path: Path = DATA_DIR / "creator_applications.json"
    provider_controls_path: Path = DATA_DIR / "provider_controls.json"
    creator_claims_path: Path = DATA_DIR / "creator_claims.json"
    euthyna_audit_path: Path = DATA_DIR / "euthyna_audit_trail.json"
    treasury_policy_path: Path = DATA_DIR / "treasury_policy.json"
    earn_vault_positions_path: Path = DATA_DIR / "earn_vault_positions.json"
    brand_name: str = BRAND_NAME
    brand_codename: str = BRAND_CODENAME
    brand_tagline: str = BRAND_TAGLINE
    brand_description: str = BRAND_DESCRIPTION
    internal_quant_engine: str = INTERNAL_QUANT_ENGINE
    internal_treasury_module: str = INTERNAL_TREASURY_MODULE
    api_title: str = BRAND_TITLE
    api_version: str = "1.0.0"

    @property
    def access_token_secret(self) -> str:
        return os.getenv("QMA_ACCESS_TOKEN_SECRET") or os.getenv("QMA_SESSION_SECRET") or "qma-local-demo-secret-change-me"

    @property
    def cors_allowed_origins(self) -> list[str]:
        return [str(origin) for origin in app_setting("services", "corsAllowedOrigins")]


settings = Settings()


# ---------------------------------------------------------------------------
# Payment / pricing constants
# ---------------------------------------------------------------------------
# Per-network public chain data lives in config/networks.json (see static_config).
NETWORKS_CONFIG_PATH = ROOT_DIR / "config" / "networks.json"
NETWORKS_DATA: dict = NETWORKS

# ---------------------------------------------------------------------------
# Network Mode & Profiles (Testnet vs Mainnet)
# ---------------------------------------------------------------------------
# QMA_NETWORK_MODE="testnet" | "mainnet" is the ONLY network switch; everything else follows the profile.
NETWORK_MODE: str = os.getenv("QMA_NETWORK_MODE", "testnet").strip().lower()
IS_TESTNET: bool = NETWORK_MODE != "mainnet"

_active_profile = NETWORKS_DATA["testnet" if IS_TESTNET else "mainnet"]
_arc_preset = _active_profile["arc"]
_contracts_preset = _active_profile["contracts"]

# Sourced directly from config/networks.json based on NETWORK_MODE
ARC_CHAIN_ID: int = int(_arc_preset["chainId"])
ARC_RPC_URL: str = str(_arc_preset["rpcUrl"])
ARC_EXPLORER: str = str(_arc_preset["explorerUrl"])
ARC_EXPLORER_URL: str = ARC_EXPLORER  # Backward-compatible alias

ARC_USDC_ADDRESS: str = str(_arc_preset["usdcAddress"])
ARC_TESTNET_USDC: str = ARC_USDC_ADDRESS  # Backward-compatible alias
ARC_EURC_ADDRESS: str = str(_arc_preset["eurcAddress"])
ARC_USYC_VAULT_ADDRESS: str = str(_arc_preset["usycVaultAddress"])

# StableFX Configuration
STABLEFX_EURC_USD_RATE: float = float(app_setting("stablefx", "eurcUsdRate"))
STABLEFX_SPREAD_BPS: int = int(app_setting("stablefx", "spreadBps"))
STABLEFX_QUOTE_TTL_SECONDS: int = int(app_setting("stablefx", "quoteTtlSeconds"))

# ---------------------------------------------------------------------------
# Emergency Circuit Breaker & Operations Pause
# ---------------------------------------------------------------------------
# When set to 1, true, or yes, all on-chain treasury sweeps, redeems, swaps, and withdrawals are halted immediately.
# Accepts QMA_TREASURY_HALTED or QMA_TREASURY_HALT. Default: False.
_raw_halt = os.getenv("QMA_TREASURY_HALTED", os.getenv("QMA_TREASURY_HALT", "false")).strip().lower()
QMA_TREASURY_HALTED: bool = _raw_halt in ("1", "true", "yes", "on")
QMA_TREASURY_HALT: bool = QMA_TREASURY_HALTED  # Canonical backward-compatible alias
EMERGENCY_HALT_FLAG_FILE: Path = DATA_DIR / "EMERGENCY_HALT"
EMERGENCY_HALT_FLAG_NAME = "EMERGENCY_HALT"


def _runtime_flag_store() -> Optional[Any]:
    """Storage backend that persists shared runtime flags (PostgreSQL), if active."""
    try:
        from backend.app.core import state
        st = getattr(state, "storage_backend", None)
    except Exception:
        st = None
    if st is not None and hasattr(st, "get_runtime_flag") and hasattr(st, "set_runtime_flag"):
        return st
    return None


def emergency_halt_flag_active() -> bool:
    """True if the runtime emergency-halt flag is set. Raises on read failure."""
    store = _runtime_flag_store()
    if store is not None:
        return store.get_runtime_flag(EMERGENCY_HALT_FLAG_NAME) is not None
    return EMERGENCY_HALT_FLAG_FILE.exists()


def _write_emergency_halt_flag(payload: Dict[str, Any]) -> None:
    store = _runtime_flag_store()
    if store is not None:
        store.set_runtime_flag(EMERGENCY_HALT_FLAG_NAME, payload)
        return
    EMERGENCY_HALT_FLAG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(EMERGENCY_HALT_FLAG_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def _clear_emergency_halt_flag() -> None:
    store = _runtime_flag_store()
    if store is not None:
        store.clear_runtime_flag(EMERGENCY_HALT_FLAG_NAME)
        return
    if EMERGENCY_HALT_FLAG_FILE.exists():
        EMERGENCY_HALT_FLAG_FILE.unlink(missing_ok=True)


def set_emergency_halt(
    halted: bool,
    reason: str = "",
    operator: str = "system",
    acknowledge_active_incidents: bool = False,
) -> Dict[str, Any]:
    """Dynamically set or clear emergency halt across all workers via runtime flag file, storage policy, and Euthyna audit."""
    if not halted and not acknowledge_active_incidents:
        try:
            from backend.app.services.incident_engine import get_incidents
            from backend.app.schemas.incidents import IncidentSeverity, IncidentStatus
            open_p1 = get_incidents(severity=IncidentSeverity.P1_CRITICAL.value, status=IncidentStatus.OPEN.value)
            if open_p1:
                raise ValueError(
                    f"Controlled Recovery Refusal: Cannot lift emergency halt while {len(open_p1)} open P1 critical "
                    f"safety incidents exist (e.g. {open_p1[0].get('incident_id')}: {open_p1[0].get('rule')}). "
                    "Resolve incidents or provide acknowledge_active_incidents=True with operator sign-off."
                )
        except ValueError:
            raise
        except Exception as exc:
            logging.getLogger("qma.emergency_halt").warning("Incident check skipped during emergency halt check: %s", exc)

    flag_payload = {
        "halted": halted,
        "reason": reason,
        "operator": operator,
        "timestamp": time.time(),
    }

    try:
        if halted:
            _write_emergency_halt_flag(flag_payload)
        else:
            _clear_emergency_halt_flag()
    except Exception as exc:
        logging.getLogger("qma.emergency_halt").error("Failed to update EMERGENCY_HALT runtime flag: %s", exc)

    try:
        from backend.app.services.euthyna_audit import euthyna_audit_engine
        euthyna_audit_engine.record_action(
            action="EMERGENCY_HALT_TRIGGERED" if halted else "EMERGENCY_HALT_LIFTED",
            actor=operator or "admin",
            amount_usdc=0.0,
            balance_before=0.0,
            balance_after=0.0,
            usyc_shares=0.0,
            policy_rule="EMERGENCY_HALT_CONTROL",
            reasoning=f"Emergency halt {'activated' if halted else 'lifted'} by {operator}: {reason}",
        )
    except Exception as exc:
        logging.getLogger("qma.emergency_halt").warning("Euthyna audit recording for emergency halt skipped: %s", exc)

    try:
        from backend.app.services.usyc_treasury import usyc_treasury_service
        current_policy = usyc_treasury_service.get_policy(reload=True)
        if current_policy.treasury_halted != halted:
            updated = current_policy.model_copy(update={"treasury_halted": halted})
            usyc_treasury_service.set_policy(updated)
    except Exception as exc:
        logging.getLogger("qma.emergency_halt").warning("Failed to sync emergency halt to treasury policy: %s", exc)

    return flag_payload


def is_treasury_halted() -> bool:
    """Dynamic runtime evaluation of emergency halt across all money-moving operations.

    Evaluation precedence (fail-closed):
    1. Runtime flag: qma_runtime_flags.EMERGENCY_HALT in PostgreSQL (shared by every
       instance), or data/EMERGENCY_HALT under the json test backend.
    2. Environment variable: QMA_TREASURY_HALTED or QMA_TREASURY_HALT.
    3. Dynamic operator policy: CorporateTreasuryPolicy.treasury_halted (fresh reload from storage).
    4. Fails closed (returns True) if policy source fails or is corrupted.
    """
    # 1. Immediate runtime flag check
    try:
        if emergency_halt_flag_active():
            return True
    except Exception:
        return True  # Fail-closed on flag read error

    # 2. Process environment check
    env_halt = os.getenv("QMA_TREASURY_HALTED", os.getenv("QMA_TREASURY_HALT", "")).strip().lower()
    if env_halt in ("1", "true", "yes", "on"):
        return True

    # 3. Dynamic policy store check (fresh reload)
    try:
        from backend.app.services.usyc_treasury import usyc_treasury_service

        policy = usyc_treasury_service.get_policy(reload=True)
        return bool(getattr(policy, "treasury_halted", False))
    except Exception as exc:
        logging.getLogger("qma.emergency_halt").error(
            "Emergency halt policy read failed; failing closed for financial safety: %s", exc
        )
        return True


def enforce_single_instance_topology_guard() -> None:
    """Deployment Guardrail: Enforces single-container, single-worker execution.

    QMA concurrency primitives (cross_process_lock / fcntl.flock, SpendLimitGuard reservations,
    and swap execution logs) currently rely on single-container, single-process filesystem state.
    Multi-container or multi-worker deployment (even if REDIS_URL is present) is strictly forbidden
    because distributed locking (Redlock) and a shared distributed reservation store
    are not yet integrated end-to-end.
    """
    multi_instance = os.getenv("QMA_MULTI_INSTANCE", "0").strip().lower() in ("1", "true", "yes")
    render_instances = int(os.getenv("RENDER_INSTANCE_COUNT", os.getenv("INSTANCE_COUNT", "1")))
    if multi_instance or render_instances > 1:
        raise RuntimeError(
            "DEPLOYMENT TOPOLOGY ERROR: QMA requires single-container deployment (instance_count=1). "
            f"Detected configuration: instances={render_instances}, multi_instance={multi_instance}. "
            "Local OS advisory locks (fcntl.flock), in-memory spend reservations, and local file ledgers "
            "do not span separate container filesystems. Multi-container deployment is strictly forbidden "
            "until distributed locking (Redlock) and centralized reservation storage are implemented."
        )

    web_concurrency = int(os.getenv("WEB_CONCURRENCY", "1"))
    uvicorn_workers = int(os.getenv("UVICORN_WORKERS", os.getenv("WORKERS", "1")))
    if web_concurrency > 1 or uvicorn_workers > 1:
        raise RuntimeError(
            "DEPLOYMENT TOPOLOGY ERROR: QMA requires single-worker execution (workers=1). "
            f"Detected configuration: WEB_CONCURRENCY={web_concurrency}, UVICORN_WORKERS={uvicorn_workers}. "
            "In-memory SpendLimitGuard reservations and local state machines diverge across multiple worker "
            "processes. Enforce --workers 1 or WEB_CONCURRENCY=1 until a centralized reservation store is deployed."
        )

# ---------------------------------------------------------------------------



# Swap Router (headless DEX aggregation on Arc). DEX contract addresses are per-network
# in config/networks.json ("swap"); a network without DEX contracts disables the router.
# ---------------------------------------------------------------------------
_swap_preset: Optional[Dict[str, Any]] = _active_profile.get("swap")
SWAP_ROUTER_KILL_SWITCH: bool = bool(app_setting("swap", "enabled")) and _swap_preset is not None
# Execution is dry-run (unsigned calldata only) unless BOTH the config mode is "live" AND the
# operator sets the QMA_SWAP_EXECUTION_LIVE env confirmation (deliberate second key).
SWAP_EXECUTION_MODE: str = str(app_setting("swap", "executionMode")).strip().lower()
SWAP_EXECUTION_LIVE_CONFIRM: bool = os.getenv("QMA_SWAP_EXECUTION_LIVE", "0").strip().lower() in {"1", "true", "yes"}
SWAP_QUOTE_TTL_SECONDS: int = int(app_setting("swap", "quoteTtlSeconds"))
SWAP_SLIPPAGE_BPS: int = int(app_setting("swap", "slippageBps"))
SWAP_MAX_ANCHOR_DIVERSION_BPS: int = int(app_setting("swap", "maxAnchorDiversionBps"))
SWAP_QUOTE_TIMEOUT_SECONDS: float = float(app_setting("swap", "quoteTimeoutSeconds"))
SWAP_FEE_BPS: int = int(app_setting("swap", "feeBps"))
SWAP_FEE_MIN_USDC: float = float(app_setting("swap", "feeMinUsdc"))
SWAP_MAX_SINGLE_USDC: float = float(app_setting("swap", "maxSingleUsdc"))
SWAP_UNISWAP_V2_ROUTER: str = str((_swap_preset or {}).get("uniswapV2Router", ""))
SWAP_UNISWAP_V2_FACTORY: str = str((_swap_preset or {}).get("uniswapV2Factory", ""))
SWAP_WETH9_ADDRESS: str = str((_swap_preset or {}).get("weth9", ""))
SWAP_XYLO_STABLE_POOL: str = str((_swap_preset or {}).get("xyloStablePool", ""))
SWAP_LUNEX_SWAP_POOL: str = str((_swap_preset or {}).get("lunexSwapPool", ""))
# Arc gotcha: eth_estimateGas is unreliable — every write needs explicit gas.
SWAP_EXECUTE_GAS_LIMIT: int = int(app_setting("swap", "executeGasLimit"))
SWAP_SPREAD_SAMPLER_ENABLED: bool = bool(app_setting("swap", "spreadSamplerEnabled")) and SWAP_ROUTER_KILL_SWITCH
SWAP_SPREAD_SAMPLER_INTERVAL_SECONDS: int = int(app_setting("swap", "spreadSamplerIntervalSeconds"))

PAYMENT_AMOUNT_USDC = float(app_setting("pricing", "fullUsdc"))
PAYMENT_RESOURCE_TYPE = str(app_setting("payment", "resourceType"))
PAYMENT_NETWORK: str = f"eip155:{ARC_CHAIN_ID}"
PAYMENT_NETWORK_NAME: str = str(_arc_preset["name"])

# The platform treasury is also the x402 seller (same address on testnet and mainnet).
PLATFORM_TREASURY_ADDRESS: str = str(app_setting("platform", "treasuryAddress"))
PAYMENT_WALLET_ADDRESS: str = PLATFORM_TREASURY_ADDRESS

# ---------------------------------------------------------------------------
# Arc / Circle Gateway & Contracts
# ---------------------------------------------------------------------------
# Deployment wiring: URL of the qma-arc-gateway service (differs per environment).
ARC_GATEWAY_BASE_URL = os.getenv("QMA_ARC_GATEWAY_URL", "").strip().rstrip("/")
ARC_GATEWAY_API: str = str(_contracts_preset["gatewayApiUrl"])
ARC_GATEWAY_WALLET: str = str(_contracts_preset["gatewayWallet"])
ARC_GATEWAY_MINTER: str = str(_contracts_preset["gatewayMinter"])
ARC_GATEWAY_DOMAIN: int = int(_arc_preset["cctpDomain"])

MAINNET_GATEWAY_WALLET: str = str(NETWORKS_DATA["mainnet"]["contracts"]["gatewayWallet"])
SHIELD_CONTRACT_ADDRESS: str = str(_arc_preset["shieldContractAddress"])
ARC_HEDGE_RELAYER_CONTRACT = ARC_GATEWAY_WALLET
ARC_GATEWAY_INTERNAL_SECRET = os.getenv("QMA_ARC_GATEWAY_INTERNAL_SECRET", "")

# ---------------------------------------------------------------------------
# ERC-8004 AI Agent Registry & Identity
# ---------------------------------------------------------------------------
_erc8004_preset = _arc_preset.get("erc8004", {})
ERC8004_AGENT_ID: int = int(_erc8004_preset.get("agentId", 896885))
ERC8004_IDENTITY_REGISTRY: str = str(_erc8004_preset["identityRegistry"])
ERC8004_REPUTATION_REGISTRY: str = str(_erc8004_preset["reputationRegistry"])
ERC8004_VALIDATION_REGISTRY: str = str(_erc8004_preset["validationRegistry"])

ARC_STABLEFX_ESCROW: str = str(_contracts_preset["stableFxEscrow"])

# ---------------------------------------------------------------------------
# Withdraw
# ---------------------------------------------------------------------------
WITHDRAW_MODE = str(app_setting("withdraw", "mode")).strip().lower()
WITHDRAW_RELAYER_ADDRESS = str(app_setting("platform", "withdrawRelayerAddress"))
WITHDRAW_MIN_USDC = float(app_setting("withdraw", "minUsdc"))
WITHDRAW_RELAY_DAILY_LIMIT = int(app_setting("withdraw", "relayDailyLimit"))

# ---------------------------------------------------------------------------
# Creator claims
# ---------------------------------------------------------------------------
CREATOR_CLAIM_MIN_USDC = float(app_setting("creatorClaims", "minUsdc"))
CREATOR_CLAIM_INTENT_TTL_SECONDS = int(app_setting("creatorClaims", "intentTtlSeconds"))

# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------
DEFAULT_SETTLEMENT_MODE = str(app_setting("payment", "defaultSettlementMode")).strip().lower()
SPLIT_INVOICE_TTL_SECONDS = int(app_setting("payment", "splitInvoiceTtlSeconds"))
SETTLEMENT_RAIL = str(app_setting("payment", "settlementRail"))
SETTLEMENT_CURRENCY = "USDC"
SUPPORTED_SETTLEMENT_ASSETS = ["USDC"]
INVOICE_TTL_SECONDS = int(app_setting("payment", "invoiceTtlSeconds"))

# ---------------------------------------------------------------------------
# Access tokens
# ---------------------------------------------------------------------------
ACCESS_TOKEN_TTL_SECONDS = int(app_setting("payment", "accessTokenTtlSeconds"))
WALLET_PROFILE_TOKEN_TTL_SECONDS = int(app_setting("payment", "walletProfileTokenTtlSeconds"))
# Secrets (env only). The demo value is a local-dev placeholder that _assert_production_secrets refuses in prod.
ACCESS_TOKEN_SECRET = os.getenv("QMA_ACCESS_TOKEN_SECRET") or os.getenv("QMA_SESSION_SECRET") or "qma-local-demo-secret-change-me"
SPLIT_LEG_URL_SECRET = os.getenv("QMA_SPLIT_LEG_URL_SECRET") or f"split-url:{ACCESS_TOKEN_SECRET}"
SPLIT_RECEIPT_SECRET = os.getenv("QMA_SPLIT_RECEIPT_SECRET") or f"split-receipt:{ACCESS_TOKEN_SECRET}"


def _assert_production_secrets() -> None:
    if "PYTEST_CURRENT_TEST" in os.environ:
        return
    is_prod = (
        os.getenv("QMA_ENV", "").lower() in {"prod", "production"}
        or bool(os.getenv("RENDER"))
        or bool(os.getenv("RENDER_SERVICE_ID"))
    )
    if is_prod and (not ACCESS_TOKEN_SECRET or ACCESS_TOKEN_SECRET == "qma-local-demo-secret-change-me"):
        raise RuntimeError(
            "Refusing to boot with insecure QMA_ACCESS_TOKEN_SECRET. "
            "Set QMA_ACCESS_TOKEN_SECRET (and optionally QMA_SPLIT_RECEIPT_SECRET / QMA_SPLIT_LEG_URL_SECRET) before deploying."
        )


_assert_production_secrets()

# ---------------------------------------------------------------------------
# Hosted MCP server / OAuth 2.1 for connector clients
# ---------------------------------------------------------------------------
MCP_TOKEN_TTL_SECONDS = int(app_setting("mcp", "tokenTtlSeconds"))
MCP_MAX_BUDGET_USDC = float(app_setting("mcp", "maxBudgetUsdc"))
MCP_MAX_PRICE_USDC = float(app_setting("mcp", "maxPriceUsdc"))
AGENT_MAX_DECISION_BUDGET_USDC = float(app_setting("mcp", "agentMaxDecisionBudgetUsdc"))
# Deployment wiring: public URLs of the frontend and this API (set per environment;
# RENDER_EXTERNAL_URL is injected by the platform). oauth.py handles the local-dev case.
MCP_CONNECT_BASE_URL = os.getenv("QMA_MCP_CONNECT_BASE_URL", "").strip()
MCP_API_BASE_URL = (os.getenv("QMA_MCP_API_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").strip()

# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
ADMIN_TOKEN = os.getenv("QMA_ADMIN_TOKEN", "")
ADMIN_WALLET_ADDRESS = str(app_setting("platform", "adminWallet"))

# ---------------------------------------------------------------------------
# Rate limiting & Origin Shield
# ---------------------------------------------------------------------------
RATE_LIMIT_ENABLED = bool(app_setting("rateLimit", "enabled"))
RATE_LIMIT_WINDOW_SECONDS = int(app_setting("rateLimit", "windowSeconds"))
ORIGIN_SHIELD_SECRET = os.getenv("QMA_ORIGIN_SHIELD_SECRET", "").strip()


# ---------------------------------------------------------------------------
# Settlement verification
# ---------------------------------------------------------------------------
REQUIRE_COMPLETED_SETTLEMENT = bool(app_setting("payment", "requireCompletedSettlement"))

# ---------------------------------------------------------------------------
# Gateway deposit / batch
# ---------------------------------------------------------------------------
GATEWAY_DEFAULT_DEPOSIT_USDC = float(app_setting("gateway", "defaultDepositUsdc"))
GATEWAY_DEFAULT_APPROVE_USDC = float(app_setting("gateway", "defaultApproveUsdc"))
ARC_BATCH_TX_CACHE_TTL_SECONDS = int(app_setting("payment", "arcBatchTxCacheTtlSeconds"))
PAYMENT_EVENT_REFRESH_TTL_SECONDS = int(app_setting("payment", "paymentEventRefreshTtlSeconds"))

# ---------------------------------------------------------------------------
# Circle Onramp Kit (Fiat-to-USDC)
# ---------------------------------------------------------------------------
CIRCLE_ONRAMP_API_KEY = os.getenv("CIRCLE_ONRAMP_API_KEY") or os.getenv("CIRCLE_CONSOLE_API_KEY") or ""
CIRCLE_ONRAMP_BASE_URL = str(app_setting("onramp", "baseUrl"))
CIRCLE_ONRAMP_WIDGET_BASE_URL = str(app_setting("onramp", "widgetBaseUrl"))
CIRCLE_ONRAMP_REFERRER_DOMAIN = str(app_setting("onramp", "referrerDomain"))

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
CACHE_TTL_SECONDS = 30.0
