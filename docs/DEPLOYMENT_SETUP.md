# QMA Deployment Setup

This guide is for a clean Lepton submission deploy using:

- Vercel for the static frontend
- Render for the FastAPI backend
- Render for the Arc Gateway sidecar
- Supabase for durable payment/report history

Do not put server secrets in Vercel. Vercel only serves static HTML/CSS/JS.

## Target Architecture

```text
Vercel frontend
  -> Render qma-api FastAPI backend
      -> Supabase
      -> Circle Gateway API
      -> Arcscan
      -> Render qma-arc-gateway sidecar
```

Recommended service names:

```text
qma-api
qma-arc-gateway
```

The current HTML fallback points to:

```text
https://qma-api.onrender.com
```

If you use another Render backend name, update the fallback in these files:

```text
index.html
app.html
user.html
marketplace.html
docs.html
```

Search for:

```text
window.QMA_API_BASE_URL
```

Vercel environment variables do not automatically change this static HTML value.

## Render: FastAPI Backend

Create a Render Web Service:

```text
Name: qma-api
Runtime: Python
Branch: main
Build Command: pip install -r requirements.txt
Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT
```

Required env vars are intentionally small. Start from `.env.example`; add values from
`.env.advanced.example` only when you need to override defaults.

```env
QMA_ARC_SELLER_ADDRESS=0xYourSellerTreasuryWallet
QMA_ADMIN_WALLET=0xYourSellerTreasuryWallet
QMA_ADMIN_TOKEN=replace-with-admin-review-token
QMA_ACCESS_TOKEN_SECRET=replace-with-long-random-secret

QMA_FUNDING_MEMORY_OWNER_WALLET=0xFundingProviderOwnerWallet
QMA_OI_MEMORY_OWNER_WALLET=0xOiProviderOwnerWallet

QMA_ARC_GATEWAY_URL=https://qma-arc-gateway.onrender.com

SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_SCHEMA=public
```

Optional dataset env vars if using private/full data:

```env
QMA_HISTORICAL_DB_PATH=/private_data/funding_historical_analysis.csv
QMA_BACKTEST_OUTCOME_PATH=/private_data/trading_analysis.csv
```

If omitted, the backend uses bundled sample data.

Environment files:

- `.env.example`: minimal role, secret, storage, and dataset keys.
- `.env.local.example`: local developer defaults, demo pricing, and CLI agent settings.
- `.env.advanced.example`: public Arc/Circle overrides, rate limits, market-data tuning, and other optional knobs.

Do not add public Arc Testnet constants to Render unless you need to override the source defaults.

Gasless withdraw relay is optional. To enable it, set these only after funding a dedicated hot
relayer wallet:

```env
# qma-api
QMA_WITHDRAW_MODE=platform_relayed
QMA_WITHDRAW_RELAYER_ADDRESS=0xHotRelayerWallet
QMA_MIN_PROVIDER_WITHDRAW_USDC=5
QMA_PROVIDER_WITHDRAW_DAILY_LIMIT=1

# qma-arc-gateway
QMA_WITHDRAW_RELAYER_PRIVATE_KEY=0xserver-only-hot-wallet-private-key
QMA_WITHDRAW_RELAYER_ADDRESS=0xHotRelayerWallet
ARC_TESTNET_RPC=https://rpc.testnet.arc.network
```

Keep the relayer wallet separate from the admin wallet and platform settlement treasury.

## Render: Arc Gateway Sidecar

Create a second Render Web Service:

```text
Name: qma-arc-gateway
Runtime: Node
Root Directory: arc_gateway
Branch: main
Build Command: npm install
Start Command: npm start
```

Required env vars:

```env
QMA_ARC_SELLER_ADDRESS=0xYourSellerTreasuryWallet
QMA_CIRCLE_GATEWAY_API=https://gateway-api-testnet.circle.com
QMA_ARC_EXPLORER=https://testnet.arcscan.app
ARC_EXPLORER=https://testnet.arcscan.app
ARC_TESTNET_RPC=https://rpc.testnet.arc.network

QMA_PRICE_PREVIEW_USDC=0.001
QMA_PRICE_FULL_USDC=0.005
QMA_ARC_DEFAULT_DEPOSIT_USDC=1.00
QMA_ARC_APPROVE_USDC=10.00
```

The FastAPI backend must point to this service:

```env
QMA_ARC_GATEWAY_URL=https://qma-arc-gateway.onrender.com
```

## Supabase

Create tables from:

```text
docs/SUPABASE.md
```

Then verify:

```text
/api/v1/health
```

Expected minimal response:

```json
{
  "status": "ok",
  "engine": "ready",
  "storage_backend": "supabase"
}
```

Frontend bootstrap config is:

```text
/api/v1/config
```

It should include:

```json
{
  "arc_gateway": "https://qma-arc-gateway.onrender.com",
  "seller_wallet": "0xYourSellerTreasuryWallet",
  "pricing": {
    "preview_base_usdc": 0.001,
    "full_base_usdc": 0.005
  }
}
```

## Vercel Frontend

Vercel deploys static files only:

```text
index.html
app.html
user.html
marketplace.html
docs.html
public/**
```

The current `vercel.json` already routes:

```text
/           -> index.html
/app        -> app.html
/user       -> user.html
/marketplace -> marketplace.html
/docs       -> docs.html
```

Vercel required env vars:

```text
None, if the Render backend is named qma-api.
```

If the backend is not `https://qma-api.onrender.com`, update the static fallback in the HTML files listed above.

Do not add these to Vercel:

```text
SUPABASE_SERVICE_ROLE_KEY
QMA_ACCESS_TOKEN_SECRET
QMA_ADMIN_TOKEN
QMA_ADMIN_WALLET
AGENT_PRIVATE_KEY
OpenAI keys
Circle secrets
```

## Post-Deploy Smoke Test

Backend:

```text
https://qma-api.onrender.com/api/v1/health
https://qma-api.onrender.com/api/v1/config
https://qma-api.onrender.com/api/v1/platform/summary
https://qma-api.onrender.com/api/v1/live-anomalies
```

Arc Gateway:

```text
https://qma-arc-gateway.onrender.com/health
```

Frontend:

```text
https://your-vercel-domain.vercel.app/
https://your-vercel-domain.vercel.app/app
https://your-vercel-domain.vercel.app/user
```

In the browser Network tab, confirm frontend API calls go to:

```text
https://qma-api.onrender.com
```

Then test:

1. Live Signals loads.
2. Browser Judge Mode opens.
3. Fund Arc Wallet opens and reads wallet state.
4. Preview payment creates invoice.
5. Gateway deposit prompt appears if needed.
6. x402 settlement verifies.
7. Paid report unlocks.
8. Wallet Profile and `/user` show the paid receipt.

## Main vs Dev

For final submission:

```text
main -> qma-api -> final Supabase DB
main -> qma-arc-gateway
main -> Vercel production
```

Avoid mixing preview/frontend with an old backend. The frontend is thin; the backend decides which Supabase project is used.
