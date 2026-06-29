# QMA - Quant Memory Agent

QMA is a pay-per-call market intelligence agent on Arc.

Humans and AI agents can buy historical crypto market-memory reports one query at a time using Arc Testnet USDC through Circle Gateway/x402.

## Judge TL;DR

- Live app: https://qma-three.vercel.app
- API: https://qma-api.onrender.com
- Arc Gateway: https://qma-arc-gateway.onrender.com
- Marketplace: `/marketplace`
- Core flow: Agent Picks -> Preview or Full invoice -> Circle Gateway/x402 payment -> wallet-bound entitlement -> paid JSON report.
- Agent demo: see [docs/AGENT_API.md](docs/AGENT_API.md) and `examples/agent_buyer.mjs`.
- Security model: frontend cache is convenience only; backend verifies invoice secret, query hash, tier, provider, payer wallet, x402 settlement, access token expiry, rate limits, and wallet-bound entitlements.

Try:

```text
1. Open the live app and click Launch App.
2. Connect a buyer wallet on Arc Testnet.
3. If the wallet needs testnet USDC, use the Circle Faucet: https://faucet.circle.com/
4. Buy Preview for 0.001 USDC or Full for 0.005 USDC.
5. Open Wallet Profile to see report history and spend.
6. Run npm run agent:dry to see an external buyer agent choose and invoice a report.
```

## What This Repo Contains

- FastAPI backend with OpenAPI docs at `/docs`
- Terminal-style QMA dashboard at `/app`
- Provider marketplace and creator application page at `/marketplace`
- Short hackathon landing page at `/`
- Paid Intelligence API Kit
- Provider interface with `funding_memory` and experimental `oi_memory` providers
- Arc/Circle x402 gateway sidecar
- Public sample datasets for local testing

## Repository Layout

```text
qma/
  main.py                 FastAPI backend and HTML/API routes
  qma_engine.py           historical analog engine
  providers.py            paid intelligence provider registry
  storage.py              JSON/Supabase persistence layer
  index.html              landing page served at /
  app.html                QMA dashboard served at /app
  user.html               wallet profile/history served at /user
  marketplace.html        provider marketplace served at /marketplace
  public/                 shared JS, CSS, and image assets
  docs/                   Arc, Supabase, API security, Cloudflare, demo notes
  examples/               autonomous buyer agent example
  scripts/                migration/util scripts
  data/                   public sample datasets
  paid_intelligence_kit/  reusable paid API primitive
```

## Docs

- [docs/AGENT_API.md](docs/AGENT_API.md): external autonomous buyer example.
- [examples/README.md](examples/README.md): CLI buyer demo commands.
- [docs/ARC_PAYMENT.md](docs/ARC_PAYMENT.md): Circle Gateway/x402 payment lifecycle.
- [docs/SUPABASE.md](docs/SUPABASE.md): durable payment/entitlement/creator storage.
- [docs/API_SECURITY.md](docs/API_SECURITY.md): backend authorization, rate limits, and marketplace endpoints.
- [docs/CLOUDFLARE.md](docs/CLOUDFLARE.md): Cloudflare setup for edge protection.

## Product Flow

1. QMA scans live MEXC funding anomalies.
2. Agent Picks ranks which reports are worth buying.
3. User or external agent selects a provider and creates a provider-bound invoice.
4. Buyer pays `0.001 USDC` for Preview or `0.005 USDC` for Full.
5. QMA verifies Circle Gateway settlement and records a wallet entitlement.
6. The exact query-bound report unlocks.

## Agent Buyer Flow

```text
signal -> invoice -> x402 pay -> JSON report
```

QMA supports human buyers through the web app and autonomous buyers through the paid API path. An external agent can evaluate a suggested signal, create an invoice, pay within a budget, and receive a structured report response without using the dashboard.

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
vercel.json   Static landing/dashboard routes: /, /app, /user, /marketplace
.vercelignore Keeps Vercel from deploying the Python/Node backend files
*.html        Vercel and FastAPI served HTML entrypoints
public/       Shared CSS, JS, and assets
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

After Vercel deploys the static frontend, set the API base in `index.html`, `app.html`, `user.html`, and `marketplace.html` or inject it before build:

```html
window.QMA_API_BASE_URL = "https://qma-api.onrender.com";
```

If the static UI is deployed separately from the API, set:

```html
<script>
  window.QMA_API_BASE_URL = "https://your-qma-api.example.com";
</script>
```

The same variable is supported by all static pages.

In Vercel project settings, use:

```text
Framework Preset: Other
Root Directory: repo root
Build Command: empty
Output Directory: empty
Install Command: empty
```

If Vercel shows "This Serverless Function has crashed", it is trying to deploy the backend. The static frontend deployment should include the root HTML entrypoints, `public/`, `vercel.json`, and `.vercelignore`.

Vercel notes: their docs support FastAPI/Python deployments, but Python functions have a 500 MB uncompressed bundle size limit and Python files are not tree-shaken automatically. For QMA, that makes split deployment the practical default.

## Local Run

Use local first, then push to GitHub only after the wallet/payment flow is OK. The HTML files auto-detect the environment:

```text
http://127.0.0.1:8000  -> same-origin local FastAPI API
https://qma-three.vercel.app -> https://qma-api.onrender.com
```

Local terminal 1:

```powershell
python qma\main.py
```

Local terminal 2:

```powershell
cd qma\arc_gateway
npm.cmd install
npm.cmd start
```

Local `.env` should point FastAPI at the local Arc Gateway:

```env
QMA_ARC_GATEWAY_URL=http://127.0.0.1:3000
```

Open:

```text
http://127.0.0.1:8000
http://127.0.0.1:8000/app
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
