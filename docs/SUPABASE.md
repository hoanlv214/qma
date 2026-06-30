# QMA Supabase Persistence Guide

QMA can run with local JSON files for development, but JSON files inside Render/Vercel runtime are not durable across redeploys. Supabase gives QMA a persistent source of truth for:

- Circle/Arc payment events
- paid report entitlements
- invoice lifecycle
- wallet profile/history
- dashboard metrics and pagination

The frontend still talks to FastAPI. Supabase is used only by the backend with a server-side service role key.

## 1. Create a Supabase project

1. Go to https://supabase.com/dashboard.
2. Create a new project.
3. Open `Project Settings -> API`.
4. Copy:
   - `Project URL`
   - `service_role` key

Do not put the service role key in frontend code.

## 2. Create QMA tables

Open `SQL Editor` in Supabase and run:

```sql
create table if not exists public.qma_payment_events (
  event_id text primary key,
  invoice_id text,
  settlement_id text,
  payer_address text,
  symbol text,
  tier text,
  provider_id text default 'funding_memory',
  amount_usdc double precision,
  gateway_status text,
  transaction_hash text,
  explorer_url text,
  paid_at double precision,
  event jsonb not null,
  inserted_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists qma_payment_events_paid_at_idx
  on public.qma_payment_events (paid_at desc);

create index if not exists qma_payment_events_payer_idx
  on public.qma_payment_events (payer_address, paid_at desc);

create index if not exists qma_payment_events_symbol_idx
  on public.qma_payment_events (symbol);

create table if not exists public.qma_paid_reports (
  entitlement_id text primary key,
  payer_address text,
  symbol text,
  tier text,
  provider_id text default 'funding_memory',
  query_hash text,
  settlement_id text,
  paid_at double precision,
  saved_at double precision,
  entitlement jsonb not null,
  inserted_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists qma_paid_reports_wallet_idx
  on public.qma_paid_reports (payer_address, saved_at desc);

create index if not exists qma_paid_reports_query_idx
  on public.qma_paid_reports (provider_id, query_hash, tier);

create index if not exists qma_paid_reports_settlement_idx
  on public.qma_paid_reports (settlement_id);

create table if not exists public.qma_invoices (
  invoice_id text primary key,
  status text,
  settlement_id text,
  payer_address text,
  symbol text,
  tier text,
  provider_id text default 'funding_memory',
  query_hash text,
  created_at double precision,
  expires_at double precision,
  paid_at double precision,
  invoice jsonb not null,
  inserted_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists qma_invoices_created_at_idx
  on public.qma_invoices (created_at desc);

create index if not exists qma_invoices_payer_idx
  on public.qma_invoices (payer_address, created_at desc);

create index if not exists qma_invoices_payer_status_paid_idx
  on public.qma_invoices (payer_address, status, paid_at desc);

create table if not exists public.qma_creator_applications (
  application_id text primary key,
  creator_wallet text,
  provider_id text,
  status text default 'pending',
  created_at double precision,
  updated_at double precision,
  application jsonb not null,
  inserted_at timestamptz not null default now()
);

create index if not exists qma_creator_applications_wallet_idx
  on public.qma_creator_applications (creator_wallet, created_at desc);

create index if not exists qma_creator_applications_status_idx
  on public.qma_creator_applications (status, created_at desc);

alter table public.qma_payment_events enable row level security;
alter table public.qma_paid_reports enable row level security;
alter table public.qma_invoices enable row level security;
alter table public.qma_creator_applications enable row level security;
```

There are no public RLS policies on purpose. The FastAPI backend uses the service role key, which bypasses RLS. Browser clients should not query these tables directly yet.

## 3. Configure local `.env`

Add:

```env
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_SCHEMA=public
```

Keep existing QMA/Circle/Arc env values unchanged.

## 4. Migrate existing JSON data

If you already have local runtime files:

```text
payment_ledger.json
paid_reports.json
invoices.json
```

run:

```powershell
python scripts/migrate_json_to_supabase.py
```

The script reads `.env`, then upserts existing local JSON into Supabase.

## 5. Deploy on Render

Add these environment variables to the `qma-api` Render service:

```env
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_SCHEMA=public
```

Redeploy the backend. The `/api/v1/health` response should include:

```json
{
  "storage_backend": "supabase"
}
```

If the env vars are missing, QMA falls back to local JSON:

```json
{
  "storage_backend": "json"
}
```

## 6. What changed in the source code

`storage.py`

- `JsonStorage`: local development fallback.
- `SupabaseStorage`: writes and reads QMA state through Supabase REST.
- `create_storage_backend`: chooses Supabase when env vars exist.

`main.py`

- invoices are saved when created, verified, and used.
- payment events are saved after Circle settlement verification.
- paid report entitlements are saved after preview/full report unlock.
- metrics/profile endpoints reload persisted state before responding.
- creator/provider marketplace applications are saved for admin review.

`scripts/migrate_json_to_supabase.py`

- one-time migration from local JSON to Supabase.

## 7. Operational notes

- Never expose `SUPABASE_SERVICE_ROLE_KEY` in Vercel/frontend.
- Keep report snapshots in `qma_paid_reports.entitlement` so old paid reports survive live market changes.
- Keep full private CSV data outside the public repo. Supabase stores purchases and report snapshots, not necessarily the full market dataset.
- JSON fallback is still useful for local development and judging demos without a configured Supabase project.

## 8. Later upgrades

After the hackathon, the next clean steps are:

- add Supabase Auth or Web3 Auth for wallet sign-in
- add a `wallets` table to link multiple wallets to one user
- move provider marketplace records from code into Supabase
- add RLS policies for user-owned reads if frontend starts querying Supabase directly
- add admin views for revenue, unique wallets, top providers, and top purchased symbols
- move approved provider records from code into a database-backed provider registry
- add provider withdraw accounting and payout automation
