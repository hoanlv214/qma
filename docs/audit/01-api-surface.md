# 01. API Surface Review

## 1. Phương pháp & Phạm vi (Methodology)
Tất cả các route được định nghĩa trong `backend/app/api/v1/endpoints/*.py` đã được rà soát và đối chiếu với các lệnh gọi từ phía frontend (`frontend/src/services/`, `hooks/`, `components/`).

## 2. API Inventory

### Endpoint Đang Sử Dụng (Actively Used)
| Endpoint Path | Method | Module/Function | Gọi từ (Frontend File + Lệnh Grep/View) |
|---------------|--------|-----------------|------------------------------------------|
| `/api/v1/agent/decision` | `POST` | `agent.py / create_agent_decision` | `services/agent.ts:49` |
| `/api/v1/config` | `GET` | `health.py / get_client_config` | `AppPage.tsx:115`, `ProfileOrdersPage.tsx:101`, `MarketplaceReview.tsx:215` |
| `/api/v1/payment/quote` | `POST` | `payments.py / quote_payment` | `hooks/useQuote.ts:20` |
| `/api/v1/payment/settlement/{settlement_id}` | `GET` | `payments.py / get_payment_settlement` | `services/invoices.ts:28` |
| `/api/v1/payment/invoice` | `POST` | `payments.py / create_invoice` | `services/invoices.ts:5`, `hooks/usePayment.ts` |
| `/api/v1/payment/invoices/{invoice_id}/status` | `GET` | `payments.py / get_payment_invoice_status` | `services/invoices.ts:23` |
| `/api/v1/payment/verify` | `POST` | `payments.py / verify_payment` | `services/invoices.ts:15`, `hooks/usePayment.ts:450`, `hooks/useAgentBuyer.ts:346` |
| `/api/v1/payment/withdraw` | `POST` | `payments.py / submit_withdraw` | `hooks/useProviderEarnings.ts:272` |
| `/api/v1/metrics` | `GET` | `platform.py / get_metrics` | `components/landing/LandingPage.tsx:30` |
| `/api/v1/platform/summary` | `GET` | `platform.py / get_platform_summary` | `hooks/usePlatformMetrics.ts:12` |
| `/api/v1/traction` | `GET` | `platform.py / get_traction` | `services/traction.ts:38` |
| `/api/v1/platform/payments` | `GET` | `platform.py / get_platform_payments` | `PlatformAnalyticsPanel.tsx:67` (qua hàm nội bộ `fetchJson` tại dòng 41) |
| `/api/v1/platform/payers` | `GET` | `platform.py / get_platform_payers` | `PlatformAnalyticsPanel.tsx:77` (qua hàm nội bộ `fetchJson` tại dòng 41) |
| `/api/v1/providers` | `GET` | `providers.py / list_providers` | `services/providers.ts:6`, `hooks/useProviders.ts:16`, `MarketplaceReview.tsx:196` |
| `/api/v1/providers/{provider_id}/stats` | `GET` | `providers.py / get_provider_stats` | `services/providers.ts:10`, `hooks/useProviderEarnings.ts:65` |
| `/api/v1/admin/public-config` | `GET` | `providers.py / get_admin_public_config` | `MarketplaceReview.tsx:211` |
| `/api/v1/providers/{provider_id}/toggle` | `POST` | `providers.py / toggle_provider_plugin` | `MarketplaceReview.tsx:387` |
| `/api/v1/creators/apply` | `POST` | `providers.py / apply_creator_provider` | `MarketplaceReview.tsx:353` |
| `/api/v1/creators/applications` | `GET` | `providers.py / list_creator_applications` | `MarketplaceReview.tsx:239`, `267` |
| `/api/v1/creators/applications/{application_id}/review` | `POST` | `providers.py / review_creator_application` | `MarketplaceReview.tsx:411` |
| `/api/v1/creators/claim` | `POST` | `providers.py / create_creator_claim` | `hooks/useProviderEarnings.ts:188` |
| `/api/v1/providers/{provider_id}/preview` | `POST` | `reports.py / provider_preview_signal` | `services/reports.ts:13` |
| `/api/v1/providers/{provider_id}/full-report` | `POST` | `reports.py / provider_full_report` | `services/reports.ts:14` |
| `/api/v1/wallets/{address}/summary` | `GET` | `wallets.py / get_wallet_summary` | `hooks/useQuickProfile.ts:83`, `ProfileOrdersPage.tsx:276` |
| `/api/v1/wallets/{address}/payments` | `GET` | `wallets.py / get_wallet_payments` | `hooks/useQuickProfile.ts:96`, `ProfileOrdersPage.tsx:277` |
| `/api/v1/wallets/{address}/session` | `POST` | `wallets.py / create_wallet_profile_session` | `services/walletProfileSession.ts:76` |
| `/api/v1/wallets/{address}/reports/{entitlement_id}` | `GET` | `wallets.py / get_wallet_report_detail` | `services/reports.ts:26`, `ProfileOrdersPage.tsx:503` |
| `/api/v1/entitlements/wallet/{address}` | `GET` | `wallets.py / get_wallet_entitlements` | `hooks/useAgentBuyer.ts:157` |
| `/api/v1/providers/{provider_id}/live-anomalies` | `GET` | `market.py / get_provider_live_anomalies` | `SignalSidebar.tsx:28` |
| `/api/v1/agent/recommendations` | `GET` | `market.py / get_agent_recommendations` | `services/providers.ts:14`, `useAgentBuyer.ts:471`, `SignalSidebar.tsx:48` |

### Endpoint Dành Cho Internal / Gateway Callback
| Endpoint Path | Method | Module/Function | Mục đích sử dụng |
|---------------|--------|-----------------|------------------|
| `/api/internal/invoices/{invoice_id}/split-leg/{leg_id}` | `GET` | `internal.py` | Lấy chi tiết leg |
| `/api/internal/invoices/{invoice_id}/split-leg/{leg_id}/reserve` | `POST` | `internal.py` | Reserve để chống race condition trên gateway relay |
| `/api/internal/invoices/{invoice_id}/split-leg/{leg_id}/release` | `POST` | `internal.py` | Hủy reserve nếu fail |
| `/api/internal/invoices/{invoice_id}/split-leg/{leg_id}/record` | `POST` | `internal.py` | Cập nhật khi gateway relay verify thành công |

### Unused/Deprecated Endpoints
| Endpoint Path | Method | Module/Function | Ghi chú |
|---------------|--------|-----------------|---------|
| `/api/v1/chat` | `POST` | `chat.py / handle_chat_request` | Chưa gọi từ frontend (`grep fetch(` không thấy) |
| `/api/v1/health` | `GET` | `health.py / get_health` | Unused. Đã kiểm tra body logic, không leak secret. |
| `/api/v1/gateway/info` | `GET` | `health.py / get_gateway_info` | Unused. Đã kiểm tra, không leak secret (chỉ trả diagnostic). |
| `/api/v1/engine/profile` | `GET` | `health.py / get_engine_profile` | Unused. Đã kiểm tra, không leak secret. |
| `/api/v1/providers/{provider_id}` | `GET` | `providers.py / get_provider` | Chi tiết provider chưa gọi trực tiếp. |
| `/api/v1/preview` | `POST` | `reports.py / preview_signal` | Legacy `funding_memory` endpoint. |
| `/api/v1/analyze` | `POST` | `reports.py / analyze_signal` | Legacy `funding_memory` endpoint. |
| `/api/v1/metrics/wallet/{address}` | `GET` | `wallets.py / get_wallet_metrics` | Legacy, được thay bởi `summary` và `payments`. |
| `/api/v1/wallets/{address}` | `GET` | `wallets.py / get_wallet_profile_alias` | Legacy alias. |

## 3. Data Schema & Model Validation
- Model Input Validate: FastAPI `RequestValidationError` được catch ở `main.py` và wrap lại thành envelope QMA error.
- Hầu hết response loại bỏ field null với `response_model_exclude_unset=True`.

## 4. Frontend API Client Review
- `frontend/src/services/api.ts` dùng `requestJson<T>`, wrapper chuẩn hóa lỗi 4xx/5xx thành `ApiError`.
- `withSyntheticFlag` inject cờ test (cho agent hoặc dev env).
- Cấu trúc fetch từ React hooks khá hỗn loạn, một số gọi trực tiếp bằng `fetch(API_BASE_URL + path)` thay vì dùng helper ở `services/api.ts` (ví dụ `useProviderEarnings`, `useAgentBuyer`, `MarketplaceReview`). Điều này dẫn tới duplicate error handling logic.
