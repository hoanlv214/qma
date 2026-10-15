# QMA — Intelligence, Decisions, Receipts

> QMA (Quantitative Market Analogs) sells per-query market memory to autonomous agents:
> sub-cent USDC intelligence, policy-bounded decisions, and hash-chained receipts on Arc.
> Repo codename: qma.

[![live: qma.vercel.app](https://img.shields.io/badge/live-qma.vercel.app-1aa251)](https://qma.vercel.app)
[![brand: Intelligence · Decisions · Receipts](https://img.shields.io/badge/QMA-Intelligence_%C2%B7_Decisions_%C2%B7_Receipts-6366F1)](https://qma.vercel.app)
[![marketplace: Two-Sided Intelligence](https://img.shields.io/badge/marketplace-Two--Sided_Intelligence-2563EB)](docs/business/POSITIONING_STRATEGY.md)
[![API docs: onrender](https://img.shields.io/badge/API-qma--api.onrender.com-6E56CF)](https://qma-api.onrender.com/docs)
[![settles on Arc testnet](https://img.shields.io/badge/settles_on-Arc_testnet-1f1f1f)](https://testnet.arcscan.app)
[![payments: Circle x402 & StableFX](https://img.shields.io/badge/payments-Circle_x402_%26_StableFX-2775CA)](https://docs.arc.network)
[![yield: USYC ERC-4626 (Testnet Simulation)](https://img.shields.io/badge/yield-USYC_ERC--4626_(Testnet_Simulation)-F59E0B)](https://testnet.arcscan.app/address/0x934e7309d7fca371db946b0643f2136cc0a0fcb2)
[![audit: Euthyna SHA-256 (Off-chain Hash-Chain)](https://img.shields.io/badge/audit-Euthyna_SHA--256_(Postgres_Chained)-8B5CF6)](docs/audit/SECURITY_AND_AUDIT_REPORT.md)
[![whitepaper: v2.0](https://img.shields.io/badge/whitepaper-v2.0_Arc_Micropayments-0284c7)](docs/whitepaper/QMA_WHITEPAPER.md)

**A two-sided financial intelligence protocol and autonomous corporate treasury on Arc Testnet: quant creators monetize signals, autonomous AI agents purchase verified reports per query via Circle x402 USDC micropayments, and an autonomous AI CFO manages treasury cash-flows.**

🔗 Live Marketplace: **[qma.vercel.app](https://qma.vercel.app)** — interactive Signal Explorer & Treasury Radar  
&nbsp;·&nbsp; 📄 **[Technical Whitepaper](docs/whitepaper/QMA_WHITEPAPER.md)** — authoritative technical whitepaper (Arc L1, x402, GenLayer Shield)  
&nbsp;·&nbsp; ⚡ Backend: **[qma-api.onrender.com](https://qma-api.onrender.com)** — live API & OpenAPI docs at `/docs`  
&nbsp;·&nbsp; 🏛️ **[Arc RFB Alignment Audit](docs/arc/ARC_BUILDER_ALIGNMENT_AUDIT.md)** — strategic mapping against Circle Arc's Request for Builders  
&nbsp;·&nbsp; 📖 Strategy: **[Positioning & Business Strategy](docs/business/POSITIONING_STRATEGY.md)** — two-sided business constitution  
&nbsp;·&nbsp; 🧾 **[Policy vs Model research note](docs/research/POLICY_VS_MODEL.md)** — where the guardrails overruled the model, with hashes  
&nbsp;·&nbsp; 🔎 **[public proof](https://testnet.arcscan.app/address/0x934e7309d7fca371db946b0643f2136cc0a0fcb2)** — USYC ERC-4626 Vault & on-chain tx hashes on Arcscan  
&nbsp;·&nbsp; 🛡️ [Security & Audit Report](docs/audit/SECURITY_AND_AUDIT_REPORT.md) — formal threat model & verification report

---

## Technical Status & Verification Matrix

To ensure absolute truth in advertising and avoid confusing aspirational architecture with empirical codebase capabilities, every subsystem is audited and classified below:

| Subsystem / Capability | Current Status | Enforcement Level | Verification Evidence |
| :--- | :--- | :--- | :--- |
| **Market Data & Quantitative Reports** | `[Implemented]` | Production FastAPI + PostgreSQL | Endpoints live at `/api/v1/reports/` (MEXC, OKX, Pyth, Polymarket feeds). |
| **Circle x402 USDC Micropayments** | `[Implemented]` | Protocol-level (HTTP 402 + Arc Testnet) | EIP-712 payment authorization, replay defense, and idempotency key checks in `x402_gateway.py`. |
| **End-to-End Payment Latency** | `[Partially Implemented]` | 1.5s – 3.0s total HTTP roundtrip | Arc consensus finality is sub-second, but full HTTP invoice-to-data flow depends on client/relayer roundtrip. |
| **Agent Spending Policy & Caps** | `[Partially Implemented]` | Application-level (Node CLI + Python Backend) | Advisory limits in `spending_policy.py` & CLI pre-checks in `qma.js`. **Residual Risk:** No smart-contract on-chain enforcement. |
| **USYC Yield Vault (ERC-4626)** | `[Simulation]` | Synthetic Testnet Contract | Deployed at `0x934e...` on Arc Testnet. 5.0% APY is a mathematical model parameter (`projectedYield`); **not backed by real Hashnote USYC RWA**. |
| **Euthyna Continuous Audit** | `[Partially Implemented]` | Database-level (PostgreSQL SHA-256 Hash-chain) | Hash-chain verified in `euthyna_audit.py`. Logs tx hashes of Arc events. **On-chain State Root anchor is `[Planned]`**. |
| **GenLayer SLA Verification** | `[Partially Implemented]` | Relayer-assisted Cross-chain Bridge | Contract live on GenLayer Studio (`0x2143...`). Arc refund relies on an off-chain relayer bridge (`arc_verdict_settlement.py`), not atomic cross-chain escrow. |
| **Confidential Analytics (DeCC / Nillion)** | `[Backlog / Planned]` | None (0 lines of code) | Frozen until verified commercial client demand for private portfolio computation arises. |

---

## Positioning: three pillars

1. **The Market `[Implemented]`.** Creators publish quantitative report families (funding and liquidity, cross-market basis, oracle volatility). Buyers, human or agent, pay per query in USDC over x402. Creators keep 80% of every payment, rising to 85 / 87.5 / 90% as performance tiers advance.
2. **The CFO `[Partially Implemented / Simulation]`.** An autonomous treasury engine governs operating capital: written spending policy, application-level spend guardrails, idle-cash sweeps into a mock USYC ERC-4626 vault on Arc Testnet, and JIT redemption for payables.
3. **The Proof `[Partially Implemented]`.** Every settlement, payout, sweep, and policy override is recorded into the Euthyna SHA-256 hash-chained audit trail in PostgreSQL. `/traction` renders the live ledger.

---

## The Problem

Traditional financial intelligence forces two broken paradigms:
1. **For Signal Creators:** Talented quants and analysts must build bespoke SaaS billing, payment gateways, and user management just to monetize a quantitative signal or funding-rate model.
2. **For Autonomous Buyers (AI Agents & Traders):** Existing intelligence providers demand $500–$2,000/month recurring subscriptions just to query historical regime data on-demand. Autonomous agents require structured JSON payloads paid per query via stablecoins, with hard spending budgets and cryptographic verification.

## The Solution: Two-Sided Financial Intelligence Marketplace

The platform operates as a two-sided protocol:

1. **Supply Side (Quant Creators & Signal Providers) `[Implemented]`:**
   - Publish quantitative feeds (`POST /api/v1/creators/apply`) across funding anomalies, cross-market prediction basis, and oracle volatility.
   - Monetize directly per query in USDC with automatic revenue sharing.
   - Claim accrued earnings non-custodially via signed cryptographic proofs (`POST /api/v1/creators/claim`).
2. **Demand Side (Autonomous Agents & Algorithmic Buyers) `[Implemented]`:**
   - Pay-per-query (0.002 USDC Preview / 0.005 USDC Full) over HTTP via Circle Gateway x402 headers with zero subscription lock-in.
   - Enforce spending limits via client policies (`GET /api/v1/agent/spending-policy`).
   - Discover providers via **ERC-8004** (`/.well-known/agent.json`) and **ERC-8183** escrow tasks (`POST /api/v1/agent/jobs`).
3. **SLA & Verification (GenLayer Shield) `[Partially Implemented]`:**
   - Evaluates purchased intelligence payloads with LLM consensus on GenLayer Studio (`contracts/GenQMAShield.py`).
   - Verdict-driven refunds are orchestrated via an off-chain relayer bridge (`backend/app/services/arc_verdict_settlement.py`). When verification cannot conclude, the platform fails closed: the report stays locked and no auto-refund occurs.

### Internal Subsystems

To keep architecture clear:
- **QMA Engine `[Implemented]`:** The analytical engine matching live anomalies to historical regime archives and calculating analog distributions.
- **QMA Treasury Engine `[Partially Implemented / Simulation]`:** The corporate treasury module on Arc Testnet that maintains an operating buffer, sweeps surplus idle USDC into the mock ERC-4626 vault, redeems just-in-time for compute/oracle payables, and logs transactions via Euthyna SHA-256 audits.
- **Brand Status:** Centralized in `BRAND_CONFIG` (in `backend/app/core/config.py` and `frontend/src/config/branding.ts`).

---

## Autonomous Corporate Treasury & Liquidity Engine

While the marketplace handles commercial inflows and outflows, the internal treasury module governs cash-flow and runway:

- **SWEEP / KEEP / REDEEM with rationale** — every financial movement names the runway multiplier, excess reserves, and economic justification.
- **Dynamic reserve buffering** — scales the cash buffer up during high volatility and down during predictable inflow regimes.
- **Just-In-Time (JIT) redemption** — redeems the micro-amount required by incoming invoices from the vault contract.
- **Euthyna continuous audit `[Partially Implemented]`** — actions are hashed with financial context into a tamper-evident audit record (`POST /api/v1/treasury/audit/verify`).
- **Safety rails `[Partially Implemented]`** — application-layer deterministic invariants enforce transaction caps and minimum reserve thresholds.

Example trace (real on-chain output on Arc Testnet):

```text
QMA TREASURY ENGINE — AUTONOMOUS AI CFO ON ARC TESTNET
======================================================
Target Wallet: 0xf5987818EBBEe812EB730B6a395d66e664412cf5
Execution    : LIVE ON-CHAIN BROADCAST (Arc Testnet Chain ID 5042002)
Underlying   : USDC ERC-20 (0x3600000000000000000000000000000000000000)
USYC Vault   : 0x934e7309d7fca371db946b0643f2136cc0a0fcb2 (Testnet Simulation)

[forecast]  30-day runway required: $1.20 | Current liquid cash: $25.00 | Excess: $23.80
[decide]    SWEEP_IDLE — liquid reserves exceed safety buffer; sweeping 10.0 USDC into USYC Vault
[sweep]     Deposited 10.0 USDC into USYCVault (0x934e...) → Minted 10.0 yvUSYC shares (Tx: 0xd9b3... Block #62679606)
[bill]      Incoming payable #INV-PYTH-01 for $0.05 (Pyth Live Oracle Feed)
[decide]    JIT_REDEEM — operational cash below buffer; redeem 0.05 USDC from USYC principal
[redeem]    Burned 0.05 yvUSYC shares → Redeemed 0.05 USDC to liquid treasury (Tx: 0x705c... Block #62679616)
[audit]     Euthyna digest 0x7b23f8... verified · 0 unallocated cents · Ledger balanced
```

---

## The Money Rails: Truth in Advertising

Corporate treasury is about real capital, so claims must declare their boundaries:

- **Arc native USDC gas `[Implemented]`**: Fast block confirmation with USDC as native gas token.
- **USYC Yield Vault (`contracts/USYCVault.sol`) `[Simulation]`**: ERC-4626 vault deployed on Arc Testnet. Solvency is based on on-chain USDC held, but 5.0% APY is purely a simulation parameter. It is NOT connected to off-chain Hashnote USYC assets.
- **Circle x402 Micropayments `[Implemented]`**: HTTP 402 pay-per-request payables and receivables in native USDC.
- **Euthyna Audit Framework `[Partially Implemented]`**: State transitions chained via SHA-256 in PostgreSQL. On-chain anchor contract is pending implementation.
- **GenLayer Consensus Shield (`contracts/GenQMAShield.py`) `[Partially Implemented]`**: LLM consensus verification on GenLayer Studio; payout orchestration to Arc relies on an off-chain relayer.

---

## What is Live, What is Simulation, and What is Planned

- **Live on Arc Testnet:** x402 payment verification, mock USYC deposits and JIT redemptions (`0x934e...`), StableFX quote & settlement routing.
- **Live off-chain (Backend DB):** Euthyna SHA-256 hash-chained audit in PostgreSQL, spending policy advisory calculation, creator claims ledger.
- **Testnet Simulation:** USYC 5.0% APY (mathematical projection parameter in `USYCVault.sol`), GenLayer Studio dispute adjudication.
- **Planned / Roadmap:** On-chain Euthyna Anchor contract on Arc L1, Smart Contract / Account Abstraction hard spending enforcement, Atomic cross-chain escrow.

---

## Live Identifiers & Arc Testnet Proofs

*Arc Testnet (Chain ID `5042002`)*

| Component / Action | On-Chain Identifier | Proof Link | Verification Level |
| :--- | :--- | :--- | :--- |
| **USYC Yield Vault (ERC-4626)** | `0x934e7309d7fca371db946b0643f2136cc0a0fcb2` | [Arcscan Contract](https://testnet.arcscan.app/address/0x934e7309d7fca371db946b0643f2136cc0a0fcb2) | `[Simulation Contract]` |
| **Underlying Token (Arc USDC)** | `0x3600000000000000000000000000000000000000` | [Arcscan Token](https://testnet.arcscan.app/address/0x3600000000000000000000000000000000000000) | Arc L1 Token |
| **Approve Vault Allowance** | `0xc389ab7244cde76ea906bab77421e9f033e6481e3ddead7f30ba6a041bfefebe` | [Arcscan Tx](https://testnet.arcscan.app/tx/0xc389ab7244cde76ea906bab77421e9f033e6481e3ddead7f30ba6a041bfefebe) | Confirmed Historical Tx |
| **Autonomous Sweep Deposit** | `0xd9b31a246f0df00e08ceaf40b0f2892305bc820f0f9e8d0e7717b0b04e18edec` | [Arcscan Tx](https://testnet.arcscan.app/tx/0xd9b31a246f0df00e08ceaf40b0f2892305bc820f0f9e8d0e7717b0b04e18edec) | Block #62679606 |
| **Just-In-Time (JIT) Redemption** | `0x705c9e4b3ee7a99159082c8f800bb8fb6916e2acbc33f4743a33ca9a81e29629` | [Arcscan Tx](https://testnet.arcscan.app/tx/0x705c9e4b3ee7a99159082c8f800bb8fb6916e2acbc33f4743a33ca9a81e29629) | Block #62679616 |
| **GenLayer Shield Contract** | `0x2143EA5800c08356d3b2de3bFacE1c2431F7eD69` | [GenLayer Studio](https://studio.genlayer.com) | `[Studio Testnet]` |
| **Live Backend API** | `https://qma-api.onrender.com` | [OpenAPI Docs](https://qma-api.onrender.com/docs) | 24/7 Deployed |
| **Test Suite** | Unit, integration & docs regressions | [Local Test Suite](tests/) | Passing (Mock-heavy) |

---

## Architecture

```text
CLIENT / DASHBOARD                    AI CFO & TREASURY CORE                     ARC L1 BLOCKCHAIN
──────────────────                    ──────────────────────                     ─────────────────
┌──────────────────┐                  ┌───────────────────────────────┐          ┌──────────────────────┐
│ Treasury Radar   │                  │ FastAPI Autonomous Backend    │          │ USYC Yield Vault     │
│ React + Vite UI  │ ─── HTTP / SSE ─▶│                               │ ── EVM ─▶│ (ERC-4626)           │
│                  │                  │  • Cash-Flow Forecaster       │          │ 0x934e...            │
└──────────────────┘                  │  • Runway Buffer Calculator   │          └──────────┬───────────┘
                                      │  • JIT Liquidity Allocator    │                     │
┌──────────────────┐                  │  • Euthyna Audit Engine       │                     │ 5.0% target APY
│ Autonomous Agent │                  └──────────────┬────────────────┘                     ▼
│ CLI Runner       │                                 │                   ┌──────────────────────┐
│ (qma / agent_buyer.js) │ ─── JSON-RPC ─────────────┼──────────────────▶│ Native USDC Token    │
└──────────────────┘                                 │                   │ 0x3600...            │
                                                     ▼                   └──────────────────────┘
                                      ┌───────────────────────────────┐
                                      │ GenLayer Intelligent Shield   │
                                      │ SLA Consensus Verification    │
                                      │ (GenQMAShield.py)             │
                                      └───────────────────────────────┘
```

---

## Run it

### One-Command Quickstart (~30s)

Execute the autonomous CFO decision and settlement loop:

```bash
npm run demo:treasury
```

*Runs cash-flow forecasting, verifies treasury runway, executes an on-chain idle sweep into USYC, triggers JIT redemption for payables, and outputs cryptographic Euthyna audit verification.*

### Autonomous Buyer CLI

The canonical agent CLI is `qma` (`agents/bin/qma.js`, published as `@hoanlv214/qma-cli`):

```bash
qma agent run --task "funding anomaly watchlist" --budget 0.05 --max-purchases 5 --json
```

*The agent discovers providers, scores live anomalies, decides what to buy under its spending policy, pays per query via x402, and logs every decision.*

### Local Development Setup

```bash
# 1. Clone & install dependencies
git clone https://github.com/hoanlv214/qma.git
cd qma
npm install
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Set AGENT_PRIVATE_KEY and RPC_URL

# 3. Start Backend API
uvicorn backend.app.main:app --reload --port 8000

# 4. Start Frontend Radar
npm run dev:frontend    # http://localhost:5173

# 5. Run complete test suite
python -m pytest tests/ -q
```

---

## Repository Structure

```text
qma/
├── agents/                  # Autonomous agent runners and decision engines
│   ├── bin/qma.js           # Canonical CLI: bounded autonomous report buyer
│   └── bin/agent_buyer.js   # Payment executor: --treasury, --sweep, --redeem, --live
├── backend/                 # FastAPI REST API & Autonomous Financial Core
│   └── app/
│       ├── api/v1/          # Modular endpoints (/reports, /treasury, /orders)
│       ├── core/            # Config, lifecycle, state, and security middleware
│       ├── repositories/    # Storage engine: PostgreSQL with local JSON fallback
│       ├── schemas/         # Pydantic validation schemas
│       ├── sdk/             # Python Client SDK for external agents
│       └── services/        # USYC Treasury, Euthyna Audit, x402 Gateway, Oracles
├── contracts/               # Smart Contracts on Arc L1 & GenLayer
│   ├── USYCVault.sol        # ERC-4626 Yield Vault on Arc Testnet
│   └── GenQMAShield.py      # Intelligent Contract (SLA Consensus) on GenLayer
├── docs/                    # Architecture, API specifications, and research notes
│   ├── api/README.md        # Complete OpenAPI route inventory & schema docs
│   ├── research/            # Policy vs Model: guardrail override evidence
│   └── audit/               # Full security assessment, threat matrix, and audit
├── frontend/                # Production Vite + React Treasury & Intelligence Dashboard
├── tests/                   # Unit, integration, and OpenAPI regression tests
├── main.py                  # Root entrypoint shim for Render deployment
└── render.yaml              # Multi-service Render deployment manifest
```

---

## Enterprise Architecture & Economics

### 1. Hybrid Intelligence Architecture (Scenario A & B)
- **Scenario A (Default / Machine-to-Machine):** When querying via MCP or API without an AI key, the engine delivers ultra-fast, pure quantitative data (win rates, historical analogues, basis spreads, volatility z-scores, and EIP-712 execution intents). Zero server token overhead.
- **Scenario B (BYO-Key AI Executive Synthesis):** When a user or client attaches their own LLM API key (OpenAI / Gemini / Groq), the system automatically triggers specialized sub-agents to synthesize comprehensive natural language market commentary, executive briefings, and hedging strategies on top of the quantitative metrics.
- **Transparent Pricing:** All report tiers are priced at **0.002 USDC (Preview)** and **0.005 USDC (Full)** — transparent, predictable, and fully sustainable without legacy nanopayment friction.

### 2. Arc L1 Settlement & Money Rails
- **Native USDC Gas**: Arc eliminates volatile ETH gas tokens; all transactions settle in native USDC.
- **ERC-4626 USYC Yield**: Idle corporate treasury balances compound toward the 5.0% target APY in a tokenized vault instead of bleeding purchasing power.
- **Clean EVM Standards**: Standard Solidity smart contracts deployable to Arc Testnet (Chain ID `5042002`) and Arc Mainnet (Chain ID `5042`).

---

## Security & Honest Disclosures

Corporate treasury code must withstand adversarial conditions:

1. **Non-Custodial Separation**: The AI CFO operates under hardcoded deterministic constraints: minimum runway buffer, maximum single-tx sweep/redeem limits, and authenticated payees.
2. **Deterministic Safety Rails**: LLMs provide financial intelligence and proposals; deterministic smart contracts and Python validators enforce hard limits so hallucinations cannot cause overspending. See [Policy vs Model](docs/research/POLICY_VS_MODEL.md) for the recorded override evidence.
3. **No Secret Leaks**: Private keys never leave the local environment or authorized server enclave; transactions are signed locally via Viem/Web3.
4. **Dual-Backend Redundancy**: PostgreSQL persistence with automatic, transparent fallback to local JSON ledgers for zero downtime.

Full threat matrix, formal verification proofs, and mitigation details are documented in **[`docs/audit/SECURITY_AND_AUDIT_REPORT.md`](docs/audit/SECURITY_AND_AUDIT_REPORT.md)**. Known technical debt and pending upgrades are tracked in **[`docs/TECH_DEBT.md`](docs/TECH_DEBT.md)**.

---

## Stack

Solidity 0.8.20 · OpenZeppelin v5 · ERC-4626 · FastAPI · Python 3.12 · Viem · Node.js · React 19 · Vite · Tailwind CSS · Circle x402 · Arc L1 · GenLayer Intelligent Contracts.
