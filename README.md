# QMA - Quant Memory Agent

QMA is a pay-per-call market intelligence agent on Arc.

Humans and AI agents can buy historical crypto market-memory reports one query at a time using Arc Testnet USDC through Circle Gateway/x402.

## What This Repo Contains

- FastAPI backend with OpenAPI docs at `/docs`
- Terminal-style QMA dashboard at `/app`
- Short hackathon landing page at `/`
- Paid Intelligence API Kit
- Provider interface and `funding_memory` example provider
- Arc/Circle x402 gateway sidecar
- Public sample datasets for local testing

## Product Flow

1. QMA scans live MEXC funding anomalies.
2. Agent Picks ranks which reports are worth buying.
3. User or external agent creates a provider-bound invoice.
4. Buyer pays `0.001 USDC` for Preview or `0.005 USDC` for Full.
5. QMA verifies Circle Gateway settlement and records a wallet entitlement.
6. The exact query-bound report unlocks.

## Data Policy

The public repo includes sample CSVs:

```text
qma/data/sample_funding_historical_analysis.csv
qma/data/sample_trading_analysis.csv
```

The deployed demo can use a larger private provider dataset through environment variables:

```env
QMA_HISTORICAL_DB_PATH=/private_data/funding_historical_analysis.csv
QMA_BACKTEST_OUTCOME_PATH=/private_data/trading_analysis.csv
```

The data source is MEXC Futures public API. Public sample data plus crawler scripts are included for transparency; the full dataset is treated as a provider asset.

## Recommended Hackathon Deployment

Use the landing/dashboard on Vercel if you want a clean public URL, and run the backend/API plus private data on Railway, Render, or a VPS.

Vercel can deploy FastAPI, but QMA uses pandas, scipy, sklearn, live scanning, and optionally a private dataset. Keeping the backend separate is safer for bundle size and long-running reliability.

Suggested setup:

```text
Vercel:
  - landing page
  - frontend shell

Railway / Render / VPS:
  - FastAPI backend
  - QMA engine
  - Arc Gateway sidecar
  - private full dataset
```

This repo includes:

```text
render.yaml   Render blueprint for qma-api + qma-arc-gateway
vercel.json   Static landing/dashboard routes: / and /app
.vercelignore Keeps Vercel from deploying the Python/Node backend files
```

After Render creates both services, set these environment variables:

```env
# qma-api service
QMA_ARC_SELLER_ADDRESS=<seller-wallet>
QMA_FUNDING_MEMORY_OWNER_WALLET=<seller-wallet>
QMA_ARC_GATEWAY_URL=https://qma-arc-gateway.onrender.com

# qma-arc-gateway service
QMA_ARC_SELLER_ADDRESS=<seller-wallet>
```

After Vercel deploys the static frontend, set the API base in `landing.html` and `index.html` or inject it before build:

```html
window.QMA_API_BASE_URL = "https://qma-api.onrender.com";
```

If the static UI is deployed separately from the API, set:

```html
<script>
  window.QMA_API_BASE_URL = "https://your-qma-api.example.com";
</script>
```

The same variable is supported by both `landing.html` and `index.html`.

In Vercel project settings, use:

```text
Framework Preset: Other
Build Command: empty
Output Directory: empty
Install Command: empty
```

If Vercel shows "This Serverless Function has crashed", it is trying to deploy the backend. The static frontend deployment should only include `landing.html`, `index.html`, `public/`, `vercel.json`, and `.vercelignore`.

Vercel notes: their docs support FastAPI/Python deployments, but Python functions have a 500 MB uncompressed bundle size limit and Python files are not tree-shaken automatically. For QMA, that makes split deployment the practical default.

## Local Run

```powershell
python qma\main.py
```

```powershell
cd qma\arc_gateway
npm.cmd install
npm.cmd start
```

Open:

```text
http://127.0.0.1:8000
```

Useful endpoints:

```text
GET  /api/v1/providers
GET  /api/v1/providers/funding_memory
POST /api/v1/payment/invoice
POST /api/v1/payment/verify
POST /api/v1/providers/funding_memory/preview
POST /api/v1/providers/funding_memory/full-report
```
