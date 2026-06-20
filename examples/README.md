# QMA Agent Buyer Example

This folder shows how an external autonomous agent can buy QMA intelligence directly from the API.

The example agent:

```text
1. Reads /api/v1/agent/recommendations
2. Chooses the highest-scoring affordable signal under budget
3. Creates a provider-bound invoice
4. Ensures Circle Gateway balance is available
5. Pays the x402 requirement with Arc Testnet USDC
6. Verifies settlement with QMA
7. Fetches the paid JSON report
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

Optional filters:

```powershell
node examples/agent_buyer.mjs --dry-run --tier preview
node examples/agent_buyer.mjs --dry-run --tier full
node examples/agent_buyer.mjs --dry-run --symbol HYPE
node examples/agent_buyer.mjs --dry-run --api http://127.0.0.1:8000
```

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
