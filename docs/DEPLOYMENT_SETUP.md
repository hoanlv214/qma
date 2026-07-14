# QMA Deployment Setup

This repository currently contains two deployable frontend realities:

- `main`: the live legacy HTML application (`index.html`, `app.html`,
  `user.html`, `marketplace.html`, `docs.html`, and `public/*`).
- `frontend/vite-react-rebuild`: the replacement Vite + React application in
  `frontend/src/`, backed by the modular FastAPI application in `backend/app/`.

Keep them isolated during validation. Do not repoint the live Vercel/Render
projects until the rebuild preview has passed its smoke tests.

## Target architecture

```text
Vercel: qma-react-rebuild-preview
  branch: frontend/vite-react-rebuild
  output: frontend/dist
       |
       v
Render: qma-api-rebuild
  root shim: main.py -> backend.app
       |
       +--> Render: qma-arc-gateway-rebuild
       +--> isolated Supabase/project or test persistence

Existing production remains unchanged:
main -> qma-api -> qma-arc-gateway -> production data
```

No new repository is required. Create a separate Vercel project and separate
Render preview services connected to the same repository and rebuild branch.
This prevents a preview deployment from sharing production API, gateway
secrets, or persistence accidentally.

## Render: production FastAPI backend

Keep the existing production service on `main`:

```text
Name: qma-api
Runtime: Python
Branch: main
Build Command: pip install -r requirements.txt
  Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT
```

For the rebuild preview, the tracked sample datasets are at repository-root
`data/`. If these variables already exist in Render, use these exact relative
paths (not the old `qma/data/...` paths):

```env
QMA_HISTORICAL_DB_PATH=data/sample_funding_historical_analysis.csv
QMA_BACKTEST_OUTCOME_PATH=data/sample_trading_analysis.csv
```

The root `main.py` is the supported Render start-command shim and delegates to
`backend.app`. It is not an independent second backend implementation.

Required production variables include:

```env
QMA_ARC_SELLER_ADDRESS=0xYourSellerTreasuryWallet
QMA_ADMIN_WALLET=0xYourSellerTreasuryWallet
QMA_ADMIN_TOKEN=replace-with-admin-review-token
QMA_ACCESS_TOKEN_SECRET=replace-with-long-random-secret
QMA_ARC_GATEWAY_URL=https://qma-arc-gateway.onrender.com
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_SCHEMA=public
```

Start from `.env.example`; use `.env.advanced.example` only for intentional
overrides. Keep relayer keys and service-role keys out of Vercel.

## Render: production Arc Gateway

Keep the existing gateway on `main`:

```text
Name: qma-arc-gateway
Runtime: Node
Root Directory: arc_gateway
Branch: main
Build Command: npm install
Start Command: npm start
```

The production API must use:

```env
QMA_ARC_GATEWAY_URL=https://qma-arc-gateway.onrender.com
```

## Render: rebuild preview services

Create these services manually in Render, using the same repository and branch
`frontend/vite-react-rebuild`:

```text
qma-api-rebuild
  Runtime: Python
  Root Directory: .
  Branch: frontend/vite-react-rebuild
  Build Command: pip install -r requirements.txt
  Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT

qma-arc-gateway-rebuild
  Runtime: Node
  Root Directory: arc_gateway
  Branch: frontend/vite-react-rebuild
  Build Command: npm install
  Start Command: npm start
```

Cross-link the preview services:

```env
# qma-api-rebuild
QMA_ARC_GATEWAY_URL=https://qma-arc-gateway-rebuild.onrender.com
QMA_SPLIT_LEG_URL_SECRET=<same-random-value-as-gateway>
QMA_SPLIT_RECEIPT_SECRET=<same-random-value-as-gateway>

# qma-arc-gateway-rebuild
QMA_BACKEND_INTERNAL_URL=https://qma-api-rebuild.onrender.com
QMA_SPLIT_LEG_URL_SECRET=<same-random-value-as-api>
QMA_SPLIT_RECEIPT_SECRET=<same-random-value-as-api>
```

These two HMAC secrets must be entered manually with identical values in both
Render services. Do not use separate `generateValue` values: each service
would then sign and verify with different keys, producing `403 invalid split
leg signature`.

Use separate secrets and, preferably, separate Supabase/persistence for the
preview services. Never copy production service-role keys or a funded relay
key into an untrusted preview environment.

## Supabase

Create tables from `docs/SUPABASE.md`. For each environment, verify:

```text
/api/v1/health
/api/v1/config
```

Do not decide between JSON and Supabase storage from deployment settings alone;
that remains the repository's documented needs-verification item.

## Vercel: rebuild preview project

Create a new Vercel project, for example `qma-react-rebuild-preview`, linked to
the existing repository. Configure it as follows:

```text
Production Branch: frontend/vite-react-rebuild (for this preview project)
Root Directory: . (repository root)
Framework Preset: Vite
Install Command: cd frontend && npm ci
Build Command: cd frontend && npm run build
Output Directory: frontend/dist
```

The root directory must remain `.` because the checked-in `vercel.json` runs
the build from `frontend/` and publishes `frontend/dist`. Setting the Vercel
Root Directory to `frontend` would require moving/reworking the root config and
handling the Vite `publicDir: ../public` dependency separately.

Set this variable in both the Vercel Production and Preview environments of
this dedicated preview project:

```env
VITE_QMA_API_BASE_URL=https://qma-api-rebuild.onrender.com
```

The Vite client reads that variable in `frontend/src/services/api.ts`. The
root `index.html` is the legacy landing page; it is not published by this
project because Vercel serves `frontend/dist`. The Vite entry is
`frontend/index.html`. The SPA rewrite in `vercel.json` makes direct refreshes
of `/app`, `/profile`, and `/marketplace` resolve to the React entry.

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

## Why the current Active Branches preview is not sufficient

A branch preview uses the Vercel project's existing root, build, and
environment settings. If that project still publishes the legacy root HTML,
the rebuild branch can appear deployed while serving the wrong entrypoint or
calling the production API. A separate project gives the rebuild an explicit
`frontend/dist` output and isolated Preview environment variable.

## Smoke test

Run these against the rebuild services before any cutover:

```text
https://qma-api-rebuild.onrender.com/api/v1/health
https://qma-api-rebuild.onrender.com/api/v1/config
https://qma-arc-gateway-rebuild.onrender.com/health
https://qma-react-rebuild-preview.vercel.app/
https://qma-react-rebuild-preview.vercel.app/app
https://qma-react-rebuild-preview.vercel.app/profile
https://qma-react-rebuild-preview.vercel.app/marketplace
```

In the browser Network tab, confirm requests use
`https://qma-api-rebuild.onrender.com` and that direct refreshes do not return
404. Test wallet session, report preview/full unlock, profile history, provider
authorization, and failure paths without spending real funds.

## Cutover sequence

1. Validate the rebuild Vercel project against `qma-api-rebuild` and
   `qma-arc-gateway-rebuild`.
2. Open a PR from `frontend/vite-react-rebuild` into `main`. Merge frontend,
   backend, gateway configuration, and deployment configuration together.
3. Deploy the merged `main` to the production Render services. Confirm the
   production API points to the production gateway and persistence.
4. Update the existing production Vercel project to the Vite settings above,
   set production `VITE_QMA_API_BASE_URL=https://qma-api.onrender.com`, and
   deploy from the merged `main`.
5. Smoke-test `/`, `/app`, `/profile`, `/marketplace`, API health, wallet
   session, and report unlock. Only then retire the preview services and legacy
   static files in a separate change.

The preview services are disposable. Production services remain on `main`
until the pull request is merged and the coordinated cutover is verified.
