# QMA v2 Migration Blueprint: The Intelligence Marketplace

*Tài liệu này hệ thống hoá toàn bộ các vấn đề kiến trúc hiện tại và định nghĩa Đặc tả (Spec) cho phiên bản v2 nhằm chuyển đổi QMA từ một "Công cụ phân tích Crypto nguyên khối" thành một "Chợ Dữ Liệu Thông Minh (Intelligence Marketplace)" thực thụ.*

---

## PHẦN 1: TỔNG KẾT CÁC VẤN ĐỀ CHÍ MẠNG HIỆN TẠI (THE PROBLEMS)

Dựa trên quá trình kiểm toán (Audit) mã nguồn, hệ thống hiện tại đang vi phạm nguyên tắc "Nền tảng trung lập" ở 4 điểm cốt lõi:

### 1. Bó hẹp nghiệp vụ chuyên ngành (Tightly Coupled Domain Logic)
- **Ở Frontend:** Giao diện bị code cứng các bảng biểu P25, P50, P75 và tỷ lệ thắng (win rates). Nếu trả về một bản tin thời tiết hoặc bài báo, UI sẽ sập.
- **Ở Agent:** AI Prompt bị nhồi nhét từ khóa `"funding_memory"`, bắt Agent phải hiểu khái niệm *"funding âm cực độ"*.
- **Ở Backend:** Nền tảng tự ôm đồm việc chạy hàm `deps.scan_mexc_live()` để lấy giá MEXC và tự tính điểm, ép các Provider phải phụ thuộc vào công thức của Nền tảng.

### 2. Thiếu cơ chế Cắm nối (Missing Plugin/Webhook Infrastructure)
- Các Provider (Funding, OI) đang là các hàm Python viết chết bên trong ruột `qma_engine.py`.
- Nền tảng chưa có cổng HTTP Webhook Dispatcher để một bên thứ 3 (chạy server riêng bằng ngôn ngữ khác) có thể cắm API vào chợ để bán dữ liệu.

### 3. Rủi ro Thanh toán & Phân tán (Distributed Transaction Risk)
- Vòng đời hoá đơn (Invoice State Machine) quá thô sơ (`pending` -> `completed`). 
- **Lỗ hổng:** QMA thu tiền USDC on-chain của khách xong, nếu gọi sang server Provider bị lỗi sập mạng (Error 500) -> Khách mất tiền, QMA không có file báo cáo để trả, và hệ thống **không có cơ chế hoàn tiền (Refund)** hay hàng đợi thử lại (Retry Queue).

### 4. Lỗ hổng Đánh giá & Thao túng (Reputation & Sybil Attack Risk)
- Điểm số hiện tại là điểm do QMA tự tính (rất chủ quan). Nếu để Provider tự chấm điểm, họ có thể khai khống lên 100/100 để lừa Agent.
- Chưa có rào cản chống việc đối thủ dùng ví (wallet) ảo mua báo cáo giá siêu rẻ rồi review 1 sao (Review Bombing) để dìm chết một Provider.

---

## PHẦN 2: ĐẶC TẢ KIẾN TRÚC MỚI V2 (THE SOLUTIONS)

Để giải quyết triệt để 4 vấn đề trên, v2 sẽ áp dụng các cơ chế kiến trúc sau:

### 1. Đóng gói Dữ liệu & UI Plugin Registry (Giải quyết Vấn đề 1)
- **Payload mờ đục:** Mọi dữ liệu chuyên ngành của Funding/OI phải bị nhốt vào một biến `payload: dict`. Nền tảng QMA và Agent bị cấm đọc ruột của biến này.
- **Frontend Switcher:** Giao diện Nền tảng QMA chỉ giữ lại Vỏ bọc (Shell: Nút thanh toán, Header). Ở giữa màn hình sẽ gọi `UIRegistry` để render giao diện tương ứng với Provider (VD: Gọi `FundingReportRenderer` để hiển thị đồ thị P50, hoặc gọi `MarkdownRenderer` cho các nhà cung cấp lạ).

### 2. Provider Registry & Phân tán quyền Lấy dữ liệu (Giải quyết Vấn đề 1 & 2)
- **Giao thức chuẩn:** Mọi Provider (Nội bộ hay Bên thứ 3) đều phải tuân thủ 3 hàm: `score(context)`, `deliver(context, invoice_id)`, và `verify_outcome(context, delivered_at)`.
- **Trách nhiệm lấy dữ liệu:** Lệnh `scan_mexc_live()` bị đuổi khỏi Nền tảng và trả về đúng nhà của Plugin `FundingProvider`. Từ nay Nền tảng QMA sẽ "mù" hoàn toàn về MEXC.
- **Hỗ trợ Webhook (Idempotency):** Thêm loại `WebhookProvider` bắn HTTP POST ra server đối tác. Bắt buộc truyền `invoice_id` làm Idempotency Key. **Contract yêu cầu:** Cùng `invoice_id` -> server đối tác phải trả về response đã cache giống hệt lần đầu (không chỉ bỏ qua xử lý đúp - nếu không QMA retry mà vẫn không lấy được report dù giao dịch gốc đã xong). *Lưu ý: Webhook thật sẽ được giấu sau Feature-Flag cho đến khi hoàn thành hệ thống Hoàn tiền.*

### 3. Escrow State Machine & Retry Queue (Giải quyết Vấn đề 3)
Nâng cấp vòng đời thanh toán sang mô hình Ký quỹ (Escrow) với 5 trạng thái chặt chẽ:
1. **`PAID_ONCHAIN`**: Tiền chảy vào ví trung gian. Sử dụng Circle W3S Programmable Wallets (chỉ Circle giữ key, giảm rủi ro lộ khoá thô). Tuy nhiên cần lưu ý đây vẫn là mô hình **Custodial-at-decision-layer**: Quyết định release/refund vẫn do Backend QMA tự gọi W3S thực thi, không trustless 100% như Smart Contract. Đây là tradeoff kỹ thuật chấp nhận được cho V2.
2. **`DELIVERING`**: Đưa vào hàng đợi. Tự động thử lại (Retry) với giới hạn cứng (Max 3 lần: 15s, 1p, 5p).
3. **`DELIVERED` (Nội bộ)**: Giao file thành công -> Đánh dấu hoàn tất nội bộ và cộng dư nợ vào sổ cái (Batched) để tiết kiệm Gas.
4. **`SETTLED_ONCHAIN` (Finality - Pull Payment)**: Định kỳ ghi nhận khoản thanh toán cho Provider vào trạng thái nợ (pending withdrawals). Provider tự gọi lệnh rút tiền; không push tiền trực tiếp (tránh 1 địa chỉ lỗi làm kẹt cả lô giao dịch).
5. **`DELIVERY_FAILED`** -> **`REFUNDED` (Pull Payment)**: Quá 3 lần thử thất bại, QMA đánh dấu "đang nợ Agent X tiền hoàn". Agent tự gọi `claim_refund()` để rút tiền về. Tách rời quyết định hoàn tiền khỏi thực thi chuyển tiền.

### 4. Hệ thống Đánh giá Trọng số Dòng tiền & Calibration (Giải quyết Vấn đề 4)
- **Calibration Factor (Cảnh báo trước khi mua):** Nền tảng đo độ lệch giữa Confidence tự phong và Outcome thực tế. Báo cáo của Provider có hệ số Calibration thấp sẽ bị hạ tier hoặc dán badge cảnh báo **trước khi** bấm mua. *(Lưu ý: Các ngưỡng FIRM ≥80%, UNRESOLVABLE <60% hiện chỉ là placeholder mượn từ Mimir, bắt buộc phải backtest trên phân phối dữ liệu thật của QMA để chốt số).*
- **Cơ chế đo lường Outcome (Observation Pipeline):** QMA chỉ đóng vai trò bộ lên lịch trình (Cronjob). Sau X giờ kể từ lúc bán, QMA tự động gọi hàm `verify_outcome()` của đúng Provider đó. Việc cào data thực tế (VD: gọi MEXC) và tính độ lệch phải nằm gọn trong ruột Provider. Nền tảng tuyệt đối không tự gọi MEXC để đo kết quả, tránh tình trạng tái dính chặt (Re-coupling) logic chuyên ngành.
- **Proof of Spend (Bằng chứng tài chính):** Review 1-5 sao chỉ có trọng lượng khi người mua đã tiêu một số tiền USDC lớn, triệt tiêu nạn spam review bẩn.
- **Auto-Slashing & Hồi phục:** Nếu API liên tục timeout, QMA tự động ẩn (hide) Provider. Sẽ có ngưỡng phục hồi (Un-slash) nếu Provider duy trì Uptime ổn định trên môi trường production trong X ngày (đo qua chính các lệnh webhook thật QMA định kỳ gọi).

---

## PHẦN 3: LỘ TRÌNH THI CÔNG (IMPLEMENTATION ROADMAP)

Chúng ta sẽ không đập đi viết lại. Mã nguồn hiện tại sẽ được tái cấu trúc (refactor) theo 4 Giai đoạn An toàn:

- **Giai đoạn 1 (Tách vỏ và ruột):** Sửa schema `ProviderReportResponse` bọc Funding data vào `payload`. Bóc code vẽ bảng Funding ở Frontend sang thư mục Plugin riêng.
- **Giai đoạn 2 (Tạo Ổ cắm API):** Dựng `ProviderRegistry` ở Backend. Chuyển logic gọi MEXC vào trong Internal Plugin. *Lưu ý: Khóa `WebhookProvider` lại bằng Feature-Flag, chưa cho gọi ra ngoài.*
- **Giai đoạn 3 (Tẩy não Agent):** Cắt đứt các từ khóa "funding" trong não LLM. Bắt Agent mua hàng chỉ dựa trên Giá tiền và Điểm Tự tin.
- **Giai đoạn 4 (Phẫu thuật Ký quỹ):** Cập nhật `payment_state_machine.py` thành `DELIVERING`, `DELIVERED`, `SETTLED_ONCHAIN` và `REFUNDED`. **Lưu ý:** Escrow phải thiết kế theo mô hình Pull-Payment (`pendingWithdrawals`/`claim_refund`), không push tiền trực tiếp đồng bộ. Cuối cùng: Mở Feature-Flag cho Webhook thực tế hoạt động.
