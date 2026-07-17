# QMA

## Market intelligence that agents can discover, buy, and unlock

QMA is a pay-per-call marketplace for quantitative market intelligence. A
human or autonomous agent can compare live market signals, choose a provider
and report tier, pay a small USDC invoice, and unlock the exact historical
report bound to that purchase.

The payment rail is Circle Gateway/x402 on Arc Testnet. The backend remains the
authority for prices, invoices, settlement, entitlements, and access tokens.

## Start here

| Entry point | Link or command |
| --- | --- |
| React application | [qma-three.vercel.app](https://qma-three.vercel.app) |
| Rebuild API | [qma-api-rebuild.onrender.com](https://qma-api-rebuild.onrender.com) |
| Arc Gateway sidecar | [qma-arc-gateway-rebuild.onrender.com](https://qma-arc-gateway-rebuild.onrender.com) |
| API documentation | `/docs` on the active API deployment |
| CLI autonomous session | `npm run agent` |
| Marketplace | `/marketplace` on the React application |
| Metrics | `/api/v1/metrics?payment_page_size=1&payer_page_size=1` |

The rebuild services are Arc Testnet targets. Verify the deployment branch and
environment configuration before treating a live URL as current; see
[docs/DEPLOYMENT_SETUP.md](docs/DEPLOYMENT_SETUP.md).

## The problem

Market intelligence is useful only when the buyer can access the right
snapshot at the right time. A conventional dashboard gives every user the same
surface, while a conventional subscription hides the cost of each report.
Agents need a more precise primitive:

```text
find a useful signal
  -> compare provider, score, tier, and price
  -> buy only when the report fits the task and budget
  -> receive a verifiable, wallet-bound result
```

## What QMA does

QMA turns a live signal into a paid historical comparison:

1. Recommendations expose candidate signals from approved providers.
2. The decision service evaluates score, provider, tier, price, budget, and
   existing entitlements.
3. QMA creates an invoice bound to the provider, query snapshot, tier, and
   resource type.
4. Circle Gateway/x402 settles independent creator and platform payment legs.
5. The backend verifies every required leg before issuing an entitlement and a
   short-lived access token.
6. The exact preview or full report is returned to the buyer.

No report is unlocked merely because an invoice was created or one split leg
was paid.

## The agent actually has a budget

The CLI agent is bounded by policy rather than being allowed to spend freely:

- session budget and maximum price per report;
- provider and tier allowlists;
- minimum score and ownership checks;
- Preview-to-Full upgrade behavior;
- symbol cooldowns;
- maximum purchases and duration stop conditions;
- dry-run mode with no payment;
- explicit live executor selection.

The backend returns the canonical candidate and policy result. The LLM, when
enabled, can propose a minimal plan, but it cannot authoritatively choose the
recipient, invoice secret, split leg, settlement id, access token, or report
content.

## Example decision and payment trace

An actual Arc Testnet CLI run follows this shape:

```text
Candidate APDSTOCK: score=91.7 tier=full price=0.006 USDC

Agent pick: APDSTOCK / oi_memory / full
Invoice: inv_...
Split legs:
  creator  -> provider revenue wallet
  platform -> QMA treasury wallet

Circle Agent Wallet pays the x402 legs
QMA verifies both settlement receipts
Payment settled; report unlocked
```

Use `--verbose` to print the evaluated candidates, policy decisions, canonical
query, settlement result, and unlock outcome. Use `--json` for machine-readable
session output.

## Human and autonomous paths

### Browser path

```text
React UI
  -> backend decision endpoint
  -> invoice
  -> connected browser wallet signs x402 legs
  -> payment verification
  -> report unlock
```

This is a user-controlled wallet flow. The browser does not receive Circle CLI
credentials or Agent Wallet OTP sessions.

### CLI path

```text
Prompt and bounded policy
  -> POST /api/v1/agent/decision
  -> canonical candidate
  -> invoice
  -> Circle Agent Wallet / Gateway x402
  -> split settlement verification
  -> entitlement and report
```

The CLI supports a local private-key executor for test workflows and an opt-in
Circle Agent Wallet executor. The Circle Agent Wallet address is the x402
authorization identity; Gateway settlement can expose a separate backing payer
identity. QMA binds both identities when available.

## Provider economy

Every current direct-split invoice has two payment legs:

```text
buyer
  ├─ creator leg  -> provider revenue wallet
  └─ platform leg -> QMA treasury wallet
```

Provider owners can inspect earnings and withdraw according to the configured
settlement mode. The marketplace exposes provider metadata, applications,
review state, payment history, and settlement references.

## Traction and proof

The public metrics endpoint separates current paid activity from legacy data
and reports buyer type, provider, tier, payer, and revenue breakdowns:

```text
/api/v1/metrics?payment_page_size=1&payer_page_size=1
```

Important fields include:

- `paid_count` and `current_paid_count`;
- `buyer_type_counts.agent` and `buyer_type_counts.human`;
- `revenue_usdc` and `current_revenue_usdc`;
- `unique_payers`;
- `revenue_by_provider`;
- `tier_counts` for Preview and Full;
- recent settlement events and payer breakdowns.

Metrics must be read with their deployment timestamp and classified as real
settlements, simulated activity, or engine-generated agent activity. The
tracking policy is documented in [docs/TRACTION.md](docs/TRACTION.md).

## Payment rails

QMA uses Circle and Arc primitives for small, machine-readable payments:

- x402 pay-per-request authorization;
- Circle Gateway balance for USDC nanopayments;
- independent creator/platform split legs;
- provider-bound invoice signatures;
- settlement receipts and idempotency checks;
- wallet-bound entitlements;
- short-lived access tokens for paid reports.

The complete lifecycle, state transitions, retry rules, and failure behavior
are documented in [PAYMENT_FLOW.md](PAYMENT_FLOW.md).

## Architecture

```text
React UI                          External CLI / agent
    │                                      │
    └──────────────┬───────────────────────┘
                   ▼
        POST /api/v1/agent/decision
                   │
                   ▼
      FastAPI decision + provider registry
                   │
                   ├─ recommendations
                   ├─ entitlements and ownership
                   ├─ price and tier policy
                   └─ canonical query resolution
                   │
                   ▼
          Provider-bound invoice API
                   │
                   ▼
       Arc Gateway / Circle x402 split legs
                   │
                   ▼
       Settlement verification + state machine
                   │
                   ▼
       Entitlement + access token + report API
```

## Run locally

Install dependencies and build the typed agent package:

```powershell
npm install
npm run agent:build
```

Start the backend and frontend using the commands documented in
[backend/README.md](backend/README.md) and
[frontend/README.md](frontend/README.md). Then run a safe agent observation:

```powershell
npm run agent -- --api http://127.0.0.1:8000 --dry-run --run-once --budget 0.05 --max-price 0.005
```

For a bounded repeated session:

```powershell
npm run agent -- --api http://127.0.0.1:8000 --dry-run --duration 10m --poll 60 --budget 1 --max-price 0.005
```

For live Arc Testnet execution, explicitly select a funded executor and keep
auto-deposit disabled unless the extra funding transaction is intended:

```powershell
npm run agent -- --api http://127.0.0.1:8000 --live --run-once --budget 0.01 --max-price 0.005 --executor circle-agent-wallet --wallet 0xYOUR_AGENT_WALLET --no-auto-deposit
```

See [examples/README.md](examples/README.md) for the complete CLI reference.

## Current limitations

QMA is an active rebuild, not a claim of production completeness:

- the browser agent still uses the connected user wallet, not Circle Agent
  Wallet login inside Vite;
- LLM planning is optional and the bounded session polls deterministically;
- provider routing exposes comparison data, but quality/latency reputation is
  not yet a full independent reputation system;
- the CLI session is bounded and process-based, not a durable hosted worker;
- deployed payment and metrics claims refer to Arc Testnet unless explicitly
  stated otherwise;
- the legacy frontend and rebuild frontend remain separate deployment realities
  until cutover is confirmed.

## Documentation map

- [docs/AUTONOMOUS_AGENT.md](docs/AUTONOMOUS_AGENT.md) — canonical autonomous
  session flow, policy, accounting, and stop conditions.
- [docs/AGENT_API.md](docs/AGENT_API.md) — HTTP decision contract.
- [examples/README.md](examples/README.md) — CLI commands and troubleshooting.
- [agents/README.md](agents/README.md) — typed policy/session package.
- [backend/README.md](backend/README.md) — FastAPI implementation boundary.
- [frontend/README.md](frontend/README.md) — React routes, services, and wallet
  flow.
- [docs/DEPLOYMENT_SETUP.md](docs/DEPLOYMENT_SETUP.md) — rebuild deployment.
- [docs/TRACTION.md](docs/TRACTION.md) — metrics integrity and proof objects.
- [docs/README.md](docs/README.md) — complete documentation ownership map.

## Security boundary

The backend is authoritative for payment and access. Frontend cache, prompt
text, and LLM output cannot grant a report. Never commit or expose private
keys, service-role keys, Circle OTP/session data, invoice secrets, or access
tokens.

## Verification

```powershell
python -m pytest -q tests
cd frontend; npm run typecheck; npm run build
cd ..; npm run agent:build
node --check examples/agent_session.mjs
```

These commands verify source/build contracts. They do not prove a browser run,
live Circle settlement, or a successful production deployment.
