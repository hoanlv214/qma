# Phase 1 - API Surface Review - Process Log

## Bước 1: Đọc `backend/app/main.py`
- Lần read: `C:\Users\Admin\Downloads\code\buy\qma\backend\app\main.py`
- Kết quả: Xác định app load 10 router từ `backend/app/api/v1/endpoints`: `agent.py`, `chat.py`, `health.py`, `internal.py`, `market.py`, `payments.py`, `platform.py`, `providers.py`, `reports.py`, `wallets.py`.
- Lệnh: `view_file`

## Bước 2: Liệt kê các file trong `backend/app/api/v1/endpoints/`
- Lệnh: `list_dir`
- Kết quả: Đã xác định 11 file (bao gồm `__init__.py`). Đã đọc 10 file router ở trên.

## Bước 3: Đọc từng file router
- `agent.py`: `POST /api/v1/agent/decision`
- `chat.py`: `POST /api/v1/chat`
- `health.py`: `GET /`, `GET /app`, `GET /user`, `GET /profile`, `GET /marketplace`, `GET /api/v1/health`, `GET /api/v1/config`, `GET /api/v1/gateway/info`, `GET /api/v1/engine/profile` (Đã đọc toàn bộ body logic của các handler, xác nhận không leak thông tin nhạy cảm).
- `internal.py`: `GET /api/internal/invoices/{invoice_id}/split-leg/{leg_id}`, `POST /api/internal/invoices/{invoice_id}/split-leg/{leg_id}/reserve`, `POST /api/internal/invoices/{invoice_id}/split-leg/{leg_id}/release`, `POST /api/internal/invoices/{invoice_id}/split-leg/{leg_id}/record`
- `market.py`: `GET /api/v1/providers/{provider_id}/live-anomalies`, `GET /api/v1/agent/recommendations`
- `payments.py`: `POST /api/v1/payment/quote`, `GET /api/v1/payment/settlement/{settlement_id}`, `POST /api/v1/payment/invoice`, `GET /api/v1/payment/invoices/{invoice_id}/status`, `POST /api/v1/payment/verify`, `POST /api/v1/payment/withdraw`
- `platform.py`: `GET /api/v1/metrics`, `GET /api/v1/platform/summary`, `GET /api/v1/traction`, `GET /api/v1/platform/payments`, `GET /api/v1/platform/payers`
- `providers.py`: `GET /api/v1/providers`, `GET /api/v1/providers/{provider_id}`, `GET /api/v1/providers/{provider_id}/stats`, `GET /api/v1/admin/public-config`, `POST /api/v1/providers/{provider_id}/toggle`, `POST /api/v1/creators/apply`, `GET /api/v1/creators/applications`, `POST /api/v1/creators/applications/{application_id}/review`, `POST /api/v1/creators/claim`
- `reports.py`: `POST /api/v1/providers/{provider_id}/preview`, `POST /api/v1/providers/{provider_id}/full-report`, `POST /api/v1/preview` (legacy), `POST /api/v1/analyze` (legacy)
- `wallets.py`: `GET /api/v1/metrics/wallet/{address}` (legacy), `GET /api/v1/wallets/{address}/summary`, `GET /api/v1/wallets/{address}` (legacy), `GET /api/v1/wallets/{address}/payments`, `POST /api/v1/wallets/{address}/session`, `GET /api/v1/wallets/{address}/reports/{entitlement_id}`, `GET /api/v1/entitlements/wallet/{address}`

## Bước 4: Đọc `frontend/src/services/`
- Đã liệt kê và đọc: `agent.ts`, `api.ts`, `gatewayCrypto.ts`, `invoices.ts`, `providers.ts`, `reports.ts`, `traction.ts`, `wallet.ts`, `walletProfileSession.ts`, `x402.ts`.

## Bước 5: Grep tìm kiếm lời gọi API trên frontend

| Lệnh grep | Query | MatchPerLine | Số kết quả |
|---|---|---|---|
| `grep_search` | `fetch\(` | `false` | 0 |
| `grep_search` | `/api/v1` | `false` | 21 file |
| `grep_search` | `fetch(` | `true` | 46 dòng |
| `grep_search` | `api/internal` | `false` | 0 dòng |

**Giải thích chênh lệch 46 kết quả grep vs 30 dòng evidence:**
Có 46 dòng thỏa mãn grep `fetch(`. Trong danh sách evidence, tôi lập chỉ mục **28 dòng** trực tiếp trỏ đến route backend QMA từ thư mục `hooks/` và `components/`, và **1 dòng** từ `services/walletProfileSession.ts:76` (tổng cộng 29 dòng xuất phát từ grep). Đồng thời, tôi bổ sung thêm **2 dòng** gọi qua helper (không chứa `fetch(`) trong `PlatformAnalyticsPanel.tsx:67` và `77`.

Dưới đây là **17 dòng còn lại (bị loại)** trong số 46 kết quả grep và lý do (False Positives / Excluded):
1. `services/x402.ts:37` (`await fetch(resourceUrl)`): Gọi external URL cho Arc Gateway.
2. `services/x402.ts:108` (`await fetch(prepared.resourceUrl)`): Gọi external Gateway settlement.
3. `services/api.ts:41` (`await fetch(apiUrl(path))`): Hàm wrapper cơ sở, không trỏ path cụ thể.
4. `hooks/useQuickProfile.ts:51` (`fetch(${cleanGatewayUrl}/api/wallet-status...)`): Fetch tới Gateway URL.
5. `hooks/useQuickProfile.ts:65` (`fetch(${cleanGatewayUrl}/api/balance...)`): Fetch tới Gateway URL.
6. `hooks/usePayment.ts:193` (`fetch(${gatewayBase}/api/balance...)`): Fetch tới Gateway URL.
7. `hooks/usePayment.ts:267` (`fetch(${gwBase}/api/wallet-status...)`): Fetch tới Gateway URL.
8. `hooks/usePayment.ts:272` (`fetch(calldataUrl)`): Fetch tới public IPFS.
9. `hooks/usePayment.ts:296` (`fetch(${gwBase}/api/balance...)`): Fetch tới Gateway URL.
10. `hooks/usePayment.ts:503`: Biến `endpoint` được định nghĩa ở các dòng trên (500-502) trỏ tới các route đã biết:
  ```typescript
      const endpoint = invoiceForReport?.tier === "preview"
        ? `/api/v1/providers/${encodeURIComponent(providerForReport)}/preview`
        : `/api/v1/providers/${encodeURIComponent(providerForReport)}/full-report`;
  ```
  => Route `/api/v1/providers/{id}/preview` và `/api/v1/providers/{id}/full-report` đã có mặt trong bảng Inventory.
11. `hooks/useFundArcWallet.ts:89` (`fetch(${cleanGatewayUrl}/api/wallet-status...)`): Fetch tới Gateway URL.
12. `hooks/useFundArcWallet.ts:90` (`fetch(${cleanGatewayUrl}/api/balance...)`): Fetch tới Gateway URL.
13. `hooks/useAgentBuyer.ts:672` (`fetch(${API_BASE_URL}/api/v1/payment/verify...`): Lệnh duplicate do logic fallback agent retry.
14. `components/traction/PlatformAnalyticsPanel.tsx:42` (`fetch(${API_BASE_URL}${path})`): Hàm helper cục bộ, đã trích xuất logic tĩnh của nó ra evidence list.
15. `components/profile/ProfileOrdersPage.tsx:244` (`fetch(${cleanUrl}/api/wallet-status...)`): Fetch tới Gateway URL.
16. `components/profile/ProfileOrdersPage.tsx:289` (`fetch(${API_BASE_URL}/api/v1/wallets/...`): Lệnh duplicate trong luồng refresh token lỗi.
17. `components/marketplace/MarketplaceReview.tsx:266`: Biến `providerPath` được định nghĩa ở dòng 263 trỏ tới route đã biết:
  ```typescript
      const providerPath = canLoadApps ? "/api/v1/providers?include_disabled=true" : "/api/v1/providers";
  ```
  => Route `/api/v1/providers` đã có mặt trong bảng Inventory.

*(Phép cộng kiểm chứng: 28 dòng hooks/components + 1 dòng services/walletProfileSession.ts + 17 dòng bị loại = 46 kết quả grep)*

**Danh sách bằng chứng các đoạn mã (Evidence Trail) cho `services/*.ts`:**
Vì các module này bọc lời gọi trong hàm requestJson, ta phải trích thủ công:

- `services/agent.ts:49`
  ```typescript
  49:   return requestJson<AgentDecisionResponse>("/api/v1/agent/decision", {
  ```
- `services/invoices.ts:5`
  ```typescript
  5:   return requestJson<InvoiceResponse>("/api/v1/payment/invoice", {
  ```
- `services/invoices.ts:15`
  ```typescript
  15:   return requestJson<PaymentVerifyResponse>(`/api/v1/payment/verify?invoice_id=${encodeURIComponent(invoiceId)}`, {
  ```
- `services/invoices.ts:23`
  ```typescript
  23:     `/api/v1/payment/invoices/${encodeURIComponent(invoiceId)}/status?invoice_secret=${encodeURIComponent(invoiceSecret)}`
  ```
- `services/invoices.ts:28`
  ```typescript
  28:   return requestJson<Record<string, unknown>>(`/api/v1/payment/settlement/${encodeURIComponent(settlementId)}`);
  ```
- `services/providers.ts:6`
  ```typescript
  6:   return requestJson<{ providers: ProviderSummary[] }>(`/api/v1/providers${suffix}`);
  ```
- `services/providers.ts:10`
  ```typescript
  10:   return requestJson<Record<string, unknown>>(`/api/v1/providers/${encodeURIComponent(providerId)}/stats`);
  ```
- `services/providers.ts:14`
  ```typescript
  14:   return requestJson<Record<string, unknown>>(`/api/v1/agent/recommendations?limit=${encodeURIComponent(String(limit))}`);
  ```
- `services/reports.ts:13`
  ```typescript
  13:       ? `/api/v1/providers/${encodeURIComponent(options.providerId)}/preview`
  ```
- `services/reports.ts:14`
  ```typescript
  14:       : `/api/v1/providers/${encodeURIComponent(options.providerId)}/full-report`;
  ```
- `services/reports.ts:26`
  ```typescript
  26:     `/api/v1/wallets/${encodeURIComponent(address)}/reports/${encodeURIComponent(entitlementId)}`,
  ```
- `services/traction.ts:38`
  ```typescript
  38:   return requestJson<TractionSnapshot>(`/api/v1/traction?${params.toString()}`, init);
  ```
- `services/walletProfileSession.ts:76`
  ```typescript
  76:   const resp = await fetch(`${API_BASE_URL}/api/v1/wallets/${normalized}/session`, {
  ```

**Danh sách bằng chứng các đoạn mã (Evidence Trail) cho `components/` và `hooks/`:**

- `hooks/useQuote.ts:20`
  ```typescript
  20:             const resp = await fetch(`${API_BASE_URL}/api/v1/payment/quote`, {
  ```
- `hooks/useQuickProfile.ts:83`
  ```typescript
  83:       const summaryResp = await fetch(`${API_BASE_URL}/api/v1/wallets/${account}/summary`);
  ```
- `hooks/useQuickProfile.ts:96`
  ```typescript
  96:       const paymentsResp = await fetch(`${API_BASE_URL}/api/v1/wallets/${account}/payments?${params.toString()}`);
  ```
- `hooks/useProviders.ts:16`
  ```typescript
  16:       const resp = await fetch(`${API_BASE_URL}/api/v1/providers`);
  ```
- `hooks/useProviderEarnings.ts:65`
  ```typescript
  65:         const resp = await fetch(`${API_BASE_URL}/api/v1/providers/${encodeURIComponent(provider.provider_id)}/stats`);
  ```
- `hooks/useProviderEarnings.ts:188`
  ```typescript
  188:       const resp = await fetch(`${API_BASE_URL}/api/v1/creators/claim`, {
  ```
- `hooks/useProviderEarnings.ts:272`
  ```typescript
  272:       const submitResp = await fetch(`${API_BASE_URL}/api/v1/payment/withdraw`, {
  ```
- `hooks/usePlatformMetrics.ts:12`
  ```typescript
  12:     const resp = await fetch(`${API_BASE_URL}/api/v1/platform/summary`);
  ```
- `hooks/usePayment.ts:450`
  ```typescript
  450:       const verifyResp = await fetch(`${API_BASE_URL}/api/v1/payment/verify?invoice_id=${encodeURIComponent(currentInvoice.invoice_id)}`, {
  ```
- `hooks/useAgentBuyer.ts:157`
  ```typescript
  157:       const response = await fetch(`${API_BASE_URL}/api/v1/entitlements/wallet/${encodeURIComponent(wallet)}`);
  ```
- `hooks/useAgentBuyer.ts:346`
  ```typescript
  346:         const verifyResp = await fetch(`${API_BASE_URL}/api/v1/payment/verify?invoice_id=${encodeURIComponent(invData.invoice_id)}`, {
  ```
- `hooks/useAgentBuyer.ts:471`
  ```typescript
  471:           fetch(`${API_BASE_URL}/api/v1/agent/recommendations?limit=25`),
  ```
- `components/reports/AppPage.tsx:115`
  ```typescript
  115:         const resp = await fetch(`${API_BASE_URL}/api/v1/config`);
  ```
- `components/profile/ProfileOrdersPage.tsx:101`
  ```typescript
  101:         const resp = await fetch(`${API_BASE_URL}/api/v1/config`);
  ```
- `components/profile/ProfileOrdersPage.tsx:276`
  ```typescript
  276:         fetch(`${API_BASE_URL}/api/v1/wallets/${account}/summary`),
  ```
- `components/profile/ProfileOrdersPage.tsx:277`
  ```typescript
  277:         fetch(`${API_BASE_URL}/api/v1/wallets/${account}/payments?${params.toString()}`, {
  ```
- `components/profile/ProfileOrdersPage.tsx:503`
  ```typescript
  503:       const resp = await fetch(`${API_BASE_URL}/api/v1/wallets/${wallet}/reports/${encodeURIComponent(entitlementId)}`, {
  ```
- `components/marketplace/MarketplaceReview.tsx:196`
  ```typescript
  196:       const resp = await fetch(`${API_BASE_URL}/api/v1/providers`);
  ```
- `components/marketplace/MarketplaceReview.tsx:211`
  ```typescript
  211:       const resp = await fetch(`${API_BASE_URL}/api/v1/admin/public-config`);
  ```
- `components/marketplace/MarketplaceReview.tsx:215`
  ```typescript
  215:           const fallbackResp = await fetch(`${API_BASE_URL}/api/v1/config`);
  ```
- `components/marketplace/MarketplaceReview.tsx:239`
  ```typescript
  239:       const resp = await fetch(`${API_BASE_URL}/api/v1/creators/applications?${params.toString()}`);
  ```
- `components/marketplace/MarketplaceReview.tsx:267`
  ```typescript
  267:         canLoadApps ? fetch(`${API_BASE_URL}/api/v1/creators/applications`, { headers }) : Promise.resolve(null),
  ```
- `components/marketplace/MarketplaceReview.tsx:353`
  ```typescript
  353:       const resp = await fetch(`${API_BASE_URL}/api/v1/creators/apply`, {
  ```
- `components/marketplace/MarketplaceReview.tsx:387`
  ```typescript
  387:       const resp = await fetch(`${API_BASE_URL}/api/v1/providers/${encodeURIComponent(providerId)}/toggle`, {
  ```
- `components/marketplace/MarketplaceReview.tsx:411`
  ```typescript
  411:       const resp = await fetch(`${API_BASE_URL}/api/v1/creators/applications/${encodeURIComponent(applicationId)}/review`, {
  ```
- `components/landing/LandingPage.tsx:30`
  ```typescript
  30:         const resp = await fetch(`${API_BASE_URL}/api/v1/metrics?payment_page_size=1&payer_page_size=1`, {
  ```
- `components/traction/PlatformAnalyticsPanel.tsx:67`
  ```typescript
  67:     const data = await fetchJson(`/api/v1/platform/payments?page=${page}&page_size=10`);
  ```
- `components/traction/PlatformAnalyticsPanel.tsx:77`
  ```typescript
  77:     const data = await fetchJson(`/api/v1/platform/payers?page=${page}&page_size=10`);
  ```
- `components/reports/SignalSidebar.tsx:28`
  ```typescript
  28:       const response = await fetch(`${API_BASE_URL}/api/v1/providers/funding_memory/live-anomalies`);
  ```
- `components/reports/SignalSidebar.tsx:48`
  ```typescript
  48:         const response = await fetch(`${API_BASE_URL}/api/v1/agent/recommendations`);
  ```

## 6. File được nhắc tới nhưng không đọc trực tiếp
- Các file bên ngoài `frontend/src/` gọi API không được quét (do context của ứng dụng chỉ tập trung ở frontend/src).

## 7. Kết luận có rủi ro suy đoán
- Rủi ro 1: Rút ra kết luận về các caller endpoint dựa vào từ khóa `/api/v1` và `fetch(`. Nếu có nơi nào sử dụng biến môi trường hoặc path alias (VD: `/api/internal`) bị lọt khỏi tầm nhìn (do không nằm trong danh sách grep). Tôi đã xác minh `/api/internal` không được frontend gọi (đã chạy lệnh `grep_search` với `Query="api/internal"` trên `frontend/src` và trả về 0 kết quả). Các endpoint này được gọi từ gateway relay bên thứ ba.
- Rủi ro 2: `/api/v1/health`, `/api/v1/gateway/info` và `/api/v1/engine/profile` không tìm thấy caller trực tiếp trên codebase frontend. Thực tế chúng có thể hoàn toàn unused bởi frontend (đã ghi chú rõ trong bảng).
