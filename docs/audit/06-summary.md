# 06. Executive Summary & Lessons Learned

Báo cáo này tổng hợp kết quả toàn bộ chiến dịch Audit từ Phase 1 đến Phase 5, phác họa bức tranh toàn cảnh về kiến trúc hệ thống QMA, các lỗ hổng bảo mật/logic hiện tại, và bài học rút ra cho đội ngũ phát triển.

## 1. Tổng quan hệ thống (System Overview)
Kiến trúc QMA phức tạp và tinh vi hơn một ứng dụng Web3 thông thường. Hệ thống bao gồm 4 thành phần chính đã được xác minh:
1. **Backend (Python/FastAPI):** Nơi chứa lõi logic tiền tệ, cấp quyền (`paid_intelligence_kit`), sinh hóa đơn (Split-Leg), và xác minh chữ ký HMAC (`backend/app/main.py`).
2. **Arc Gateway (Node.js/Relay):** Đóng vai trò cầu nối giao dịch on-chain với mạng lưới Circle, tạo receipt và ký HMAC bảo mật với backend (`arc_gateway/server.ts`).
3. **AI Agents (`agents/src/`):** Một package riêng đóng vai trò "Người mua tự động". Được thiết kế theo mô hình "Deterministic Policy Boundary" rất an toàn — AI chỉ lên kế hoạch chọn ứng viên (LLM Planner), còn việc thanh toán bị khóa chặt bởi các policy tĩnh kiểm tra ngân sách và chữ ký (`05-architecture.md:233-241`).
4. **Frontend (React/Vite):** Client-side giao tiếp với backend qua REST API, không lưu trữ thông tin nhạy cảm ở state cục bộ (`05-architecture.md:55-63`).

Nhìn chung, hệ thống áp dụng tốt nguyên tắc Phân quyền (Least Privilege) ở cấp độ mạng (Backend ẩn sau Gateway), nhưng lại gặp vấn đề ở việc **đồng bộ trạng thái phân tán** và **quên kiểm soát truy cập (Access Control) ở những endpoint phụ**.

---

## 2. Danh sách Bug & Lỗ hổng (Vulnerabilities & Bugs)

Dưới đây là 4 vấn đề bảo mật/kiến trúc nghiêm trọng nhất đang tồn tại:

### 🚨 2.1. Critical IDOR trên tính năng AI Chat
- **Vấn đề:** Mọi endpoint lấy báo cáo (`/api/v1/providers/{id}/full-report`) đều ép buộc kiểm tra `qma_access_token`. Nhưng endpoint `/api/v1/chat` lại **HOÀN TOÀN KHÔNG CÓ** tham số kiểm tra token này. Nó chỉ check xem `invoice_id` truyền lên đã được thanh toán chưa.
- **Hệ quả:** Bất kỳ ai đoán được hoặc lấy được `invoice_id` (từ block explorer hoặc log mạng) đều có thể chat với AI và moi móc toàn bộ dữ liệu báo cáo mà không cần trả tiền mua Access Token.
- **Nguồn:** `03-authorization-review.md:16-139`

### 🚨 2.2. Double Spend / Rút ruột Treasury khi Provider Payout
- **Vấn đề:** Khi Creator bấm nút "Claim", `arc_gateway` thực hiện chuyển tiền (ERC20 transfer) on-chain lập tức mà không có cơ chế đối soát (Reconciliation) hay Idempotency Key.
- **Hệ quả:** Nếu transfer thành công nhưng mạng bị lag khiến HTTP response trả về Backend bị timeout, Backend sẽ bắt Exception và tự động đánh dấu Claim là `failed`. Số dư khả dụng của Creator **được hoàn lại**, cho phép họ tiếp tục bấm Claim để rút tiền lần thứ 2, thứ 3... cho tới khi ví Treasury cạn kiệt.
- **Nguồn:** `04-data-flow.md:105-109`

### 🚨 2.3. Lỗ hổng Double-Claim trên Database (Supabase)
- **Vấn đề:** Để chống nạp 1 biên lai (settlement_id) 2 lần, backend hiện tại lấy 2000 hoá đơn mới nhất từ Supabase (`limit=2000`) lên RAM rồi quét `O(N)`. Tồi tệ hơn, file `scripts/supabase_perf_indexes.sql` **không hề tạo `UNIQUE constraint`** cho cột `settlement_id`.
- **Hệ quả:** Kẻ tấn công có thể spam tạo 2001 hoá đơn rác để đẩy hoá đơn hợp lệ ra khỏi bộ nhớ đệm 2000 dòng kia. Sau đó, chúng nộp lại đúng `settlement_id` cũ. Database không chặn (vì thiếu Unique), và Backend cũng không thấy (vì bị trôi khỏi top 2000). Kết quả: 1 giao dịch Circle mua được nhiều báo cáo.
- **Nguồn:** `05-architecture.md:138-169`

### ⚠️ 2.4. Khóa cục bộ (Cross-Process Lock) gây Race Condition khi Scale
- **Vấn đề:** Hàm chống Race condition `cross_process_lock` dùng OS-level lock (`fcntl.flock`) lưu file trong thư mục `/tmp/qma-locks`.
- **Hệ quả:** Khi deploy lên Kubernetes với nhiều Pod chạy song song, file lock ở `/tmp` của Pod này không có tác dụng với Pod kia. Race condition sẽ xảy ra ở môi trường production phân tán.
- **Nguồn:** `02-payment-review.md:136-166`

---

## 3. Bài học rút ra (Lessons Learned)

Từ các lỗ hổng trên, đây là những bài học kỹ thuật xương máu cho dự án:

1. **"Defense in Depth" (Phòng thủ nhiều lớp) là bắt buộc ở tầng Database:** Không bao giờ phụ thuộc hoàn toàn vào logic của Application (Backend) để chống trùng lặp dữ liệu tài chính. Nếu biến `settlement_id` là duy nhất, hãy đặt `UNIQUE` cho nó ở cấp độ SQL Schema. (Bài học từ bug 2.3).
2. **Tuyệt đối không dùng HTTP Synchronous cho các State tài chính:** Việc phụ thuộc vào một request HTTP thành công để cập nhật số dư (như luồng Creator Claim) là thiết kế "bom nổ chậm". **Phải luôn dùng mô hình:** Ghi nhận Intent (Pending) -> Thực thi -> Nhận Webhook Callback (hoặc Polling) để cập nhật trạng thái. (Bài học từ bug 2.2).
3. **Idempotency Key là cứu cánh:** Bất cứ API nào đụng tới chuyển tiền on-chain đều phải nhận một `Idempotency-Key` từ client. Nếu request bị lặp do retry mạng, Gateway phải nhận diện được key này để không chuyển tiền 2 lần.
4. **Cô lập AI (Deterministic Boundary) là thiết kế xuất sắc:** Dự án đã làm rất tốt khi tách biệt bộ não AI (LLM Planner) khỏi quyền ra quyết định thanh toán (Executor). Bài học ở đây là: Hãy luôn để AI đề xuất (Plan), nhưng Code truyền thống (Policy/Rules) mới là kẻ bóp cò (Execute). (Bài học từ thư mục `agents/`).
5. **IDOR thường nằm ở những tính năng "vệ tinh":** Endpoint chính (`/reports`) được bảo vệ cực kỳ cẩn thận với `Security(...)` tiêm vào mọi nơi, nhưng endpoint vệ tinh (`/chat`) lại bị bỏ quên vì lập trình viên nghĩ rằng "chỉ cần check invoice_id là đủ". Luôn phải review auth trên toàn bộ mặt cắt API, không chỉ những API "hiển nhiên". (Bài học từ bug 2.1).
