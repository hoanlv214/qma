# QMA Agent Notes

## Trạng thái repo — đọc trước khi làm bất kỳ việc gì

Repo có 2 branch đang mô tả 2 thực tại khác nhau:

- **`main`** — đang **live**, deploy thật cho hackathon. Backend chạy trên
  Render, trỏ vào `main.py` root. Frontend live là `app.html`, `index.html`,
  `user.html`, `marketplace.html`, `docs.html` + `public/*.css,*.js`.
  Đây là bản **legacy, sắp bị thay thế**.
- **`frontend/vite-react-rebuild`** — branch đang code, **nguồn sự thật hiện
  tại** cho công việc mới. Frontend là `frontend/src/` (Vite + React + TS,
  build ra `frontend/dist/`, dự định thay thế hoàn toàn root `*.html` +
  `public/` khi cutover). Backend là `backend/app/` (module layout đầy đủ:
  api/v1/endpoints, core, repositories, schemas, services).

Trước khi sửa file, xác định đang ở branch nào (`git branch --show-current`
nếu không chắc) và áp dụng đúng phần tương ứng.

Không sửa cả legacy (`main`) và rebuild cùng lúc trừ khi được yêu cầu rõ.
Mọi tính năng mới đi vào branch rebuild, không đi vào `main`, trừ hotfix
khẩn cấp cho bản đang live.

`arc_gateway/` là service Node/TS độc lập, đã deploy ổn định riêng trên
Render — ngoài phạm vi agent này, không đụng vào trừ khi được yêu cầu rõ.

## Quan hệ main.py / backend/app — đã xác nhận với người dùng

`backend/app/` là nguồn sự thật của logic thật (đã tách xong, không phải
"đang decompose"). Root `main.py` hiện tại là một **shim/wrapper**: gọi vào
`backend.app` bên trong, tồn tại để Render tiếp tục chạy được mà không cần
đổi start command — không phải bản logic độc lập song song.

⚠️ **Chưa xác nhận đầy đủ**: shim này có tương thích ngược hoàn toàn với API
cũ (route paths, response keys) mà Render config / frontend legacy đang phụ
thuộc hay không, người dùng cũng chưa chắc chắn 100%. Trước khi:
- xóa `main.py` root,
- đổi Render start command trỏ thẳng `backend/app/main.py`,
- hoặc đổi bất kỳ route path / response schema nào trong `backend/app/`,

→ bắt buộc kiểm tra `render.yaml` và xác nhận với người dùng trước, không tự
suy đoán là an toàn.

`main_ref.py` là legacy reference snapshot — **không chạy, không được import
bởi bất kỳ đâu**, chỉ để đối chiếu logic khi rebuild. Không sửa, không xóa.

## Needs verification

- Nguồn sự thật dữ liệu: `paid_reports.json` / `payment_ledger.json` (JSON
  file ở root) **vs** Supabase (có `scripts/migrate_json_to_supabase.py`,
  `scripts/repair_supabase_payments.py`, backup trong `exports/`). Xác nhận
  với người dùng trước khi sửa logic đọc/ghi trong
  `backend/app/repositories/storage.py`.

## Code Search And Refactor Tooling

This repo uses `ast-grep` (`sg`) for syntax-aware code search and refactors. Config lives in `sgconfig.yml`, and saved rules live in `.ast-grep/rules/`.

- Use `sg` for searches that need code structure: FastAPI route decorators, function calls, argument shapes, class/model instantiation, payment state transitions, and refactors that must avoid comments/strings.
- Use `rg` for plain text lookups: log messages, config keys, TODOs, static copy, CSS class names, and file discovery.
- Check `.ast-grep/rules/` before writing a new structural pattern.
- Dry-run structural rewrites first with a plain search. Use interactive rewrites before broad changes.
- Prefer `sg --rewrite` over ad hoc text replacement for syntax-aware multi-file refactors.

Common commands:

```powershell
sg -p 'save_invoice($INVOICE)' -l python .
sg scan -r .ast-grep/rules/python-save-invoice-call.yml
sg scan -r .ast-grep/rules/python-fastapi-app-route.yml
```

QMA-specific reminders:

- New public API routes should be registered in endpoint modules under `backend/app/api/v1/endpoints/` via `APIRouter`, not directly with `@app.get` or `@app.post`.
- Default ast-grep scripts scan live code only (`backend main.py tests`) to avoid noisy reference hits. Scan `main_ref.py` explicitly when comparing parity with the old god file.
- Payment logic is sensitive. Before changing invoice status, settlement verification, split legs, or access tokens, scan for `save_invoice`, `save_payment_ledger`, and payment-required exceptions.
- Keep public API paths and response keys stable during the migration.

## Vùng nhạy cảm (payment/x402)

`backend/app/services/`: `payment_state_machine.py`, `x402_gateway.py`,
`settlement_validation.py`, `payment_signing.py`, `payment_ledger.py`,
`invoice_builder.py`, `creator_claims.py`.

Trước khi sửa bất kỳ file nào ở trên: đọc `docs/agent/PAYMENT_FLOW.md`
trước, không đoán invoice lifecycle hay idempotency rule từ code một mình.
Không ghi trực tiếp vào state invoice — dùng qua service layer (đúng tinh
thần ast-grep rule đã tồn tại: `python-state-invoices-direct-write.yml`).

## Work Protocol

Với mọi task không tầm thường (non-trivial):

1. **Inspect** — xác định branch, đọc `AGENTS.md` liên quan (root + nested nếu có).
2. **Locate source of truth** — file/module thật sự chứa logic cần sửa.
3. **Locate callers** — ai gọi tới đoạn code này.
4. **Locate consumers** — ai phụ thuộc vào output/behavior của nó.
5. **Determine smallest change** — phạm vi sửa nhỏ nhất giải quyết đúng vấn đề.
6. **Verify** — chạy lint/build/test liên quan.
7. **Summarize** — liệt kê file đã đổi, đã verify gì, rủi ro còn lại chưa kiểm chứng.
8. **Branch check** - check branch hiện tại 

Không bắt đầu bằng quét toàn bộ repo. Dừng tìm kiếm ngay khi đã biết: source
of truth, callers, tests liên quan, và cách verify — không đọc thêm ngoài
phạm vi đó.

## Confidence trước khi sửa

Trước khi bắt đầu edit, tự đánh giá và nêu rõ:

- **High** — source of truth rõ ràng, đã xác định callers/consumers, không có
  bản implementation cạnh tranh nào khác. Có thể sửa.
- **Medium** — hiểu phần lớn nhưng còn 1 điểm chưa chắc (ví dụ: chưa chắc file
  này có phải bản đang chạy thật hay không). Nêu rõ điểm chưa chắc, hỏi lại
  nếu ảnh hưởng tới quyết định sửa.
- **Low** — tìm thấy nhiều implementation cạnh tranh nhau, hoặc chưa xác định
  được đâu là nguồn sự thật. **Không sửa.** Inspect thêm hoặc hỏi người dùng
  trước khi động vào code.

## Scope Control

Không được, trừ khi người dùng yêu cầu rõ ràng:
- dọn dẹp/refactor file không liên quan tới task đang làm ("tiện đây sửa luôn")
- đổi tên symbol trên phạm vi toàn repo
- format lại toàn bộ file khi chỉ cần sửa vài dòng
- thay đổi kiến trúc/migrate cấu trúc thư mục
- sửa cả legacy (`main`) và rebuild trong cùng một lượt

## Verification

Chạy các lệnh kiểm tra thật sự tồn tại trong repo trước khi báo là xong —
không claim "đã pass" nếu chưa thực sự chạy lệnh. Nếu không có lệnh
lint/test phù hợp, nói rõ là chưa verify được và tại sao.

## Quy trình làm việc (tổng quát)

1. Xác định đang ở branch nào.
2. Xác định phạm vi nhỏ nhất cần sửa.
3. Nếu chạm vùng nhạy cảm ở trên → dừng, báo cáo rủi ro trước khi sửa.
4. Nếu confidence Low → dừng, không đoán.
5. Sửa tối thiểu, không refactor lan man ngoài phạm vi yêu cầu.
6. Không chạy git command phá hủy (`reset --hard`, `clean -fd`) trừ khi được yêu cầu rõ ràng.

## Documentation loading policy

Load additional documentation only when required.

Frontend UI work:

- frontend/AGENTS.md only

Backend API work:

- backend/AGENTS.md only

Payment:

- PAYMENT_FLOW.md

Legacy migration:

- LEGACY_PARITY_MATRIX.md

Deployment:

- DEPLOYMENT_SETUP.md

Do not load unrelated documentation.