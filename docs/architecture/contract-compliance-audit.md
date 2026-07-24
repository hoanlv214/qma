# QMA Contract Compliance Audit

This audit evaluates the gap between the current QMA implementation and the target 4-spec Intelligence Marketplace Architecture (v1).

## PART 1: Executive Summary

* **Platform Layer:** 13/27 fields (48%) — *Partially Compliant*. The `CreatorApplicationRequest` aligns reasonably well with `ProviderManifest`, but the core asset envelope and previews are heavily tied to funding mechanics rather than the opaque payload standard.
* **Agent Layer:** 3/7 fields (42%) — *Missing Compliant*. The agent core requires a massive refactor. It heavily ingests domain-specific variables (funding rates, win rates) instead of operating as a pure financial proxy.
* **Provider Layer:** 0/4 webhooks (0%) — *Missing Compliant*. `funding_memory` and `oi_memory` are entirely hardcoded into the platform layer, skipping the provider SDK interface completely.
* **Commerce & Settlement Layer:** Pending — sẽ đánh giá ở Part 9 (Checkpoint 3).

*Methodology Note: When calculating the N/M ratio, N represents the number of target fields that are explicitly present in the current schema. Superfluous or leaked fields do not penalize the N/M score directly, but are documented separately in a "Leakage" row for clarity. For nested objects like `metadata`, the child fields are counted individually as required parts of the contract.*

## PART 2: Platform Contract Compliance

### 1. IntelligenceAsset vs ProviderReportResponse
- **Status:** Partially Compliant (4/9 fields).
- **Leakage:** 13+ funding-specific fields (`regime_cluster`, `is_ood`, `win_rate_band`, `top_analogs`, etc.) leak directly into the platform envelope instead of being encapsulated in an opaque payload.
- *Lưu ý về metadata:* Spec mô tả `timestamp` là thời điểm tạo asset, schema hiện tại có `paid_at` là thời điểm thanh toán. Chúng không tương đương nhau, do đó `timestamp` được tính là thiếu.

| Target field (từ spec) | Có trong current schema? | File:line nếu có |
|---|---|---|
| `asset_id` | ❌ Không | UNVERIFIED |
| `provider_id` | ✅ Có | `backend/app/schemas/phase3_responses.py:74` |
| `tier` | ✅ Có | `backend/app/schemas/phase3_responses.py:51` |
| `format` | ❌ Không | UNVERIFIED |
| `metadata.schema_version` | ❌ Không | UNVERIFIED |
| `metadata.timestamp` | ❌ Không (chỉ có `paid_at` mang ngữ nghĩa khác) | UNVERIFIED |
| `metadata.category` | ❌ Không | UNVERIFIED |
| `metadata.context_hash` | ✅ Có (`query_hash`) | `backend/app/schemas/phase3_responses.py:50` |
| `payload` | ✅ Có (`provider_specific_data`) | `backend/app/schemas/phase3_responses.py:66` |

### 2. IntelligencePreview
- **Status:** Missing Compliant (0/4 fields).
- **Leakage:** Không có object riêng.
- **Hiện trạng:** Hệ thống không có schema `IntelligencePreview` riêng biệt. Thay vào đó, API tái sử dụng toàn bộ khối `ProviderReportResponse` khổng lồ và ép `tier="preview"` thông qua hàm `run_paid_provider_report` để che đi (mask) các trường dữ liệu bị khóa.

| Target field (từ spec) | Có trong current schema? | File:line nếu có |
|---|---|---|
| `provider_id` | ❌ Không (Nằm trong object chung) | `backend/app/api/v1/endpoints/reports.py:39` (Nơi truyền `required_tier="preview"`) |
| `teaser_text` | ❌ Không | UNVERIFIED |
| `confidence_score` | ❌ Không | UNVERIFIED |
| `preview_payload` | ❌ Không | UNVERIFIED |

### 3. IntelligenceScore vs AgentRecommendationItem
- **Status:** Partially Compliant (3/5 fields).
- **Leakage:** Schema hiện tại nhúng trực tiếp `query` và `live` metrics vào kết quả chấm điểm của agent.

| Target field (từ spec) | Có trong current schema? | File:line nếu có |
|---|---|---|
| `provider_id` | ✅ Có | `backend/app/schemas/phase3_responses.py:23` |
| `relevance_score` | ✅ Có (`score`) | `backend/app/schemas/phase3_responses.py:27` |
| `confidence_score` | ❌ Không | UNVERIFIED |
| `price_usdc` | ✅ Có (`suggested_price_usdc`) | `backend/app/schemas/phase3_responses.py:29` |
| `justification` | ❌ Không (dùng mảng `reasons` chứa logic domain thay thế) | UNVERIFIED |

### 4. ProviderManifest vs CreatorApplicationRequest
- **Status:** Partially Compliant (6/9 fields).
- **Leakage:** Rất sạch, gần như không có field thừa.

| Target field (từ spec) | Có trong current schema? | File:line nếu có |
|---|---|---|
| `provider_id` | ✅ Có | `backend/app/schemas/providers.py:10` |
| `provider_name` | ✅ Có | `backend/app/schemas/providers.py:11` |
| `provider_type` | ❌ Không | UNVERIFIED |
| `categories` | ✅ Có (`category` - dạng string) | `backend/app/schemas/providers.py:13` |
| `pricing_model` | ❌ Không | UNVERIFIED |
| `supported_assets` | ❌ Không | UNVERIFIED |
| `webhook_url` | ✅ Có (`api_base_url`) | `backend/app/schemas/providers.py:18` |
| `contact_info` | ✅ Có (`contact`) | `backend/app/schemas/providers.py:12` |
| `revenue_share_bps` | ✅ Có | `backend/app/schemas/providers.py:23` |

## PART 3: Agent Contract Compliance

- **Status:** Missing Compliant.
- **Target:** The agent LLM prompt should see only `price_usdc`, `score`, `confidence`, `provider`, `category`.
- **Violations:**
  1. `backend/app/services/agent_decision.py:48-51`: The core agent prompt logic hardcodes `"oi_memory" in lowered` and `"funding_memory" in lowered`, directly coupling the platform router to specific provider IDs.
  2. `backend/app/services/agent_decision.py:224`: The `_evaluated_candidates` payload passes `canonical_query` directly into the agent's context, leaking `fundingRate` and `marketCap`.
  3. `backend/app/services/agent_decision.py:233`: The agent reads `reasons`. These reasons are generated in `backend/app/services/agent_recommendations.py:48-69` and contain phrases like "extreme negative funding" and "very high open-interest crowding", forcing the agent to reason about crypto mechanics rather than financial metrics.

## PART 4: Provider Architecture Compliance

`funding_memory` and `oi_memory` are currently functioning as monolithic, first-party modules rather than independent providers.

**Provider-Specific Assumptions Embedded in Platform Code:**
1. `backend/app/services/agent_recommendations.py:14`: The platform itself initiates a `deps.scan_mexc_live()` call to pull crypto anomalies. This is domain logic (MEXC scanning) executing inside the platform's recommendation engine.
2. `backend/app/services/agent_recommendations.py:43-69`: The platform itself calculates the `score` by hardcoding `funding_score = min(45.0, funding_pct * 18)` and `turnover_score`. In the target architecture, the platform must issue a POST to `/score` and let the provider calculate its own score.

## PART 5: Marketplace Compliance

This section evaluates what information is exposed on the public Provider Catalog and public endpoints.

- **Status:** Partially Compliant (3/5 fields).
- **Leakage:** The `provider.metadata()` schema dumps internal settlement keys and full pricing dicts, exposing platform-level mechanics to anonymous clients.

| Target field (từ spec) | Có trong current schema? | File:line nếu có |
|---|---|---|
| `provider_name` | ✅ Có | `backend/app/providers.py:110` |
| `category` | ✅ Có | `backend/app/providers.py:114` |
| `teaser_text` | ❌ Không (dùng `description` thay thế) | UNVERIFIED |
| `price_usdc` | ✅ Có (`pricing.full.amount_usdc`) | `backend/app/providers.py:120` |
| `reputation` | ❌ Không | UNVERIFIED |

*Note: The actual `ProviderListResponse` relies on `provider.metadata()` via `backend/app/services/providers_meta.py:55`. It successfully exposes names, categories, and pricing, but lacks formal teaser texts and reputation scores.*

## PART 6: Frontend Compliance

- **Status:** Missing Compliant.
- **Goal:** The frontend should use an `AssetViewerShell` that delegates rendering of opaque payloads to a `ProviderRegistry`.
- **Current State:** The frontend contains hardcoded components tightly coupled to `funding_memory` and crypto mechanics. 
- **Platform vs Funding UI Breakdown:**
  1. **Funding-Specific UI (Needs extracting to a plugin):**
     - `frontend/src/components/reports/AppPage.tsx:458-461`: Hardcodes columns for "P90 Best", "P75", "P50 Med", and "P25".
     - `frontend/src/components/reports/ReportWorkspace.tsx:75-76`: Directly accesses `unlockedReport.percentiles.P50_median`.
     - `frontend/src/components/paywall/PaywallPanel.tsx:47`: Hardcodes sales copy promising "win rates, typical returns, and historical analogs".
  2. **Platform UI (Generic, can be kept):**
     - `frontend/src/components/reports/MarketplaceReview.tsx` (Handles agent scoring).
     - `frontend/src/components/reports/WalletConnect.tsx` (Handles payments).

## PART 7: OpenAPI Compliance

This section evaluates the alignment of current endpoints with the required Provider SDK / Webhook interface.

- **Status:** Missing Compliant (0/4 endpoints).

| Target Endpoint (từ spec) | Có trong current API? | File:line nếu có |
|---|---|---|
| `discover()` [HTTP method không spec chỉ rõ - giả định GET] | ❌ Không | UNVERIFIED |
| `score(context)` [HTTP method giả định POST] | ❌ Không (Logic nằm trong `agent_recommendations.py`) | UNVERIFIED |
| `preview(context)` [HTTP method giả định POST] | ❌ Không (Dùng `/api/v1/providers/{id}/preview` ép tier) | `backend/app/api/v1/endpoints/reports.py:18` |
| `deliver(context, invoice_id)` [HTTP method giả định POST] | ❌ Không (Dùng `/api/v1/providers/{id}/full-report`) | `backend/app/api/v1/endpoints/reports.py:47` |

*Note: The platform currently exposes `/preview` and `/full-report` on behalf of the provider, rather than calling out to a provider SDK webhook to generate the assets. The `score` and `discover` endpoints are entirely absent from the provider interface.*

## PART 8: Commerce & Settlement Compliance

- **Status:** Fully Compliant (100%).
- **Goal:** The payment, x402 gateway, and Arc settlement must be completely agnostic to the provider's domain logic.
- **Current State:** 
  1. `backend/app/services/settlement_validation.py:13-56`: `validate_arc_payment()` only checks `USDC` currency, `amount`, `status`, `fromAddress`, and `toAddress`. No provider-specific metrics (like tier or funding) are validated on-chain.
  2. `backend/app/services/invoice_builder.py:50-68`: `invoice_payment_schema()` strictly handles `amount_usdc` and `pricing_profile`.
  3. `backend/app/main.py:1249`: `run_paid_provider_report` passes `provider_id` to route funds, decoupled from the intelligence generation.

## PART 9: Revisit Executive Summary (Commerce Layer)

In Checkpoint 1, the Commerce & Settlement Layer was marked "Pending". Based on the evidence in Part 8, we can now assign a score:
- **Commerce & Settlement Layer:** 3/3 fields (100% Compliant)
  - `invoice_id`: ✅ Có (`backend/app/services/invoice_builder.py`)
  - `amount_usdc`: ✅ Có (`backend/app/services/invoice_builder.py:53`)
  - `settlement_status`: ✅ Có (`backend/app/services/settlement_validation.py:37`)

## PART 10: Provider SDK / Webhook Gap Analysis

- **Status:** Missing Webhook Dispatcher.
- **Goal:** Providers should be able to integrate via external HTTP webhooks (`webhook_url`), as defined in `ProviderManifest` (spec `provider-onboarding-spec.md`).
- **Current State:** The `ProviderRegistry` (`backend/app/core/providers.py`) only supports Python subclasses (`IntelligenceProvider`). 
- **Missing Infrastructure:** There is no generic HTTP dispatcher in `run_paid_provider_report` that forwards the `context` to an external URL. Providers must currently submit code directly into the QMA repository.

## PART 11: Migration Strategy

Based on the audit, here is the architectural migration path to decouple QMA into an Intelligence Marketplace:

1. **Phase 1: Encapsulation (Non-Breaking)**
   - Move all crypto-specific fields in `ProviderReportResponse` (`regime_cluster`, `win_rate_band`, etc.) into a nested `payload` dictionary.
2. **Phase 2: Registry & Frontend Decoupling**
   - Implement `ProviderManifest` natively in `backend/app/providers.py`.
   - In `frontend/src/components/reports/`, create a `ProviderRegistry` that maps `provider_id` to isolated React renderers (e.g., `FundingReportRenderer`), preventing `AppPage.tsx` from hardcoding `P25`/`P50`.
3. **Phase 3: Agent Abstraction**
   - Remove `funding_memory` hardcoded keywords from `agent_decision.py:48-51`. 
   - Force the LLM to route based purely on `relevance_score` and `price_usdc` from `ProviderManifest`.
4. **Phase 4: Webhook Implementation**
   - Add a `webhook` provider type to `ProviderRegistry` capable of proxying HTTP calls to 3rd party providers, fully realizing the remote SDK interface.
