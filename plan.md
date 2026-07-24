# QMA Comprehensive Engineering Review (v2 — Verifiable Process)

Bạn đang thực hiện một audit kỹ thuật toàn diện cho repo này. Bản plan này khác bản cũ ở
một điểm quan trọng: **mọi kết luận đều phải có dấu vết (evidence trail) đi kèm**, và bạn
phải ghi lại process log riêng biệt cho từng phase để người review có thể kiểm tra lại
độc lập với kết quả audit.

---

## QUY TẮC BẮT BUỘC (áp dụng cho TẤT CẢ các phase)

1. **Không suy đoán từ tên file/thư mục.** Nếu bạn chưa mở (read/view) trực tiếp một file,
   bạn KHÔNG được mô tả nội dung, hành vi, hoặc kiến trúc của nó. Nếu cần đề cập tới nó mà
   chưa đọc, phải ghi rõ: `⚠️ CHƯA ĐỌC — không đủ bằng chứng`.

2. **Không khẳng định phủ định mà không có tìm kiếm tương ứng.** Các câu như "None found",
   "No missing endpoints", "Fully covered" chỉ được viết nếu ngay phía trên có liệt kê rõ
   các câu lệnh search/grep đã chạy để xác minh điều đó, kèm số lượng kết quả trả về.

3. **Mọi trích dẫn code (evidence block) phải đến từ lần `view`/`read` gần nhất trong session
   này.** Không copy lại số dòng từ trí nhớ hoặc từ lần đọc trước đó nếu file đã có khả năng
   thay đổi. Nếu không chắc số dòng còn đúng, ghi `(dòng có thể lệch, cần verify lại)`.

4. **Xử lý theo đơn vị nhỏ nhất có thể (per-file, per-endpoint), không gộp lô lớn.** Ví dụ:
   không được "đọc 10 router files rồi tóm tắt chung" — phải xử lý từng router file một,
   ghi log riêng cho từng file, rồi mới tổng hợp.

5. **Không tự ý bỏ qua thư mục nào nếu nó nằm trong phạm vi phase.** Nếu một thư mục
   (ví dụ `arc_gateway/`) được nhắc tới trong bất kỳ finding nào, nó BẮT BUỘC phải đã được
   liệt kê + đọc trực tiếp trong process log của phase đó.

6. **Mỗi phase kết thúc, DỪNG LẠI.** Không tự động chuyển sang phase tiếp theo. In ra tóm tắt
   ngắn (file đã tạo + file log đã tạo) và chờ xác nhận trước khi tiếp tục.

---

## ĐỊNH DẠNG PROCESS LOG (bắt buộc cho mỗi phase)

Với mỗi phase N, ngoài file audit chính `docs/audit/0N-*.md`, phải tạo thêm:

```
docs/audit/logs/0N-process-log.md
```

Log này phải theo cấu trúc sau, viết tuần tự theo đúng thứ tự bạn thực sự thực hiện
(không viết lại theo thứ tự "cho đẹp" sau khi xong):

```markdown
# Process Log — Phase N: <tên phase>

## Phạm vi khai báo
- Danh sách file/thư mục dự kiến sẽ đọc (copy từ plan.md phase này)

## Các bước thực hiện (tuần tự)

### Bước 1: <mô tả hành động, ví dụ "Đọc toàn bộ payment_state_machine.py">
- Tool dùng: view / grep / search
- Input chính xác: <đường dẫn file, hoặc query grep chính xác>
- Kết quả: <số dòng đọc được / số kết quả match / trích 1-2 dòng đại diện>
- Ghi chú: <có gì bất thường, thiếu, hoặc không đọc hết không>

### Bước 2: ...
(lặp lại cho từng bước, KHÔNG được gộp nhiều file vào 1 bước nếu đọc riêng lẻ)

## File đã đọc trực tiếp (danh sách đầy đủ, không thiếu)
- path/to/file1.py — đọc dòng 1–388 (toàn bộ)
- path/to/file2.ts — đọc dòng 1–57 (toàn bộ)

## File được NHẮC TỚI trong audit nhưng KHÔNG đọc trực tiếp
- path/to/fileX — lý do không đọc: <...>
  → Mọi mô tả về file này trong audit chính phải gắn nhãn ⚠️ CHƯA ĐỌC

## Search/grep đã chạy
| Query | Số kết quả | Ghi chú |
|---|---|---|
| "/api/v1" trong frontend/src | 34 matches | dùng để đối chiếu endpoint |

## Các kết luận có RỦI RO SUY ĐOÁN (self-flagged)
Tự bạn liệt kê những chỗ trong audit chính mà bạn cảm thấy kém chắc chắn nhất —
ví dụ vì file dài quá không đọc hết, hoặc vì phải suy luận logic thay vì thấy code trực tiếp.
```

Nếu process log của một phase không đủ chi tiết để một người khác dò lại từng bước —
coi như phase đó CHƯA HOÀN THÀNH.

---

## PHASE 1 — API SURFACE REVIEW

**Đọc (từng file một, ghi log riêng từng file):**
- `backend/app/main.py`
- Từng file trong `backend/app/api/v1/endpoints/` (liệt kê tên cụ thể trước khi bắt đầu)
- Từng file trong `frontend/src/services/`
- Từng file trong `frontend/src/hooks/` có gọi API
- Bất kỳ component nào gọi `fetch`/API trực tiếp (tìm bằng grep `fetch(` và `/api/v1` trước,
  rồi mở từng file match được — không được bỏ qua file nào trong danh sách match)

**Với MỖI router file:**
1. Liệt kê toàn bộ endpoint (method, path, handler function) — copy trực tiếp từ code, không tóm tắt.
2. Grep path đó trong toàn bộ `frontend/src/` — ghi rõ query đã chạy và số kết quả.
3. Nếu có match → ghi đường dẫn file + dòng gọi cụ thể.
4. Nếu không có match → đánh dấu "unused endpoint", nhưng chỉ sau khi đã grep ít nhất 2 biến thể
   (path đầy đủ, và tên handler function) để loại trừ khả năng gọi gián tiếp qua alias.

**Output:** `docs/audit/01-api-surface.md` (giữ cấu trúc mục như bản cũ)
**Log:** `docs/audit/logs/01-process-log.md`

---

## PHASE 2 — PAYMENT LIFECYCLE REVIEW

**Đọc toàn bộ, từng file, không bỏ sót dòng nào (đây là phần rủi ro cao nhất, ưu tiên đọc kỹ):**
- `payment_state_machine.py`
- `x402_gateway.py`
- `settlement_validation.py`
- `payment_signing.py`
- `invoice_builder.py`
- Bất kỳ file nào các file trên import/gọi tới liên quan trực tiếp đến state transition
  hoặc số tiền (nếu phát hiện trong lúc đọc, phải mở thêm và ghi vào log, không được bỏ qua)

**Với mỗi hàm quan trọng (state transition, tính toán số tiền, xác thực settlement):**
- Trích nguyên đoạn code làm evidence (không diễn giải trước khi trích).
- Tự đặt câu hỏi: "Có edge case nào hàm này KHÔNG xử lý?" — liệt kê rõ, kể cả nếu không chắc.
- Không tự kết luận "Severity: Low (Well-Handled)" nếu chưa thử tìm phản chứng
  (ví dụ: thử tìm xem có đường nào bỏ qua check này không).

**Output:** `docs/audit/02-payment-review.md`
**Log:** `docs/audit/logs/02-process-log.md`

---

## PHASE 3 — AUTHORIZATION REVIEW

**Đọc:**
- `security.py`, `security_schemes.py`
- Toàn bộ file có dependency `Depends(...)` liên quan tới auth trong các router
  (grep `Depends(` trong `backend/app/api/v1/endpoints/` trước, liệt kê hết, rồi mở từng cái)
- Middleware auth (nếu có — tìm bằng grep `middleware` trong `backend/app/`)

**Với mỗi route:**
- Ghi rõ route đó có dependency auth nào, hay KHÔNG có (liệt kê cả route không có auth,
  đừng chỉ liệt kê route có auth — thiếu auth ở route nhạy cảm là finding quan trọng).

**Output:** `docs/audit/03-auth-review.md`
**Log:** `docs/audit/logs/03-process-log.md`

---

## PHASE 4 — DATA FLOW REVIEW

**Yêu cầu riêng:** Mỗi sequence diagram (Report Purchase / Report Unlock / Provider Payout)
chỉ được vẽ dựa trên các file đã đọc trực tiếp trong Phase 1–3 CỘNG THÊM bất kỳ file mới nào
cần đọc thêm — nếu đọc thêm, phải ghi vào log của Phase 4, không được dùng "kiến thức" từ
các phase trước mà chưa từng thực sự đọc file.

**Đặc biệt lưu ý `arc_gateway/`:** Nếu Provider Payout flow đề cập tới arc_gateway, thư mục
này BẮT BUỘC phải được liệt kê và đọc trực tiếp trong log Phase 4 (kể cả khi nó là Node/TS,
không phải Python). Nếu không đọc được (ví dụ ngoài phạm vi ngôn ngữ bạn xử lý tốt), phải
ghi rõ trong audit chính: "Provider Payout flow phía arc_gateway (Node/TS) chưa được audit
trực tiếp — chỉ suy luận từ HTTP contract phía backend Python."

**Output:** `docs/audit/04-data-flow.md`
**Log:** `docs/audit/logs/04-process-log.md`

---

## PHASE 5 — ARCHITECTURE REVIEW

**Đọc toàn bộ cấu trúc thư mục** (`ls`/`tree` toàn repo trước, liệt kê ra tất cả thư mục cấp 1-2),
sau đó với mỗi thư mục chưa được đọc ở Phase 1–4, mở ít nhất file entry point của nó
(ví dụ `package.json`, `index.ts`, `main.py`...) trước khi mô tả nó trong audit.

**Output:** `docs/audit/05-architecture.md`
**Log:** `docs/audit/logs/05-process-log.md`

---

## PHASE 6 — EXECUTIVE SUMMARY

Không đọc code mới. Chỉ tổng hợp từ 5 file audit + 5 file log đã tạo. Với mỗi "Top Finding",
phải trích dẫn ngược lại đúng file + dòng trong audit gốc mà finding đó đến từ đâu.

**Output:** `docs/audit/06-summary.md`
**Log:** `docs/audit/logs/06-process-log.md` (chỉ cần ghi bạn đã tổng hợp từ những file nào)

---

## PHASE 7 — VERIFICATION PASS (bắt buộc, chạy sau cùng)

Mở lại TOÀN BỘ 6 file audit vừa tạo. Với mỗi evidence block có trích số dòng cụ thể:
1. Mở lại đúng file, đúng dòng đó.
2. So sánh: nội dung có khớp 100% với những gì đã trích không?
3. Nếu khớp → không cần sửa gì.
4. Nếu KHÔNG khớp hoặc số dòng đã lệch → sửa lại ngay trong file audit, và ghi vào
   `docs/audit/logs/07-verification-log.md` là đã sửa chỗ nào, từ gì thành gì.
5. Với mọi câu có gắn `⚠️ CHƯA ĐỌC` — thử đọc lại lần này. Nếu đọc được, cập nhật finding
   và bỏ nhãn cảnh báo. Nếu vẫn không đọc được (lý do kỹ thuật, ví dụ file không tồn tại
   trong repo), giữ nguyên nhãn và ghi rõ lý do trong verification-log.

**Output:** cập nhật 6 file audit (nếu cần) + `docs/audit/logs/07-verification-log.md`

---

## Sau khi hoàn thành

In ra bảng tổng kết:

| Phase | File audit | File log | Số finding | Số finding gắn ⚠️ CHƯA ĐỌC |
|---|---|---|---|---|

Không tự kết luận "review hoàn tất" nếu cột cuối cùng > 0 mà chưa giải thích rõ trong
verification log tại sao không đọc được các phần đó.