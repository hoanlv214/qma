# Process Log: Phase 5 (Architecture Review Addendum)

## 1. Mục tiêu
Thực hiện yêu cầu "làm tiếp tục phase 5 thật kĩ càng, rà soát toàn bộ liên quan đến nó". Đặc biệt đóng các gap "⚠️ CHƯA ĐỌC" đã được report cũ liệt kê.

## 2. Các file đã đọc trực tiếp (View File)

### 2.1 Backend / API Routers
- `backend/app/api/v1/router.py` (37 dòng): Đọc toàn bộ. Xác nhận định nghĩa `api_router` nhưng không được dùng.
- `main.py` (138 dòng): Entry point gốc. Chỉ re-export `backend.app.main:app` và vá `state.py`.
- `backend/app/main.py` (1549 dòng): Đọc các đoạn code quan trọng (import, error handling, include_router). 
  - **Phát hiện:** Các router được include trực tiếp qua function factory (VD: `app.include_router(create_chat_router(...))`) kèm theo Dependency Injection (SimpleNamespace).
  - **Kết luận:** `api_router` trong `router.py` là dead code. Routing thực tế đã được verify và không có route lạ.

### 2.2 Database / Supabase Storage
- `scripts/supabase_perf_indexes.sql` (20 dòng): Đọc toàn bộ.
  - **Phát hiện:** File chỉ tạo index `qma_paid_reports_settlement_idx`, hoàn toàn KHÔNG CÓ `UNIQUE constraint` trên `settlement_id` trong database.
  - **Kết luận:** Lỗ hổng "limit 2000" ở Phase 5 là có thật. Database không chặn double-claim ở cấp schema, dẫn đến hệ thống có thể bị claim lại 1 hoá đơn cũ nếu hoá đơn đó trôi khỏi top 2000 bản ghi mới nhất.

### 2.3 Frontend State
- `frontend/src/state/walletStore.tsx`, `invoiceStore.ts`, `reportStore.ts`: Đọc toàn bộ.
  - **Kết luận:** Logic React State cơ bản, chỉ lưu `qma_connected_wallet` ở localStorage. Không có leak secret hay token.
- `frontend/src/app/routes.tsx`: Routing URL cơ bản. Không có lỗ hổng.

### 2.4 AI Agents (`agents/src/`)
- `agents/src/planner/llmPlanner.ts` (40 dòng): Xác nhận LLM chỉ sinh JSON với `candidate_id`, bị cô lập khỏi logic tiền bạc (system prompt cấm trả về price, invoice, settlement).
- `agents/src/policy/validateDecision.ts` (32 dòng): Kiểm tra cực kỳ chặt chẽ budget (budgetUsdc, maxPriceUsdc), lấy giá chuẩn từ pricing map (không tin LLM), và chặn mua trùng nếu đã có entitlement.
- `agents/src/wallets/signer.ts`: Hỗ trợ giao diện `AgentPaymentSigner` và `payLeg` (gọi Circle CLI trực tiếp mà không lộ signature header).
- **Kết luận:** Kiến trúc Agent được thiết kế theo mô hình "Deterministic Policy Boundary" rất an toàn. LLM chỉ là bộ não chọn ứng viên, mọi quyền quyết định tài chính nằm ở `validateDecision` và `paymentExecutor`.

## 3. Các bước tìm kiếm bổ sung
- `grep_search` trên `main.py` và `backend/app/main.py` để tìm `api_router` và `include_router`.

## 4. Kết luận
Đã hoàn tất kiểm tra các vùng mù (blind spots) của Phase 5. Các phát hiện sẽ được cập nhật vào `05-architecture.md`.
