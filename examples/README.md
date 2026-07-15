# QMA Agent Buyer Example

This folder shows how an external autonomous agent can buy QMA intelligence directly from the API.

The example agent:

```text
1. Reads /api/v1/agent/recommendations
2. Optionally loads wallet entitlements from /api/v1/entitlements/wallet/{address}
3. Chooses an affordable signal under budget and max-price policy
4. Upgrades Preview -> Full when Preview was already paid, and skips symbols with Full already paid
5. Creates a provider-bound invoice
6. Ensures Circle Gateway balance is available
7. Pays the x402 requirement with Arc Testnet USDC
8. Verifies settlement with QMA
9. Fetches the paid JSON report
```

The web dashboard is not required for this flow.

## Bounded autonomous session

For repeated observations under one explicit spending policy, use the session
command. It performs one bounded policy parse, polls the backend decision
source, and reuses the existing payment executor only in live mode:

```powershell
npm run agent:build
npm run agent -- --dry-run --run-once --budget 0.05 --max-price 0.005
npm run agent -- --live --budget 0.05 --max-purchases 5 --duration 30m --poll 60 --no-auto-deposit
```

Use `--until-stopped` only when an unlimited runtime is intentional. The
session writes a final report; `--json`, `--report-file`, and `--event-log` are
available for automation. Dry-run mode simulates purchases and creates no
invoice.

## LLM planner mode

The regular command uses the deterministic policy directly. The `--llm` mode
sends the prompt to the shared backend agent service before the same payment
executor:

```text
prompt
  -> recommendations + entitlements
  -> backend OpenAI structured decision JSON (or regex fallback)
  -> canonical candidate/budget/entitlement validation
  -> existing split-payment executor
```

The LLM returns only a minimal plan (`action`, `candidate_id`, requested tier,
budget, max price, reason, and rejected IDs). QMA resolves the authoritative
provider, symbol, price, query, and entitlement state before an invoice can be
created. The LLM never supplies an invoice secret, settlement ID, access token,
recipient, or payment payload.

Build the new package first:

```powershell
& .\frontend\node_modules\.bin\tsc.cmd -p agents\tsconfig.json
```

Dry-run (no invoice, no payment):

```powershell
$env:QMA_API_URL="http://127.0.0.1:8000"
node examples/agent_buyer.mjs --llm --dry-run --prompt "Find the best opportunity under 0.002 USDC"
```

`examples/agent_session.mjs` and `examples/agent_buyer.mjs` load
`QMA_API_URL` from the repository-root `.env`. The `agents/.env` file is for
the TypeScript package and is not used to override the CLI's root setting. Use
`--api http://127.0.0.1:8000` for local testing, or set the root
`QMA_API_URL` to the deployed backend that contains
`POST /api/v1/agent/decision`.

By default, a session with no loop bound performs one safe poll and stops.
For repeated autonomous polling, provide an explicit bound, for example:

```powershell
node examples/agent_session.mjs --api http://127.0.0.1:8000 --dry-run --duration 10m --poll 60
```

Use `--until-stopped` for a session that continues until Ctrl+C, or
`--max-purchases 3` to stop after at most three purchases.

Session sequence:

```mermaid
sequenceDiagram
    autonumber
    participant CLI as agent_session.mjs
    participant API as QMA /agent/decision
    participant Buyer as agent_buyer.mjs
    participant Gateway as Arc Gateway/x402

    CLI->>API: Poll with policy, budget, provider/tier allowlist
    API-->>CLI: Canonical candidate or rejection set
    alt dry-run
        CLI-->>CLI: Simulate purchase; no invoice or funds
    else live
        CLI->>Buyer: Execute selected candidate
        Buyer->>API: Create provider-bound invoice
        Buyer->>Gateway: Sign and settle required split legs
        Gateway-->>Buyer: Receipts
        Buyer->>API: Verify and fetch paid report
        Buyer-->>CLI: Purchase result
    end
    CLI-->>CLI: Update spend, cooldown, failures, and stop conditions
```

The default output is compact. Use `--verbose` for policy checks, the
evaluated candidate table, and the canonical query; use `--json` for the
machine-readable backend response, or `--quiet` for a one-line result.

Live Arc Testnet payment using an existing Gateway balance:

```powershell
$env:AGENT_PRIVATE_KEY="0x..."
node examples/agent_buyer.mjs --llm --live --no-auto-deposit --prompt "Buy the best affordable preview report"
```

This bridge still signs with the existing test-wallet path. Circle Agent Wallet
CLI integration is a separate signer adapter and is not enabled by `--llm`.
For an isolated local TypeScript planner test, add `--local-llm`; that path
requires `OPENAI_API_KEY` and does not share the backend decision execution.

## Install

From the `qma/` directory:

```powershell
npm install
```

## Dry Run

Dry run is safe for demos. It does not sign or spend USDC. The regular
non-LLM dry-run path may still create a quote invoice for compatibility; the
`--llm --dry-run` planner path does not create an invoice.

```powershell
npm run agent:dry
```

If you want dry-run policy to check paid history without signing, pass the wallet address to inspect:

```powershell
node examples/agent_buyer.mjs --dry-run --wallet 0xYOUR_AGENT_WALLET
```

Optional filters:

```powershell
node examples/agent_buyer.mjs --dry-run --tier preview
node examples/agent_buyer.mjs --dry-run --tier full
node examples/agent_buyer.mjs --dry-run --symbol HYPE
node examples/agent_buyer.mjs --dry-run --api http://127.0.0.1:8000
```

## Selection Policy

There are two ways to run the buyer:

```text
Auto policy mode:
  node examples/agent_buyer.mjs --dry-run
  node examples/agent_buyer.mjs --live

Forced tier mode:
  npm run agent:preview
  npm run agent:full
  node examples/agent_buyer.mjs --live --tier preview
  node examples/agent_buyer.mjs --live --tier full
```

Auto policy mode is the autonomous agent behavior. It checks wallet entitlements when an agent wallet is known:

- If a symbol has no paid report yet, the agent can buy the suggested Preview or Full report.
- If a symbol already has Preview but not Full, the agent upgrades to Full instead of buying Preview again.
- If a symbol already has Full, the agent skips it and evaluates the next opportunity.
- Among remaining choices, it prefers Preview -> Full upgrades first, then ranks by `score / price`.

Forced tier mode is a command primitive. It respects the tier you requested:

- `agent:preview` buys Preview opportunities only.
- `agent:full` buys Full opportunities only.
- If the requested tier was already purchased for a symbol, the buyer skips that symbol and moves to the next affordable opportunity.

## Live Payment

Live mode uses a private key from a test wallet and signs real Arc Testnet transactions.

```powershell
$env:QMA_API_URL="https://qma-api.onrender.com"
$env:AGENT_PRIVATE_KEY="0xYOUR_TEST_WALLET_PRIVATE_KEY"
$env:AGENT_BUDGET_USDC="0.01"
$env:AGENT_MAX_PRICE_USDC="0.005"
$env:AGENT_GATEWAY_DEPOSIT_USDC="1"
npm run agent:preview
```

Full report:

```powershell
npm run agent:full
```

Run the fully automatic policy without forcing a tier:

```powershell
node examples/agent_buyer.mjs --live
```

## Testnet USDC

New agent wallets can request Arc Testnet USDC from Circle:

```text
https://faucet.circle.com/
```

The faucet funds the wallet's normal on-chain USDC balance.

QMA/x402 spends from Circle Gateway balance, so live mode will auto-approve and auto-deposit USDC into Circle Gateway if the Gateway balance is too low.

Disable auto-deposit:

```powershell
node examples/agent_buyer.mjs --live --tier preview --no-auto-deposit
```

## Environment

Supported environment variables:

```env
# Use qma-api-rebuild for the current rebuild branch; qma-api is the legacy/main service.
QMA_API_URL=https://qma-api-rebuild.onrender.com
AGENT_PRIVATE_KEY=0x...
AGENT_WALLET_ADDRESS=0x... # optional dry-run policy wallet when no private key is loaded
AGENT_BUDGET_USDC=0.01
AGENT_MAX_PRICE_USDC=0.005
AGENT_GATEWAY_DEPOSIT_USDC=1
AGENT_GATEWAY_APPROVE_USDC=10
ARC_TESTNET_RPC=https://rpc.testnet.arc.network
```

Never commit `AGENT_PRIVATE_KEY`.

## Security Model

The agent does not receive a report just because it created an invoice.

QMA backend still validates:

- invoice id
- invoice secret
- query fingerprint
- provider id
- tier
- Circle/x402 settlement id
- payer wallet
- payment amount
- access token expiry

Only after verification does QMA issue an access token for the paid report endpoint.

## Troubleshooting

### `insufficient_balance`

The wallet has on-chain USDC, but its Circle Gateway balance is too low.

Run live mode without `--no-auto-deposit`, or use the web UI once to approve/deposit into Gateway.

### `Wallet has X USDC, but auto-deposit needs Y USDC`

Request more testnet USDC from the Circle Faucet or lower:

```env
AGENT_GATEWAY_DEPOSIT_USDC=0.01
```

### `QMA verification did not return an access token`

The settlement was accepted by the gateway but QMA did not accept the invoice verification. Check:

- invoice secret belongs to the same invoice,
- payer wallet matches the private key,
- report tier matches the invoice tier,
- query payload was not changed.

### Report tx is pending

Circle can accept the x402 payment before the final Arcscan batch transaction appears. QMA can still unlock the report once Circle settlement is accepted, and Arcscan tx hydration may appear later.
