# Process Log — Phase 3: Authorization Review

## Phạm vi khai báo
Danh sách các file API endpoint cần check Dependency/Auth:
- `backend/app/api/v1/endpoints/health.py`
- `backend/app/api/v1/endpoints/market.py`
- `backend/app/api/v1/endpoints/platform.py`
- `backend/app/api/v1/endpoints/payments.py`
- `backend/app/api/v1/endpoints/providers.py`
- `backend/app/api/v1/endpoints/reports.py`
- `backend/app/api/v1/endpoints/wallets.py`
- `backend/app/api/v1/endpoints/internal.py`
- `backend/app/api/v1/endpoints/chat.py`
- `backend/app/api/v1/endpoints/agent.py`

## Các bước thực hiện (tuần tự)

### Bước 1: Quét toàn bộ `Depends` và `Security` injection
- Tool dùng: `grep_search`
- Lệnh: Quét regex `@(router|migrated)\.(get|post)` để thống kê mọi route. Quét chuỗi `Depends` và `token` để tìm tất cả các hook auth.
- Kết quả: Xác định FastAPI ở đây KHÔNG dùng `Depends` ở mức Route decorator cho phần lớn các route. Thay vào đó, auth được lấy qua `Security(...)` vào argument của hàm, rồi kiểm tra thủ công trong body hàm qua các hàm như `deps.require_admin_token()` hoặc `deps.verify_wallet_profile_token()`.

### Bước 2: Kiểm tra các Route KHÔNG CÓ Auth (Public Routes)
- Tool dùng: `view_file` (đọc toàn bộ các file `platform.py`, `payments.py`, `chat.py`, `agent.py`).
- Kết quả: Đã lập danh sách chính xác các endpoint công khai không yêu cầu token HTTP. Đặc biệt phát hiện ra **lỗ hổng nghiêm trọng ở `chat.py`**: route này trả về data phân tích từ `paid_reports` nhưng hoàn toàn không kiểm tra `access_token`!

### Bước 3: Đánh giá `api/internal` Secret (Timing Attack)
- Tool dùng: `view_file`
- Lệnh: Xem dòng 15-30 của `backend/app/api/v1/endpoints/internal.py`.
- Kết quả: Tìm thấy hàm `require_internal_gateway_secret`. Xác nhận nó gọi `hmac.compare_digest(..., deps.arc_gateway_internal_secret)`. Không có lỗi Timing Attack.

### Bước 4: Kiểm tra `admin_token` thực tế
- Tool dùng: `view_file`
- Lệnh: Xem toàn bộ `backend/app/api/v1/endpoints/providers.py`.
- Kết quả: Trace từng route `/creators/applications/*` và `/providers/*` để xem `deps.require_admin_token` có bị bypass không. Xác nhận route `review` (duyệt đơn) bắt buộc token. Route `list providers` chỉ bắt buộc nếu gọi kèm `include_disabled=True`.

## File đã đọc trực tiếp (danh sách đầy đủ)
- `backend/app/api/v1/endpoints/platform.py`
- `backend/app/api/v1/endpoints/providers.py`
- `backend/app/api/v1/endpoints/payments.py`
- `backend/app/api/v1/endpoints/chat.py`
- `backend/app/api/v1/endpoints/agent.py`
- `backend/app/api/v1/endpoints/internal.py` (dòng 15-30)
- `backend/app/api/v1/endpoints/reports.py` (toàn bộ)
- `backend/app/api/v1/endpoints/wallets.py` (toàn bộ)
- `backend/app/api/v1/endpoints/health.py` (toàn bộ)
- `backend/app/api/v1/endpoints/market.py` (toàn bộ)

## File được nhắc tới nhưng không đọc trực tiếp
- `backend/app/api/v1/endpoints/admin.py` (File không tồn tại trên đĩa, các API /admin/ được gộp chung trong `providers.py` và `platform.py`).
- `backend/app/api/v1/endpoints/applications.py` (File không tồn tại trên đĩa, các API /creators/applications được gộp chung trong `providers.py`).
- `backend/app/api/v1/endpoints/documents.py` (Đã được xoá hoặc gộp chung, không phát hiện thấy qua lệnh grep router và list_dir).
- `backend/app/api/v1/endpoints/invoices.py` (File không tồn tại độc lập, logic gộp vào `payments.py`).

## Search/grep đã chạy
| Query | Số kết quả | Ghi chú |
|---|---|---|
| `@(router\|migrated)\.(get\|post\|put\|patch\|delete)\(` | 48 kết quả | Map toàn bộ cấu trúc API surface. |
| `Depends` trên `backend/app/api` | 5 kết quả | Tất cả 5 kết quả đều chỉ thuộc về `internal.py`. |
| `admin_token` trên `backend/app/api` | 15 kết quả | Map các route gọi `require_admin_token` và `has_admin_token`. |
| `token` trên `backend/app/api` | 44 kết quả | Trace `wallet_token` và `access_token`. |

## Các kết luận có RỦI RO SUY ĐOÁN (self-flagged)
- **Rủi ro về IDOR trên Chat:** Dựa trên code `chat.py`, route này không đòi token. Bất cứ ai biết `invoice_id` của 1 hoá đơn đã thanh toán đều có thể gọi API. Đây không phải suy đoán mà là một bug thiếu Auth thật sự, nhưng mức độ thiệt hại còn tuỳ thuộc vào việc `invoice_id` có dễ đoán (như UUID hay Integer tự tăng) hay không. Do `invoice_id` thường là chuỗi dài có hash, rủi ro có thể bị giảm bớt, nhưng vẫn là lỗi Missing Auth (IDOR).
