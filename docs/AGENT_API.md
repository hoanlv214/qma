# QMA Agent API Demo

QMA can be used by a human through the web UI, or by an autonomous buyer agent through the API.

The agent demo shows this loop:

```text
Read QMA Agent Picks
-> choose the best affordable report under budget
-> create an invoice
-> pay the x402/Circle Gateway requirement
-> verify settlement
-> receive a paid JSON report
```

## Run Dry Mode

Dry mode is safe for a video demo. It creates an invoice but does not sign or spend USDC.

```powershell
cd qma
npm install
npm run agent:dry
```

Equivalent command:

```powershell
node examples/agent_buyer.mjs --dry-run
```

Useful options:

```powershell
node examples/agent_buyer.mjs --dry-run --tier preview
node examples/agent_buyer.mjs --dry-run --tier full
node examples/agent_buyer.mjs --dry-run --symbol HYPE
node examples/agent_buyer.mjs --dry-run --api http://127.0.0.1:8000
```

## Run Live Payment Mode

Live mode signs real Arc Testnet transactions from an agent wallet.

Requirements:

- The wallet must be funded on Arc Testnet.
- New test wallets can request USDC from the Circle Faucet: https://faucet.circle.com/
- If Circle Gateway balance is too low, the agent can auto-approve and auto-deposit USDC before paying.
- Never commit `AGENT_PRIVATE_KEY`.

```powershell
$env:QMA_API_URL="https://qma-api.onrender.com"
$env:AGENT_PRIVATE_KEY="0xYOUR_TEST_WALLET_PRIVATE_KEY"
$env:AGENT_BUDGET_USDC="0.01"
$env:AGENT_MAX_PRICE_USDC="0.005"
$env:AGENT_GATEWAY_DEPOSIT_USDC="1"
npm run agent:preview
```

By default, live mode auto-deposits `AGENT_GATEWAY_DEPOSIT_USDC` into Circle Gateway if needed. Disable that behavior with:

```powershell
node examples/agent_buyer.mjs --live --tier preview --no-auto-deposit
```

For local backend:

```powershell
$env:QMA_API_URL="http://127.0.0.1:8000"
npm run agent:preview
```

## What This Proves

The web app is not the only buyer.

Any external agent can:

1. Discover paid opportunities from `/api/v1/agent/recommendations`.
2. Create a query-bound invoice at `/api/v1/payment/invoice`.
3. Pay through the x402 `PAYMENT-REQUIRED` challenge.
4. Verify settlement at `/api/v1/payment/verify`.
5. Fetch the paid report JSON with `X-QMA-Access-Token`.

This is the Lepton story:

```text
QMA sells market intelligence per call.
Humans can buy it in the dashboard.
Agents can buy it directly over API.
Providers can later plug in their own paid datasets.
```

## Demo Script Under 3 Minutes

Recommended recording order:

1. Open `https://qma-three.vercel.app/`.
2. Say: "QMA is a pay-per-call market intelligence agent on Arc."
3. Click `Launch App`.
4. Point at `Agent Picks`: QMA ranks live funding anomalies and suggests Preview or Full.
5. Buy `Preview 0.001 USDC`, show Circle Gateway/x402 flow.
6. Buy or show `Full 0.005 USDC`, then point at the analog table, percentiles, Arcscan tx, and diagnostics.
7. Open wallet profile and show purchases, spend, and entitlement history.
8. Switch terminal and run:

```powershell
npm run agent:dry
```

Close with:

```text
The same paid intelligence API works for humans and autonomous agents.
The reusable part is the Paid Intelligence API Kit.
```

If time is tight, keep the CLI part to 20 seconds. Dry mode is enough to show agent decision-making; live web payment already proves real Circle/Arc settlement.
