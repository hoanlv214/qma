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

Required env vars:

```env
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_SCHEMA=public

QMA_ARC_SELLER_ADDRESS=0xYourSellerTreasuryWallet
QMA_FUNDING_MEMORY_OWNER_WALLET=0xYourSellerTreasuryWallet
QMA_OI_MEMORY_OWNER_WALLET=0xYourSellerTreasuryWallet

QMA_ARC_GATEWAY_URL=https://qma-arc-gateway.onrender.com
QMA_CIRCLE_GATEWAY_API=https://gateway-api-testnet.circle.com
QMA_ARC_EXPLORER=https://testnet.arcscan.app
QMA_ARC_GATEWAY_WALLET=0x0077777d7EBA4688BDeF3E311b846F25870A19B9

QMA_PRICE_PREVIEW_USDC=0.001
QMA_PRICE_FULL_USDC=0.005
QMA_PAYMENT_AMOUNT_USDC=0.005
QMA_PAYMENT_RESOURCE_TYPE=qma_signal_report
QMA_PAYMENT_NETWORK=eip155:5042002
QMA_PAYMENT_NETWORK_NAME=Arc Testnet

QMA_ACCESS_TOKEN_SECRET=replace-with-long-random-secret
QMA_ADMIN_TOKEN=replace-with-admin-review-token

QMA_ARC_DEFAULT_DEPOSIT_USDC=1.00
QMA_ARC_DEFAULT_APPROVE_USDC=10.00
QMA_REQUIRE_COMPLETED_SETTLEMENT=false

QMA_RATE_LIMIT_ENABLED=true
QMA_RATE_LIMIT_WINDOW_SECONDS=60
QMA_RATE_LIMIT_PAYMENT_VERIFY_PER_MIN=8
QMA_RATE_LIMIT_INVOICE_PER_MIN=20
QMA_RATE_LIMIT_REPORT_PER_MIN=30
QMA_RATE_LIMIT_PUBLIC_MARKET_PER_MIN=120
QMA_RATE_LIMIT_CREATOR_APPLY_PER_MIN=6
QMA_RATE_LIMIT_API_DEFAULT_PER_MIN=240
QMA_MEXC_FETCH_CONTRACT_DETAILS=false
```

Optional dataset env vars if using private/full data:

```env
QMA_HISTORICAL_DB_PATH=/private_data/funding_historical_analysis.csv
QMA_BACKTEST_OUTCOME_PATH=/private_data/trading_analysis.csv
```

If omitted, the backend uses bundled sample data.

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
