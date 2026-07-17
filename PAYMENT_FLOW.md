# QMA Payment Flow

Đọc file này trước khi sửa bất kỳ file nào trong
`backend/app/services/{payment_state_machine,x402_gateway,settlement_validation,
payment_signing,payment_ledger,invoice_builder,creator_claims}.py`.

Không đoán state machine hay idempotency rule từ đọc code một mình — phần
dưới đây là thiết kế đã được xác nhận, dùng làm căn cứ đối chiếu.

## Mô hình thanh toán: `x402_direct_split`

Hai chân thanh toán (two-leg) cho mỗi giao dịch:
- **Leg 1** — thanh toán tới creator wallet.
- **Leg 2** — thanh toán tới platform treasury.

## Invoice lifecycle

Trạng thái hợp lệ: `pending` → `partial_paid` → `paid`, hoặc `pending` →
`expired`.

- `pending` — invoice vừa tạo, chưa nhận payment nào.
- `partial_paid` — mới nhận được 1 trong 2 leg.
- `paid` — cả 2 leg đã settle.
- `expired` — hết TTL (30 phút) mà chưa đủ 2 leg.

Không có trạng thái nào cho phép unlock nội dung khi chưa đủ cả 2 leg —
đây chính là lớp bảo vệ chống exploit "underpay-but-unlock".

## Idempotency

Khóa idempotency ở cấp `(invoice_id, leg_id)` — không phải chỉ
`invoice_id`. Một leg được xử lý (ghi nhận thanh toán) chỉ một lần; xử lý
lại request cho cùng `(invoice_id, leg_id)` phải là no-op, không được cộng
dồn hoặc ghi đè trạng thái.

## Binding chain (chống underpay-but-unlock)

Ba tầng ràng buộc giữa amount và payTo, theo thứ tự kiểm tra:
1. Invoice tạo ra amount + payTo cố định cho từng leg.
2. Payment request phải khớp chính xác amount + payTo đã bind ở bước 1.
3. Settlement verification xác nhận on-chain khớp với binding — không tin
   payload từ client, phải verify lại từ dữ liệu on-chain/Circle Gateway.

Nếu sửa bất kỳ bước nào trong 3 bước trên, phải xác nhận cả 2 bước còn lại
không bị phá vỡ theo — đây là chuỗi phụ thuộc lẫn nhau, sửa rời một khâu dễ
mở lại lỗ hổng underpay.

## TTL

30 phút kể từ lúc tạo invoice. Sau TTL mà chưa đủ 2 leg → chuyển `expired`,
không tự động gia hạn.

## Trạng thái chưa xác nhận (Needs verification)

- Cross-process locking cho concurrent leg updates — cơ chế cụ thể (DB lock,
  advisory lock, hay optimistic concurrency) chưa được xác nhận lại gần đây;
  kiểm tra `payment_state_machine.py` và `storage.py` hiện tại trước khi giả
  định.
- Disputed invoice handling — quy trình xử lý khi có tranh chấp (ví dụ leg đã
  trả nhưng không match binding) cần đọc code hiện tại, không suy đoán.
- Nguồn dữ liệu thật (JSON file root vs Supabase) — xem mục "Needs
  verification" trong `AGENTS.md` root, ảnh hưởng trực tiếp tới
  `payment_ledger.py` và `invoice_builder.py`.

## Trước khi sửa

1. Xác định leg nào bị ảnh hưởng (creator wallet leg hay treasury leg).
2. Xác định bước nào trong binding chain bị chạm tới.
3. Kiểm tra idempotency key `(invoice_id, leg_id)` có còn đúng ngữ nghĩa sau khi sửa không.
4. Không ghi trực tiếp vào state invoice — dùng qua service layer (ast-grep rule: `python-state-invoices-direct-write.yml`).
5. Nếu confidence Low (theo AGENTS.md) ở bất kỳ bước nào trên — dừng, hỏi lại trước khi sửa.
