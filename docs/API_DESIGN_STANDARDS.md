# QMA Backend API Design Standards

Mục tiêu: mọi route mới sinh ra tài liệu OpenAPI/Scalar đúng, đầy đủ **ngay khi viết code**,
không cần đợt "dọn dẹp lớn" nào nữa. Tài liệu là hệ quả của việc tuân thủ quy chuẩn khi code,
không phải việc làm thêm sau đó.

Nguyên tắc nền: **code-first có kỷ luật**. FastAPI vẫn tự sinh OpenAPI từ Pydantic (nhanh,
không cần viết spec tay), nhưng 8 luật dưới đây là bắt buộc, không phải khuyến nghị — và luật
số 8 (test tự động) là cơ chế duy nhất đảm bảo luật 1–7 không bị trôi theo thời gian.

---

## 1. Không bao giờ trả `dict` trần, không bao giờ nhận `dict` trần

- Mọi route bắt buộc có `response_model=`.
- Mọi request body bắt buộc là Pydantic model, không dùng `payload: dict`.
- Ngoại lệ duy nhất: route có `include_in_schema=False` (internal/debug thật sự), và ngay cả
  route đó cũng nên có model nếu nhận input từ client bên ngoài (internal gateway vẫn cần
  validate).

**Vì sao bắt buộc ngay từ đầu**: retrofit `response_model` sau khi route đã chạy production là
việc rủi ro nhất trong toàn bộ đợt dọn dẹp vừa qua — FastAPI lọc field không khai báo, một
model thiếu field là bug âm thầm cắt dữ liệu thật. Nếu bắt buộc từ dòng code đầu tiên, rủi ro
này không tồn tại.

## 2. Mọi response model kế thừa từ 2 base class dùng chung, không tự chế

```python
# schemas/response_base.py
class ResponseModel(BaseModel):
    """Base cho mọi response schema. extra='allow' là lưới an toàn (không mất field runtime
    nếu model khai thiếu), KHÔNG phải lý do để lười khai báo field đã biết trước."""
    model_config = ConfigDict(extra="allow")
```

```python
# schemas/pagination.py
class Page(ResponseModel, Generic[T]):
    items: List[T]
    page: int
    page_size: int
    total: int
    has_next: bool
```

Quy tắc đi kèm: `extra="allow"` là **lưới an toàn cho field không lường trước** (ví dụ dữ liệu
động từ Gateway/provider bên thứ ba), **không phải cái cớ để khai model rỗng rồi để hết cho
runtime tự lấp**. Nếu bạn biết chắc field nào tồn tại (đọc thấy trong code build dict), phải
khai nó trong model tường minh — chỉ dữ liệu thực sự không đoán trước được mới dựa vào
`extra="allow"`.

## 3. Mọi dict được trả về từ ≥ 2 route phải thành model có tên, không copy-paste dict

Nếu bạn thấy mình sắp viết:
```python
return {"symbol": ..., "tier": ..., "amount_usdc": ...}  # y hệt route khác đã có
```
— dừng lại, tạo một model named (`PaymentEventItem`, `EntitlementItem`...) trong
`schemas/domain/`, import dùng chung. Đây chính là bài học từ `wallet_events_with_invoice_fallback`
từng bị lặp cấu trúc dict ở 3 nơi khác nhau trước khi được gom lại.

## 4. Bảng ý nghĩa status code — cố định, không tự sáng tác thêm

| Code | Ý nghĩa trong hệ thống QMA | KHÔNG dùng để |
|---|---|---|
| 400 | Input sai định dạng / vi phạm business rule (không phải lỗi validate Pydantic — đó là 422 tự động) | |
| 402 | Cần thanh toán trước khi truy cập nội dung (report/full-report) | |
| 403 | Thiếu/sai token xác thực (access token, wallet token, admin token, internal secret) | **KHÔNG dùng 401** — quy ước QMA thống nhất mọi lỗi auth trả 403, kể cả "token rỗng" |
| 404 | Resource không tồn tại (invoice, provider, entitlement, settlement...) | |
| 409 | Xung đột trạng thái (leg đã settled, settlement_id đã bị claim...) | |
| 429 | Rate limit — luôn dùng `RateLimitErrorResponse`, không dùng `ErrorResponse` thường | |
| 500 | Lỗi nội bộ không lường trước | |
| 502 | Upstream (Circle Gateway, relayer...) trả lỗi/timeout | |
| 503 | Tính năng chưa cấu hình (thiếu secret, thiếu storage backend...) | |

Đây chính là bảng để tránh lặp lại lỗi vừa phát hiện (một route ghi "401" trong `description`
trong khi hệ thống dùng 403). Khi viết route mới, **tra bảng này trước khi gõ số**, không tự
quyết theo cảm giác REST "chuẩn" ở nơi khác.

## 5. Mọi `HTTPException` phải đi qua handler chung, không tự chế response lỗi

Không bao giờ tự trả `JSONResponse({"error": ...})` thủ công. Luôn `raise HTTPException(status_code=X, detail="...")`
— handler toàn cục (`qma_http_exception_handler`) tự bọc thành envelope chuẩn
`{error, message, status_code, detail}`. Việc này đảm bảo **schema lỗi khai trong OpenAPI luôn
khớp runtime**, không thể lệch, vì chỉ có một nơi tạo response lỗi.

## 6. Mọi security scheme định nghĩa một lần, có `description`, dùng chung

Tất cả nằm trong `core/security_schemes.py`, không định nghĩa `Header(default=None)` rải rác
trong từng route. Convention đặt tên header: `X-QMA-{Purpose}-Token` (Title-Case), viết
`description` giải thích rõ 3 điều bắt buộc ngay khi tạo scheme (không đợi ai hỏi mới bổ sung):
1. Cách lấy token (endpoint nào cấp).
2. Có fallback qua query param không.
3. Hệ quả chính xác khi thiếu/sai (status code nào, dữ liệu rút gọn hay từ chối hẳn).

## 7. Docstring route = template 3 phần bắt buộc, viết cùng lúc với code

```python
@router.get(..., summary="<một dòng, xuất hiện trên sidebar Scalar>")
def my_route(...):
    """
    <Ai gọi route này, để làm gì.>

    Auth: <public / optional token (khác biệt public vs private data ra sao) / bắt buộc token>.

    Edge-case: <ít nhất 1 hành vi biên cụ thể — thứ tự sort, giới hạn mặc định,
    field nào có thể null khi nào>.
    """
```

Viết đủ 3 dòng này **khi tạo route**, không để trống rồi "Phase 8" mới quay lại đoán ý code cũ
— lúc đó phải đọc lại toàn bộ implementation để suy ngược, tốn gấp nhiều lần công viết ngay
từ đầu.

## 8. Field mới thêm vào request/response luôn có `example` ngay khi khai báo

```python
symbol: str = Field(examples=["BTC_USDT"])
```
Không dùng placeholder (`"string"`, `"example"`). Ví dụ phải là giá trị hợp lệ thật, vì Scalar
dùng nó để tự điền form "Test Request" — ví dụ sai khiến người dùng thử API lần đầu bị lỗi ngay.

---

## Cơ chế enforce — quan trọng nhất, không có cái này thì 7 mục trên chỉ là lời hứa

Thêm (hoặc mở rộng) một bài test duy nhất, chạy trong CI, quét toàn bộ OpenAPI schema và
**fail nếu route mới không tuân thủ** — đây là "linter" cho tài liệu API, tương tự cách
`test_openapi_docs.py` đã có sẵn trong repo, chỉ cần mở rộng để bao phủ đủ 8 luật trên:

```python
# tests/test_api_design_standards.py
def test_every_public_route_has_response_model(app_openapi_schema):
    for path, methods in app_openapi_schema["paths"].items():
        for method, op in methods.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            responses = op.get("responses", {})
            ok = responses.get("200", {}).get("content") or responses.get("201", {}).get("content")
            assert ok, f"{method.upper()} {path} thiếu response schema cho 2xx"

def test_every_route_has_description(app_openapi_schema):
    for path, methods in app_openapi_schema["paths"].items():
        for method, op in methods.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            assert op.get("summary"), f"{method.upper()} {path} thiếu summary"
            assert op.get("description"), f"{method.upper()} {path} thiếu description"

def test_every_429_uses_rate_limit_error_schema(app_openapi_schema):
    for path, methods in app_openapi_schema["paths"].items():
        for method, op in methods.items():
            resp_429 = op.get("responses", {}).get("429")
            if not resp_429:
                continue
            schema_ref = resp_429["content"]["application/json"]["schema"].get("$ref", "")
            assert "RateLimitErrorResponse" in schema_ref, f"{method.upper()} {path} 429 sai schema"

def test_no_401_used_anywhere(app_openapi_schema):
    # Quy ước QMA: lỗi auth luôn 403, không dùng 401 — test này chặn drift ngay khi ai đó
    # (người hoặc AI) vô tình thêm 401 vào route mới.
    for path, methods in app_openapi_schema["paths"].items():
        for method, op in methods.items():
            assert "401" not in op.get("responses", {}), f"{method.upper()} {path} dùng 401, quy ước QMA là 403"

def test_every_field_has_example(app_openapi_schema):
    schemas = app_openapi_schema["components"]["schemas"]
    missing = []
    for name, schema in schemas.items():
        for field, prop in schema.get("properties", {}).items():
            if "example" not in prop and "examples" not in prop and "$ref" not in prop:
                missing.append(f"{name}.{field}")
    assert not missing, f"Field thiếu example: {missing}"
```

Test cuối (`test_every_field_has_example`) nên bật dần — khi bổ sung field mới, test sẽ tự báo
đỏ ngay tại PR đó, thay vì tích luỹ nợ tài liệu tới đợt sau mới phát hiện qua audit thủ công.

---

## Cấu trúc thư mục gợi ý (nếu muốn dọn lại theo quy chuẩn)

```
backend/app/schemas/
  response_base.py       # ResponseModel(extra=allow)
  pagination.py          # Page[T] generic
  errors.py              # ErrorResponse, RateLimitErrorResponse
  domain/                # model dùng chung ≥2 route: PaymentEventItem, EntitlementItem, PayerBreakdownItem
  requests/               # request model theo domain
  responses/              # response model theo domain
backend/app/core/
  security_schemes.py     # toàn bộ APIKeyHeader + description
  status_codes.md         # bảng ở mục 4, dạng file để mọi người (và AI) tra trước khi code
  openapi_responses.py    # helper gắn responses={} theo bảng status_codes
tests/
  test_api_design_standards.py   # bài test enforce ở trên — chạy trong CI mỗi PR
```

---

## Khi review PR có route mới — checklist 30 giây

- [ ] Có `response_model=`? Có Pydantic request model (không phải `dict`)?
- [ ] `summary` + `description` đủ 3 phần (Purpose / Auth / Edge-case)?
- [ ] Status code lỗi tra đúng bảng mục 4 (không tự sáng tác, không dùng 401)?
- [ ] Field mới có `example`?
- [ ] Nếu dict giống route khác — đã dùng lại model chung chưa, hay đang copy-paste?
- [ ] `pytest tests/test_api_design_standards.py` xanh?

Nếu cả 6 mục trên đều qua, route đó sinh ra tài liệu Scalar đúng chuẩn **miễn phí**, không cần
đợt "Phase dọn dẹp" nào về sau nữa.
