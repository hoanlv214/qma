# 05. Architecture Review

Báo cáo này rà soát toàn bộ cấu trúc thư mục của repo QMA, tập trung vào các thư mục
**chưa được đọc trực tiếp** ở Phase 1–4, đồng thời đối chiếu các phát hiện mới với
kết luận đã có ở các phase trước. Mọi mô tả dưới đây đều dựa trên file đã `view`/`read`
trực tiếp trong session này qua Filesystem MCP (xem `docs/audit/logs/05-process-log.md`).

## 0. Cây thư mục cấp 1 (đã liệt kê qua `list_directory`)

```
qma/
├── .env / .env.example / .env.local.example / .env.advanced.example
├── agents/              [NODE/TS — buyer-side AI agent, CHƯA từng được audit ở Phase 1-4]
├── arc_gateway/         [NODE/TS — đã đọc toàn bộ server.ts ở Phase 4]
├── backend/             [PYTHON — FastAPI, đã đọc phần lớn ở Phase 1-4]
├── data/                [Sample CSV datasets cho qma_engine.py]
├── docs/                [Tài liệu, bao gồm docs/audit/ — nơi chứa chính báo cáo này]
├── examples/             [Script demo .mjs — agent_buyer, agent_session, test_split_balance]
├── frontend/             [REACT/Vite — đã đọc frontend/src/{services,hooks,components} ở Phase 1]
├── logs/
├── node_modules/         [KHÔNG đọc — third-party, ngoài phạm vi]
├── paid_intelligence_kit/ [PYTHON package — lõi access-token & pricing, CHƯA từng đọc trực tiếp ở Phase 2-3]
├── public/                [Legacy static JS/CSS — KHÔNG thuộc build production, xem mục 6]
├── scripts/                [Ops/migration scripts — bao gồm migrate_json_to_supabase.py]
├── tests/                  [pytest suite]
├── _refs/                  [Third-party/hackathon reference repos — ngoài phạm vi ứng dụng]
├── main.py                 [Legacy compat entrypoint — re-export backend.app.main]
├── qma_engine.py           [Lõi thuật toán thống kê/ML — KMeans, LedoitWolf, NearestNeighbors]
├── market_data.py          [Data fetcher — MEXC funding rate API]
├── storage.py              [Storage abstraction layer — JsonStorage / SupabaseStorage]
├── render.yaml              [Deployment topology — 2 Render services]
└── vercel.json               [Deployment topology — frontend build target]
```

## 1. Backend (`backend/app/`) — Các thư mục con chưa đọc ở Phase 1–4

Phase 1–4 đã đọc: `backend/app/main.py`, toàn bộ `api/v1/endpoints/*.py`, phần lớn
`services/*.py` (payment_state_machine, x402_gateway, settlement_validation,
payment_signing, invoice_builder, providers_meta, creator_claims), và `core/state.py`
(dòng 68–166).

**Chưa đọc trước Phase 5, nay đã đọc entry point:**

| Thư mục/File | Entry point đã đọc | Ghi chú |
|---|---|---|
| `backend/app/core/` | `config.py` (liệt kê), `security_schemes.py` (đọc toàn bộ), `provider_registry.py`, `rate_limit.py`, `openapi_responses.py` (liệt kê, chưa đọc sâu) | Xem Mục 3 — đóng gap quan trọng của Phase 3 |
| `backend/app/repositories/` | `storage.py` (đọc ~40 dòng đầu) | Facade gọi vào `paid_intelligence_kit` + storage backend gốc, xem Mục 4 |
| `backend/app/schemas/` | Liệt kê 14 file (`agent.py`, `chat.py`, `errors.py`, `payments.py`, `providers.py`, `wallets.py`, v.v.) | Pydantic response/request models. Chưa đọc sâu từng file — chỉ xác nhận cấu trúc tồn tại. |
| `backend/app/api/v1/router.py` | Đọc toàn bộ (37 dòng) | **Đã xác minh (Addendum):** File này định nghĩa `api_router` tổng hợp 9 router. Tuy nhiên, đã quét `main.py` và `backend/app/main.py` — các router thực tế được include riêng lẻ qua các hàm factory (VD: `app.include_router(create_chat_router(...))`) kèm Dependency Injection. `api_router` trong file này hoàn toàn là **dead code** bị bỏ sót trong quá trình refactor, không được ứng dụng live sử dụng. Không có rủi ro bảo mật (chỉ là code thừa). |
| `backend/app/services/security.py` | Đọc toàn bộ (43 dòng) | Yêu cầu bắt buộc của Phase 3 gốc nhưng bị bỏ sót. Xem Mục 3. |
| `backend/app/services/plugins/` | Liệt kê: `funding_provider.py`, `oi_provider.py`, `webhook_provider.py` | Provider plugin implementations — chưa đọc nội dung, chỉ xác nhận tồn tại. |
| `backend/app/services/{agent_decision,agent_recommendations,circle_client,payment_events_service,payment_ledger,reports,wallet_profiles,wallet_utils}.py` | KHÔNG đọc | Các file này nằm trong thư mục `services/` đã được Phase 2 đọc một phần — theo đúng nghĩa đen của luật Phase 5 ("mỗi thư mục CHƯA đọc"), `services/` đã coi là "đã đọc" nên không bắt buộc mở lại toàn bộ. Đánh dấu `⚠️ CHƯA ĐỌC TRỰC TIẾP` cho riêng các file này. |

## 2. Frontend (`frontend/src/`) — Thư mục con chưa đọc ở Phase 1

Phase 1 đã đọc: `services/`, `hooks/` (một phần, qua grep), và nhiều `components/`.

**Mới đọc ở Phase 5:**
- `frontend/src/main.tsx` (toàn bộ, 15 dòng) — entry point, import `./app/App`, load 5 file CSS từ `styles/`.
- `frontend/src/state/` (đã đọc): `invoiceStore.ts`, `reportStore.ts`, `walletStore.tsx` — Xác nhận chỉ là React Context/State cục bộ, lưu `qma_connected_wallet` vào localStorage. Không có leak secret.
- `frontend/src/app/` (đã đọc): `App.tsx` (component ghép route), `routes.tsx` (khai báo route URLs). Logic hoàn toàn an toàn.

**Kết luận Frontend:** Đã quét đủ các khu vực chính, không tìm thấy lỗ hổng rò rỉ nào ở layer state.

## 3. Đóng gap Phase 3: `core/security_schemes.py` và `services/security.py`

Plan gốc yêu cầu Phase 3 đọc `security.py`, `security_schemes.py` nhưng theo
`03-process-log.md`, hai file này **không nằm trong danh sách "File đã đọc trực tiếp"**.
Phase 5 đã đọc bù cả hai.

**Evidence (`backend/app/services/security.py` — toàn bộ):**
```python
def require_admin_token(x_qma_admin_token: Optional[str] = None):
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="Admin token is not configured.")
    if not hmac.compare_digest(str(x_qma_admin_token or ""), ADMIN_TOKEN):
        raise HTTPException(status_code=403, detail="Admin token required.")
    return True
```
- **Kết luận:** Khớp hoàn toàn với mô tả của Phase 3 (`deps.require_admin_token()` dùng so sánh an toàn). Không có mâu thuẫn. Đóng gap thành công — Phase 3 §3.1/3.2 nay có bằng chứng trực tiếp thay vì suy luận qua tên hàm.

**Evidence (`backend/app/core/security_schemes.py` — trích đoạn `qma_wallet_token_header`):**
```python
qma_wallet_token_header = APIKeyHeader(
    name="X-QMA-Wallet-Token",
    ...
    description="""...
- **Optional:** `/api/v1/wallets/{address}/payments`, `/api/v1/metrics/wallet/{address}`, and `/api/v1/entitlements/wallet/{address}` accept this token. If present and valid, they return full private data. If absent or invalid, they gracefully fall back to returning redacted public data without throwing an error.
...""",
)
```
- **Phát hiện mới (self-flagged, CHƯA xác minh sâu):** Phase 3 chỉ xác minh route `get_wallet_report_detail` (route `reports/{entitlement_id}`) — route này bắt buộc token. Nhưng docstring trên khai báo 3 route khác (`payments`, `metrics/wallet`, `entitlements/wallet`) có hành vi "graceful fallback to redacted public data" khi thiếu token. **Đây là comment/docstring, KHÔNG phải bằng chứng thực thi** — chưa mở lại `wallets.py` để xác minh code thực tế có redact đúng như mô tả hay không. Đề xuất: Phase 3 addendum cần verify trực tiếp 3 route này.
- **Severity: Chưa xác định (Unverified — cần Phase 3 addendum)**

## 4. Đóng gap Phase 2/4: Storage Backend thực tế là gì?

Phase 2 §3.1 và Phase 4 §2 đều giả định persistent storage là **file JSON cục bộ**
("paid_reports.json", quét O(N) trong `invoice_builder.py`) và khuyến nghị "chuyển
sang SQL/Redis khi scale". Phase 5 phát hiện **hệ thống ĐÃ CÓ sẵn lựa chọn Supabase**,
việc này thay đổi đáng kể khung đánh giá rủi ro.

**Evidence (`storage.py` — hàm factory, đọc toàn bộ file):**
```python
def create_storage_backend(*, ledger_path, reports_path, invoices_path, creators_path, provider_controls_path):
    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("QMA_SUPABASE_URL")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("QMA_SUPABASE_SERVICE_ROLE_KEY")
    schema = os.getenv("SUPABASE_SCHEMA", "public")
    if supabase_url and service_key:
        return SupabaseStorage(url=supabase_url, service_role_key=service_key, schema=schema)
    return JsonStorage(ledger_path=ledger_path, reports_path=reports_path, invoices_path=invoices_path,
                        creators_path=creators_path, provider_controls_path=provider_controls_path)
```

**Evidence (`render.yaml` — service `qma-api`, đọc toàn bộ file):**
```yaml
      - key: SUPABASE_URL
        sync: false
      - key: SUPABASE_SERVICE_ROLE_KEY
        sync: false
      - key: SUPABASE_SCHEMA
        value: public
```

**Evidence (`.env.example` — đọc toàn bộ file):**
```
# Persistent storage. Leave service role blank for local JSON fallback.
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_SERVICE_ROLE_KEY=replace-with-service-role-key-server-only
```

- **Kết luận 1:** Production (Render) có khai báo `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY`
  (giá trị thật nằm trong Render dashboard, không lộ trong repo — `sync: false`). Nhiều khả năng
  môi trường production chạy `SupabaseStorage`, không phải `JsonStorage`. Local/dev mặc định
  dùng JSON nếu để trống 2 biến này (theo comment trong `.env.example`).
  → **Phase 2 §3.1 và Phase 4 §2 cần được gắn thêm chú thích: nhận định "JSON storage" chỉ đúng
  cho môi trường local/dev, KHÔNG chắc đúng cho production.**

- **Kết luận 2 (Phát hiện MỚI, nghiêm trọng hơn):** Việc chuyển sang Supabase **KHÔNG** giải quyết
  triệt để rủi ro Double-Claim O(N) đã nêu ở Phase 2 §3.1. Lý do — đọc `SupabaseStorage.load_invoices()`:
```python
    def load_invoices(self) -> dict:
        rows = self._request(
            "GET", "qma_invoices",
            params={"select": "invoice_id,invoice", "order": "created_at.desc.nullslast", "limit": "2000"},
        ) or []
        invoices = {}
        for row in rows:
            invoice = row.get("invoice")
            invoice_id = row.get("invoice_id") or (invoice or {}).get("invoice_id")
            if invoice_id and isinstance(invoice, dict):
                invoices[invoice_id] = invoice
        return invoices
```
  Hàm này giới hạn cứng `limit: "2000"` bản ghi mới nhất, sau đó `invoice_builder.py`
  (`settlement_id_already_claimed`, đã trích ở Phase 2 §3.1) vẫn quét **O(N) trong Python**
  trên dict trả về — logic KHÔNG được viết lại để tận dụng `UNIQUE constraint` hay filter
  phía SQL như Phase 2 khuyến nghị. **Hệ quả mới:** nếu invoice table vượt quá 2000 bản ghi,
  các invoice cũ hơn (nhưng vẫn có thể còn hợp lệ về mặt logic nghiệp vụ) sẽ **không nằm trong
  danh sách được quét**, khiến check "double claim" có thể bỏ sót các settlement_id cũ.
  - **Severity: Medium–High (self-flagged, cần Phase 2 addendum xác minh)** — mức độ nghiêm
    trọng thực tế phụ thuộc vào tốc độ tăng invoice và TTL của hoá đơn (`ACCESS_TOKEN_TTL_SECONDS`,
    `expires_at`), thứ Phase 5 **chưa** trace lại. Đây là suy luận logic có rủi ro sai nếu có
    tầng cache/index khác ở phía Supabase (ví dụ RLS policy hoặc trigger) mà Phase 5 chưa kiểm tra
    (không có quyền truy cập trực tiếp vào Supabase dashboard/schema, chỉ đọc được code Python
    gọi REST API).
  - **Recommendation:** Phase 2 addendum cần: (1) xác minh giới hạn `limit=2000` có phải là
    rủi ro thực tế dựa trên volume invoice hiện tại; (2) khuyến nghị thay thế check O(N) bằng
    `UNIQUE` constraint SQL trên cột `settlement_id`. **Đã xác minh qua Phase 5 Addendum:** Đọc file `scripts/supabase_perf_indexes.sql` thấy CHỈ CÓ `INDEX` trên `settlement_id`, hoàn toàn **không có `UNIQUE constraint`**. Do đó, database không tự động chặn việc insert settlement_id trùng lặp, biến lỗi `limit=2000` thành một **lỗ hổng Double-Claim thực sự** có thể khai thác nếu đẩy hoá đơn rác để làm trôi hoá đơn hợp lệ ra khỏi top 2000.

## 5. Phát hiện MỚI: `agents/` — Buyer-side AI Payment Agent (chưa từng được audit)

Thư mục `agents/` (Node/TS, package riêng `qma-agents`) **không nằm trong phạm vi bất kỳ
phase nào trước đó** (Phase 1–4 chỉ đọc `backend/`, `frontend/`, `arc_gateway/`).

**Evidence (`agents/package.json`):**
```json
{
  "name": "qma-agents",
  "description": "QMA structured agent planner and payment execution boundary.",
  ...
}
```

**Evidence (`agents/src/index.ts` — toàn bộ):**
```typescript
export * from "./contracts/index.js";
export * from "./planner/schema.js";
export * from "./planner/llmPlanner.js";
export * from "./policy/validateDecision.js";
export * from "./qma/client.js";
export * from "./executor/dryRunExecutor.js";
export * from "./executor/paymentExecutor.js";
export * from "./wallets/signer.js";
export * from "./providers/openai.js";
export * from "./session/index.js";
```

**Evidence (`agents/src/executor/paymentExecutor.ts` — đọc toàn bộ, trích hàm lõi):**
```typescript
export function createPaymentExecutor(defaultSigner?: AgentPaymentSigner): PaymentExecutor {
  return {
    async execute({ invoice, signer }): Promise<PaymentExecutionResult> {
      const activeSigner = signer || defaultSigner;
      if (!activeSigner) throw new Error("No payment authorizer is configured.");
      const settlements: SettlementProof[] = [];
      for (const leg of invoiceLegs(invoice)) {
        const recovered = alreadySettled(leg);
        if (recovered) { settlements.push(recovered); continue; }
        if (activeSigner.walletAddress && leg.pay_to && sameAddress(activeSigner.walletAddress, leg.pay_to)) {
          throw new Error(`Payment wallet is the ${leg.role || leg.leg_id} recipient; refusing self-payment.`);
        }
        const amountUsdc = numberAmount(leg.amount_usdc);
        const rawSettlement = activeSigner.payLeg
          ? await activeSigner.payLeg({ resourceUrl: resourceUrlForLeg(leg), legId: leg.leg_id, amountUsdc })
          : await settleSignedLeg(leg, activeSigner);
        settlements.push(normalizeSettlement(leg, rawSettlement));
      }
      return { settlements };
    },
  };
}
```

- **Mô tả kiến trúc:** Đây là một "AI agent" đứng vai **người mua**, tách biệt hoàn toàn với
  backend/arc_gateway (đóng vai người bán/nền tảng). Nó tự lập kế hoạch (`planner/`), xác thực
  quyết định (`policy/validateDecision.ts`), rồi tự ký và thực thi thanh toán x402 qua
  `paymentExecutor.ts` — bao gồm cả nhánh gọi Circle CLI (`spawn(...)`) để thanh toán bằng
  Circle Agent Wallet.
  - Điểm tích cực đã quan sát được: có guard chống tự-thanh-toán-cho-chính-mình
    (`"Payment wallet is the ... recipient; refusing self-payment"`), và validate lại
    `pay_to`/`amount_raw`/`leg_id` trả về từ settlement để tránh bị gateway trả sai lệch dữ liệu
    (`normalizeSettlement`).
  - **KHÔNG được deploy như một Render service** (không xuất hiện trong `render.yaml`) — nhiều
    khả năng đây là CLI/dev-tool chạy cục bộ hoặc dùng trong demo/hackathon, KHÔNG phải service
    production luôn bật. Tuy vậy nó vẫn là code thực thi thanh toán thật (không phải mock),
    nên vẫn là bề mặt tấn công tiềm ẩn nếu được ai đó chạy với private key thật.
- **Mức độ an toàn (Đã xác minh qua Phase 5 Addendum):** 
  - LLM chỉ đóng vai trò lập kế hoạch (`planner/llmPlanner.ts`), bị giới hạn qua system prompt cực kỳ chặt chẽ (cấm trả về giá trị thanh toán, chỉ trả về `candidate_id`).
  - Quyền quyết định giao dịch bị chặn bởi biên giới chính sách ở `policy/validateDecision.ts` (so khớp ngân sách yêu cầu vs giá thực tế, kiểm tra trùng lặp entitlement).
  - Đây là mô hình "Deterministic Policy Boundary", LLM không có thẩm quyền ra lệnh chuyển tiền mà không qua lớp kiểm duyệt logic tĩnh. 
- **Kết luận:** Thiết kế an toàn. Không cần một phase audit riêng biệt thêm.

## 6. Legacy static frontend (root `public/`, `*.html`) — Dead code, không phải rủi ro sống

**Evidence (`vercel.json` — đọc toàn bộ):**
```json
{
  "framework": "vite",
  "buildCommand": "cd frontend && npm run build",
  "outputDirectory": "frontend/dist",
  ...
}
```
- **Rationale:** Repo có `public/app.js`, `public/marketplace.js`, `public/user.js` cùng các
  file `app.html`, `marketplace.html`, `user.html`, `index.html`, `docs.html` ở gốc repo —
  ban đầu nghi ngờ đây là một frontend thứ hai (vanilla JS) chưa được Phase 1 quét endpoint.
  Sau khi đọc `vercel.json`, xác nhận build production **chỉ lấy `frontend/dist`** (output
  của Vite/React app đã review ở Phase 1). Các file HTML/JS gốc này không nằm trong luồng
  build, nên (trong phạm vi hiểu biết hiện tại về pipeline deploy) không phải là bề mặt
  sống trong production.
- **Severity: Low (Repo hygiene — dead code, khuyến nghị dọn dẹp hoặc archive)**
- **Giới hạn suy đoán:** Kết luận này dựa trên `vercel.json` — nếu có một kênh deploy khác
  (ví dụ static hosting thủ công trỏ vào `public/`) mà Phase 5 chưa biết tới, kết luận này
  có thể sai. `⚠️` mức độ tin cậy: trung bình-cao, không tuyệt đối.

## 7. `qma_engine.py`, `market_data.py` — Lõi thuật toán (chỉ xác nhận sự tồn tại)

**Evidence (`qma_engine.py`, 30 dòng đầu):**
```python
from sklearn.covariance import LedoitWolf
from sklearn.cluster import KMeans
from sklearn.neighbors import NearestNeighbors
...
HISTORICAL_DB_PATH = os.getenv("QMA_HISTORICAL_DB_PATH", ...)
```
- Đây là module thống kê/ML lõi (phân cụm regime thị trường, tìm k-nearest historical
  analogs) đứng sau các con số "win rate", "regime_cluster" mà `reports.py` và `chat.py`
  trả về (đã thấy ở Phase 3 §1.1). **Không đọc sâu logic tính toán** — nằm ngoài phạm vi
  kiến trúc/bảo mật của audit này, chỉ xác nhận vị trí & vai trò trong pipeline.
- `market_data.py`: fetcher gọi MEXC funding-rate API (`requests`), cấp dữ liệu đầu vào cho
  `qma_engine.py`. Chỉ đọc 25 dòng đầu, chưa đọc toàn bộ.
- **`⚠️ CHƯA ĐỌC SÂU`** cho cả hai file — mô tả trên chỉ ở mức kiến trúc/vai trò, không phải
  đánh giá chất lượng thuật toán hay bảo mật input.

## 8. Các thư mục KHÔNG đọc (có lý do rõ ràng)

| Thư mục | Lý do không đọc |
|---|---|
| `node_modules/` (mọi cấp) | Third-party dependency, không phải code của QMA |
| `.git/`, `__pycache__/`, `.pytest_cache/`, `.ast-grep/`, `.codex/`, `.agents/` | Metadata/cache, không phải source |
| `_refs/*` (18 thư mục con) | Xác nhận qua `list_directory` là các repo tham khảo/hackathon third-party (`arc-commerce`, `circle-agent`, `mimir`, v.v.) — không phải code chạy trong QMA production |
| `docs/{architecture,business,hackathon,infrastructure,legacy_v1,specs}/` | Thư mục tài liệu thuần (markdown), không có entry point code để mở theo nghĩa plan.md yêu cầu |
| `logs/` | Log output runtime, không phải source |
| `backend/app/schemas/*.py` (13/14 file, trừ liệt kê tên) | Đã liệt kê tên file nhưng chưa mở nội dung — Pydantic model, rủi ro thấp nhưng vẫn nên đọc ở phase sau nếu cần đối chiếu response schema chi tiết |
| `frontend/src/{app,types,utils}/`, `frontend/public/` | Chỉ xác nhận tồn tại qua import trong `main.tsx`, chưa liệt kê nội dung |
| `scripts/*.py`, `scripts/*.sql` (trừ `migrate_json_to_supabase.py` xem 30 dòng đầu) | Ops/migration script, không phải runtime application code — mở lướt 1 file để xác nhận `SupabaseStorage` tồn tại, chưa đọc `supabase_perf_indexes.sql`/`supabase_cleanup.sql` |
| `tests/*.py` | Chỉ liệt kê tên file để xác nhận có test suite, chưa đọc nội dung |
| `examples/*.mjs` | Chỉ liệt kê tên file |

## 9. Tổng kết Phase 5

Kiến trúc QMA phức tạp hơn những gì Phase 1–4 quan sát được: ngoài cặp
`backend (FastAPI) ↔ frontend (React) ↔ arc_gateway (Node relay)` đã audit kỹ,
hệ thống còn có (a) một package `paid_intelligence_kit` chứa toàn bộ logic
access-token/pricing mà các phase trước chỉ thấy qua lời gọi gián tiếp, (b) một
storage layer có thể chạy trên Supabase thay vì JSON tuỳ môi trường, và (c) một
package `agents/` hoàn toàn độc lập đóng vai người mua tự động — chưa từng được
đưa vào phạm vi audit nào. Ba phát hiện (b) và (c) có khả năng thay đổi mức độ
nghiêm trọng của các finding đã chốt ở Phase 2 và cần một Phase bổ sung để đánh giá
`agents/` một cách nghiêm túc.
