# Process Log — Phase 4: Data Flow Review

## Phạm vi khai báo
- `backend/app/main.py`
- `backend/app/services/invoice_builder.py`
- `backend/app/services/x402_gateway.py`
- `backend/app/services/payment_state_machine.py`
- `arc_gateway/server.ts`
- Bất kỳ file nào liên quan đến quy trình thanh toán, giải mã báo cáo, và rút tiền.

## Các bước thực hiện (tuần tự)

### Bước 1: Khảo sát `arc_gateway/server.ts`
- Tool dùng: `list_dir`, `view_file`
- Input chính xác: `arc_gateway/server.ts`
- Kết quả: Đọc toàn bộ file từ dòng 1 đến 950. Phân tích rõ 2 luồng quan trọng: 
  - `GET /qma-access/split-leg`: Thực hiện nhận thanh toán (x402 batching), gọi Circle Gateway `facilitator.settle`, sau đó gọi ngược lại backend `/api/internal/.../record` để cập nhật trạng thái hóa đơn.
  - `POST /api/creator/claim`: Thực hiện chuyển USDC (transfer) từ ví on-chain (hot wallet) cho creator dựa trên private key được cấu hình.
- Ghi chú: File TS này đóng vai trò trung gian uỷ quyền thanh toán (Payment Gateway).

### Bước 2: Truy vết luồng Khởi tạo và Xác nhận Hóa Đơn (Report Purchase)
- Tool dùng: `grep_search`, `view_file` (đã có từ Phase 1 và 2)
- Input: `backend/app/api/v1/endpoints/payments.py` (hàm `create_invoice`), `backend/app/services/invoice_builder.py` (hàm `allocate_split_legs_raw` và URL `/qma-access/split-leg`).
- Kết quả: Backend tạo ra hóa đơn có chia tỷ lệ (split legs). Mỗi leg chứa một URL (có chữ ký HMAC) trỏ tới `arc_gateway`. Frontend gọi HTTP 402 vào URL đó để tiến hành thanh toán.

### Bước 3: Truy vết luồng Trả kết quả báo cáo (Report Unlock)
- Tool dùng: Đã có từ Phase 3 (đọc `reports.py`).
- Input: `backend/app/api/v1/endpoints/reports.py` (`provider_full_report`), `backend/app/main.py` (`run_paid_provider_report`).
- Kết quả: Xác nhận luồng Unlock chạy qua check token -> gọi Provider tạo report -> tạo Entitlement Snapshot -> trả về Client.

### Bước 4: Khảo sát luồng Creator Claim (Provider Payout)
- Tool dùng: `grep_search`, `view_file`
- Input: `backend/app/api/v1/endpoints/providers.py` (dòng 270-350 ban đầu, sau đó mở rộng đọc đến dòng 397 để hiểu logic xử lý lỗi).
- Kết quả: Creator ký signature yêu cầu rút tiền -> Backend kiểm tra ví, chữ ký, số dư -> Lưu vào DB `creator_claims_db` -> Gọi `POST /api/creator/claim` tới `arc_gateway` kèm `x-qma-internal-secret`. 

### Bước 5: Xác minh lỗ hổng Double Spend trong Provider Payout (Đọc thêm)
- Phát hiện mâu thuẫn trong lập luận "tiền mất nhưng số dư ảo chưa trừ".
- Khảo sát mã nguồn Backend:
  - `backend/app/main.py` (dòng 704-740): `allocate_creator_claim` tính toán allocations.
  - `backend/app/services/providers_meta.py` (dòng 231-280): `build_provider_stats` tính số dư `claimable` dựa vào `earned_final - claim_amounts_data["reserved_usdc"]`.
  - `backend/app/services/creator_claims.py` (dòng 167-189): `creator_claim_amounts` KHÔNG cộng dồn status `failed` vào `reserved_usdc`.
  - `backend/app/core/state.py` (dòng 144-166): `reload_persistent_state` chỉ tải lại dữ liệu từ JSON.
- Chạy grep `retry|idempotent|webhook` trên `arc_gateway/server.ts` (dòng 528-529).
- Kết quả: Khẳng định 100% nếu request timeout, claim sẽ bị mark là `failed`, số dư khả dụng (`claimable`) tự động khôi phục, dẫn đến Double Spend vì tiền on-chain đã chuyển.

## File đã đọc trực tiếp (danh sách đầy đủ)
- `arc_gateway/server.ts` (đọc toàn bộ 950 dòng)
- `backend/app/api/v1/endpoints/providers.py` (dòng 270-397)
- `backend/app/main.py` (dòng 704-740 liên quan tới allocate_creator_claim, dòng 1272-1300 liên quan tới Provider Deliver)
- `backend/app/services/providers_meta.py` (dòng 231-280)
- `backend/app/services/creator_claims.py` (dòng 167-189)
- `backend/app/core/state.py` (dòng 144-166)
- Các file `invoice_builder.py`, `payments.py`, `reports.py` (sử dụng kiến thức và trích dẫn đã được review/view ở Phase 1, 2, 3).

## File được NHẮC TỚI trong audit nhưng KHÔNG đọc trực tiếp
- (Không có. Tất cả logic được vẽ trong sequence diagram đều đã có evidence từ các file đã đọc trực tiếp).

## Search/grep đã chạy
| Query | Số kết quả | Ghi chú |
|---|---|---|
| `api/v1/creators/claim` | 1 kết quả | Tìm endpoint rút tiền của Creator |
| `split-leg` trên `frontend/src` | 0 kết quả route | Chứng minh frontend không hardcode URL mà lấy động từ invoice |
| `split-leg` trên `backend/app/services` | 2 kết quả | Tìm nơi sinh ra `pay_url` cho hóa đơn |
| `(?i)retry\|idempotent\|webhook` trên `arc_gateway/server.ts` | 2 kết quả | Ở dòng 528-529, thuộc luồng split-leg, KHÔNG nằm trong luồng creator claim. Chứng tỏ lập trình viên quên retry ở creator claim. |

## Các kết luận có RỦI RO SUY ĐOÁN (self-flagged)
- **Suy luận logic Frontend**: Frontend gọi `fetch` vào `pay_url` và bắt mã lỗi 402 (Payment Required) dựa trên thư viện `@circle-fin/app-kit` hoặc `@circle-fin/x402-batching`. Tôi không đọc toàn bộ mã nguồn của thư viện npm này, nhưng hành vi HTTP contract hoàn toàn trùng khớp với tiêu chuẩn x402. Rủi ro suy đoán rất thấp.
