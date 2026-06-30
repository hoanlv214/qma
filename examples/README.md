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

## Install

From the `qma/` directory:

```powershell
npm install
```

## Dry Run

Dry run is safe for demos. It creates an invoice but does not sign or spend USDC.

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
QMA_API_URL=https://qma-api.onrender.com
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
