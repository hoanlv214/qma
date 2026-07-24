# Process Log — Phase 2: Payment Lifecycle Review

## Phạm vi khai báo
Danh sách các file đã dự kiến đọc:
- `payment_state_machine.py`
- `x402_gateway.py`
- `settlement_validation.py`
- `payment_signing.py`
- `invoice_builder.py`
- Các file có liên quan tới state transition. Đã đọc thêm `internal.py` và `main.py` để xem nơi state thực sự được gọi.

## Các bước thực hiện (tuần tự)

### Bước 1: Đọc `payment_state_machine.py`
- Tool dùng: `view_file`
- Input chính xác: `c:\Users\Admin\Downloads\code\buy\qma\backend\app\services\payment_state_machine.py`
- Kết quả: Đọc 157 dòng (toàn bộ file).
- Ghi chú: Xử lý logic tính toán state `paid`, `partial_paid`, `pending`, `expired`, `disputed` cho x402 split legs và gateway.

### Bước 2: Đọc `x402_gateway.py`
- Tool dùng: `view_file`
- Input chính xác: `c:\Users\Admin\Downloads\code\buy\qma\backend\app\services\x402_gateway.py`
- Kết quả: Đọc 77 dòng (toàn bộ file).
- Ghi chú: Chứa `fetch_circle_settlement` và `find_arc_batch_tx`.

### Bước 3: Đọc `settlement_validation.py`
- Tool dùng: `view_file`
- Input chính xác: `c:\Users\Admin\Downloads\code\buy\qma\backend\app\services\settlement_validation.py`
- Kết quả: Đọc 80 dòng (toàn bộ file).
- Ghi chú: Logic quan trọng: xác minh `toAddress`, `amount`, `currency` chống fake payment.

### Bước 4: Đọc `payment_signing.py`
- Tool dùng: `view_file`
- Input chính xác: `c:\Users\Admin\Downloads\code\buy\qma\backend\app\services\payment_signing.py`
- Kết quả: Đọc 166 dòng (toàn bộ file).
- Ghi chú: Xác thực chữ ký HMAC cho leg receipt, access token. Chuyển đổi chuẩn xác số liệu `USDC` / raw float.

### Bước 5: Đọc `invoice_builder.py` (Lần 1)
- Tool dùng: `view_file`
- Input chính xác: `c:\Users\Admin\Downloads\code\buy\qma\backend\app\services\invoice_builder.py`
- Kết quả: Đọc 388 dòng (toàn bộ file).
- Ghi chú: Logic tính `creator_share_bps` vs `platform_share_bps` và trả về `split` mode.

### Bước 6: Khảo sát caller của state validation (`internal.py`, `main.py`)
- Tool dùng: `grep_search`, `view_file`
- Input chính xác: Grep `validate_arc_` trên `backend/app`. Đọc `internal.py` (204 dòng) và trích xuất `main.py` (dòng 1000-1100).
- Kết quả: Đã xác minh `main.py` vẫn nắm giữ logic ghi state cuối cùng thông qua các hàm wrap `verify_payment` và `verify_split_payment`. Các API route nội bộ relay gateway gọi qua `internal.py`.

### Bước 7: Phân tích truy vết dữ liệu `settlement` và Split Verification
- Tool dùng: `grep_search`, `view_file`
- Lệnh: 
  - Chạy `grep_search` cho `verify_split_` trong `main.py`. 
  - Dùng `view_file` đọc `main.py` từ dòng 930 đến 1000.
- Kết quả: Xác định được `verify_split_payment` nằm trong khoảng này. Trace được nguồn gốc của `has_authoritative_gateway_claims` lấy từ `submitted.payer_address and submitted.gateway_status` (payload), nhưng sau đó được xác minh qua `verify_split_receipt` (HMAC) trước khi gán cho biến `settlement` tại dòng 967. Xác minh logic chặn fake payment.

### Bước 8: Kiểm tra Invoice Integrity và Entitlement Logic
- Tool dùng: `grep_search`, `view_file`
- Lệnh:
  - Chạy `grep_search` cho `allocate_split_legs_raw` trong `invoice_builder.py` không có kết quả, dùng `view_file` xem lại dòng 1-150 và 270-388.
- Kết quả: Đã định vị `allocate_split_legs_raw` ở dòng 86 để đánh giá thuật toán Largest-Remainder. Đã định vị logic cấp access token (`invoice_payment_state_response`) tại dòng 270-388 phụ thuộc vào `access_status`.

### Bước 9: Khảo sát implementation của `cross_process_lock`
- Tool dùng: `grep_search`, `view_file`
- Lệnh:
  - Grep `cross_process_lock` trên `backend/app`. 
  - Đọc file `backend/app/core/state.py` từ dòng 68 đến 120.
- Kết quả: Xác định được `cross_process_lock` là một context manager sử dụng OS-level advisory lock (`fcntl.flock`) trên file cục bộ (`/tmp/qma-locks`). Xác nhận race condition sẽ xảy ra nếu chạy multi-pod phân tán.

## File đã đọc trực tiếp (danh sách đầy đủ, không thiếu)
- `backend/app/services/payment_state_machine.py` — đọc dòng 1–157 (toàn bộ)
- `backend/app/services/x402_gateway.py` — đọc dòng 1–77 (toàn bộ)
- `backend/app/services/settlement_validation.py` — đọc dòng 1–80 (toàn bộ)
- `backend/app/services/payment_signing.py` — đọc dòng 1–166 (toàn bộ)
- `backend/app/services/invoice_builder.py` — đọc toàn bộ (1-388), view lại cụ thể dòng 1-150 và 270-388.
- `backend/app/api/v1/endpoints/internal.py` — đọc dòng 1–204 (toàn bộ)
- `backend/app/main.py` — đọc dòng 930-1000 và 1000-1100.
- `backend/app/core/state.py` — đọc dòng 68-120.

## File được NHẮC TỚI trong audit nhưng KHÔNG đọc trực tiếp
- (Không có, tất cả các file liên quan logic đều đã được đọc).

## Search/grep đã chạy
| Query | Số kết quả | Ghi chú |
|---|---|---|
| `validate_arc_` trên `backend/app` | 6 kết quả (main.py, settlement_validation.py) | Tìm caller của validation. Xác nhận main.py gọi hàm validate. |
| `api/internal` trên `backend/app` | 4 kết quả (`endpoints/internal.py`) | Kiểm tra vị trí định nghĩa logic internal endpoint. |
| `verify_split_` trên `main.py` | 0 kết quả grep lỗi, dùng view_file | Tìm thân hàm xác nhận thanh toán split. |

## Các kết luận có RỦI RO SUY ĐOÁN (self-flagged)
- **Rủi ro kiểm chứng data gốc:** Trước đó đã suy đoán `invoice["settlement"]` là "tĩnh cấu hình" nhưng chưa trace tới ngọn. Đã đọc lại `main.py` (dòng 930-1000) và `invoice_builder.py` (dòng 71-79) để kiểm chứng chính xác dữ liệu cấu hình đến từ `paid_kit.settlement_profile()` (server-side), còn dữ liệu thực tế (thanh toán) đến từ `fetch_circle_settlement` (Gateway API) hoặc Payload được ký HMAC (trusted relay).
- **Rủi ro Performance:** Hàm quét Double Claim O(N) trong `invoice_builder.py` được gắn nhãn Medium/Low, nhưng đây là suy đoán dựa trên giả định data size nhỏ. Nếu size lớn, event loop sẽ block.
