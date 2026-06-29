# QMA API Security and Paid Access Model

## Security model

QMA does not trust the frontend for paid access. The browser can improve UX, but the backend is the authority for:

- invoice creation
- Circle Gateway settlement verification
- payer wallet validation
- provider/tier/resource validation
- query fingerprint validation
- short-lived access token issuance
- wallet-bound entitlement persistence

x402 verifies that a payment authorization/settlement exists. QMA still verifies that the payment unlocks the exact provider, tier, and query snapshot requested.

## Rate limit scopes

FastAPI has an in-memory middleware limiter. When a client exceeds a scope, the API returns:

```json
{
  "detail": "rate_limited",
  "scope": "payment_invoice",
  "limit": 20,
  "window_seconds": 60,
  "retry_after_seconds": 42
}
```

Default scopes:

| Scope | Paths | Default |
| --- | --- | ---: |
| `payment_verify` | `/api/v1/payment/verify` | 8/min/IP |
| `payment_invoice` | `/api/v1/payment/invoice` | 20/min/IP |
| `paid_report` | `/api/v1/preview`, `/api/v1/analyze`, `/api/v1/providers/{id}/preview`, `/api/v1/providers/{id}/full-report` | 30/min/IP |
| `public_market` | `/api/v1/live-anomalies`, `/api/v1/agent/recommendations` | 120/min/IP |
| `creator_apply` | `/api/v1/creators/apply` | 6/min/IP |
| `api_default` | other `/api/v1/*` endpoints | 240/min/IP |

Env controls:

```env
QMA_RATE_LIMIT_ENABLED=true
QMA_RATE_LIMIT_WINDOW_SECONDS=60
QMA_RATE_LIMIT_PAYMENT_VERIFY_PER_MIN=8
QMA_RATE_LIMIT_INVOICE_PER_MIN=20
QMA_RATE_LIMIT_REPORT_PER_MIN=30
QMA_RATE_LIMIT_PUBLIC_MARKET_PER_MIN=120
QMA_RATE_LIMIT_CREATOR_APPLY_PER_MIN=6
QMA_RATE_LIMIT_API_DEFAULT_PER_MIN=240
```

## Provider marketplace endpoints

### List providers

```http
GET /api/v1/providers
```

Returns provider metadata plus creator-facing stats:

```json
{
  "provider_id": "funding_memory",
  "provider_name": "Funding Memory Provider",
  "status": "approved",
  "pricing": {
    "preview": {"amount_usdc": 0.001},
    "full": {"amount_usdc": 0.005}
  },
  "stats": {
    "payments": 12,
    "revenue_usdc": 0.044,
    "creator_earned_usdc": 0.0352,
    "platform_fee_usdc": 0.0088
  }
}
```

### Provider stats

```http
GET /api/v1/providers/{provider_id}/stats
```

Shows sales, revenue split, top symbols, buyer type counts, and recent payments.

### Creator application

```http
POST /api/v1/creators/apply
Content-Type: application/json

{
  "creator_wallet": "0x...",
  "provider_id": "whale_memory",
  "provider_name": "Whale Memory Provider",
  "contact": "@creator",
  "category": "market_memory",
  "description": "On-chain whale flow analogs for live funding anomalies.",
  "data_source": "Private indexed on-chain dataset",
  "api_base_url": "https://provider.example.com",
  "sample_schema": "{\"symbol\":\"HYPE\",\"confidence\":0.72}",
  "revenue_wallet": "0x...",
  "revenue_share_bps": 8000
}
```

New applications start as `pending`.

### Creator application lookup

```http
GET /api/v1/creators/applications?wallet=0x...
```

Returns applications submitted by that wallet.

### Admin review

```http
POST /api/v1/creators/applications/{application_id}/review
X-QMA-Admin-Token: <QMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "status": "approved",
  "admin_note": "Provider API and sample output verified."
}
```

Set `QMA_ADMIN_TOKEN` in production. If the env value is empty, local demo review is permissive.

## Marketplace payment flow

1. User selects a provider on `/marketplace` or in the app query bar.
2. Frontend creates an invoice with:

```json
{
  "provider_id": "funding_memory",
  "tier": "preview",
  "resource_type": "qma_signal_report",
  "buyer_type": "human"
}
```

3. User pays through Circle Gateway/x402 on Arc Testnet.
4. Backend verifies settlement and returns a short-lived access token.
5. Frontend calls:

```http
POST /api/v1/providers/{provider_id}/preview?invoice_id=...
Authorization: Bearer <access_token>
```

or:

```http
POST /api/v1/providers/{provider_id}/full-report?invoice_id=...
Authorization: Bearer <access_token>
```

6. Backend records a wallet/provider/tier/query entitlement in Supabase/JSON.

## Revenue split

Current implementation records revenue split in stats:

```text
creator_earned_usdc = revenue_usdc * provider.revenue_share_bps / 10000
platform_fee_usdc   = revenue_usdc - creator_earned_usdc
```

For hackathon speed, funds still settle to the platform seller treasury. Provider withdraw/vault automation is a V2 upgrade.

Recommended roadmap:

1. Provider dashboard with withdrawable accounting.
2. Admin-approved manual payout.
3. Backend signed payout flow.
4. Provider vault/payment splitter contract after the marketplace has real creator demand.
