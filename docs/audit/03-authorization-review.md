# 03. Authorization Review

Báo cáo này rà soát toàn bộ các phân hệ uỷ quyền (Authorization) và kiểm soát truy cập (Access Control) trên các endpoint của QMA.

## 1. Missing Authorization (Lỗ hổng không bảo vệ Endpoint)
Bảng dưới đây liệt kê các endpoint quan trọng không yêu cầu hoặc thiếu HTTP Authorization.

| Route | Auth Dependency | Phân loại | Rationale |
|---|---|---|---|
| `GET /api/v1/platform/*` | Không | Public | Các route thống kê platform được thiết kế công khai. Dữ liệu nhạy cảm đã bị xoá qua `deps.compact_payment_event`. |
| `POST /api/v1/payment/withdraw` | Bằng Payload Signature | Public | Không dùng HTTP header token vì client ký cryptographically một `WithdrawRequest` (EIP-712 style). Backend xác minh signature ngay trong hàm `deps.submit_withdraw()`. Rất an toàn. |
| `POST /api/v1/creators/apply` | Không | Public | Đơn đăng ký là public để thu hút creator. |
| `POST /api/v1/creators/claim` | Bằng Payload Signature | Public | Tương tự Withdraw, xác thực bằng `recover_creator_claim_signer` trên nội dung payload thay vì HTTP header. |
| `POST /api/v1/chat` | **THIẾU AUTH (LỖ HỔNG IDOR)** | **LỖI KHIẾM KHUYẾT** | **Critical Finding:** Xem chi tiết Mục 1.1. |

### 1.1 Missing Authorization trên Route Chat (IDOR)
**Evidence (`chat.py:17-132`):**
```python
    @migrated.post(
        "/api/v1/chat",
        response_model=ChatResponse,
        response_model_exclude_unset=True,
        responses=documented_errors(402, 404, 429, 500),
    )
    def handle_chat_request(payload: ChatRequest):
        """Answers interactive user queries regarding a paid report."""
        invoice_id = payload.invoice_id
        user_message = payload.message

        deps.reload_persistent_state()

        invoices_db = deps.get_invoices_db()
        paid_reports = deps.get_paid_reports()
        invoice = invoices_db.get(invoice_id)
        report_record = None

        if invoice:
            settlement_id = invoice.get("settlement_id")
            for record in paid_reports.values():
                rec_report = record.get("report") or {}
                rec_inv = rec_report.get("invoice") or {}
                if rec_inv.get("invoice_id") == invoice_id or (settlement_id and record.get("settlement_id") == settlement_id):
                    report_record = record
                    break
        else:
            for record in paid_reports.values():
                rec_report = record.get("report") or {}
                rec_inv = rec_report.get("invoice") or {}
                if rec_inv.get("invoice_id") == invoice_id:
                    report_record = record
                    invoice = rec_inv
                    break

        if not invoice or invoice.get("status") != "paid":
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="A valid, paid invoice is required to use AI Chat.",
            )

        if not report_record or not report_record.get("report"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Report data not found for this invoice. Settle and retrieve the report first.",
            )

        report = report_record["report"]
        symbol = report.get("query_symbol") or report.get("query", {}).get("symbol") or "this asset"
        regime_cluster = report.get("regime_cluster", "Unknown")
        regime_description = report.get("regime_description", "No description available.")

        win_rate = report.get("weighted_win_rate") or report.get("rough_win_rate") or 0.0
        avg_profit = report.get("weighted_avg_profit") or report.get("rough_avg_profit") or 0.0

        ci_win = report.get("ci_win_rate_95") or [0.0, 0.0]
        ci_profit = report.get("ci_avg_profit_95") or [0.0, 0.0]

        ci_win_str = f"[{ci_win[0]:.1f}% - {ci_win[1]:.1f}%]"
        ci_profit_str = f"[{ci_profit[0]:.2f}% - {ci_profit[1]:.2f}%]"

        perc = report.get("percentiles") or {}
        p10 = perc.get("P10", 0.0)
        p50 = perc.get("P50_median", 0.0)
        worst = perc.get("worst_case_max_loss") or report.get("worst_case_max_loss") or 0.0

        is_ood = report.get("is_ood", False)
        ood_p = report.get("ood_p_value", 1.0)
        novelty_status = "High Novelty (Out-of-Distribution)" if is_ood else "Familiar Pattern (In-Distribution)"

        analogs = report.get("analogs") or report.get("top_analogs") or []
        analogs_list = ", ".join([a.get("symbol", "") for a in analogs[:4] if a.get("symbol")])
        if not analogs_list:
            analogs_list = "None"

        warnings = report.get("validation_warnings") or []
        risk_flags = report.get("risk_flags") or []

        msg_lower = user_message.lower()

        if any(k in msg_lower for k in ["risk", "loss", "drawdown", "worst", "danger", "safe", "liquidat", "warning"]):
            warnings_str = "\n".join([f"- {w}" for w in (warnings + risk_flags)])
            if not warnings_str:
                warnings_str = "- No critical statistical anomalies flagged."
            answer = f"""Regarding the risk profile for {symbol}, our backtest of the **{regime_cluster}** shows a historical worst-case maximum loss of **{worst * 100:.1f}%** (or P10 outcome of **{p10:.1f}%**) among the closest historical analogs.

Additionally, our validation pipeline flagged these diagnostics:
{warnings_str}

In this regime, anomalous negative funding rates can mean-revert violently or persist if the asset has structural sell pressure. We advise keeping position sizes conservative and using strict stop-losses. Past performance does not guarantee future results."""

        elif any(k in msg_lower for k in ["win", "rate", "percent", "probability", "chance", "profit", "earn", "return"]):
            answer = f"""The historical win rate of **{win_rate:.1f}%** is calculated across **{len(analogs)}** similar historical events, weighted by similarity score and time-decay. This indicates that situations matching {symbol}'s current parameters (funding rate, market cap, and volume) had a high frequency of positive outcomes in our backtest window.

Specifically, the 95% confidence interval for the win rate is **{ci_win_str}**, with a median outcome of **{p50:.1f}%** and an average peak profit of **{avg_profit:.2f}%** (CI: {ci_profit_str}). However, outlier outcomes are common in high-novelty situations. Past performance does not guarantee future results."""

        elif any(k in msg_lower for k in ["regime", "cluster", "context", "market", "situation", "analog", "similar"]):
            answer = f"""The asset {symbol} currently falls under the **{regime_cluster}** cluster. This regime is described as: *{regime_description}*.

The novelty check shows a p-value of **{ood_p:.5f}**, classifying this signal as a **{novelty_status}**. The closest historical analogs matched in this regime include: **{analogs_list}**. Past performance does not guarantee future results."""

        else:
            answer = f"""Here is a quantitative executive summary for the {symbol} anomaly report:
- **Market Regime:** {regime_cluster} ({novelty_status})
- **Backtest Win Rate:** {win_rate:.1f}% ({ci_win_str} 95% CI)
- **Average Peak Outcome:** {avg_profit:+.2f}% (95% CI: {ci_profit_str})
- **Top Historical Analogs:** {analogs_list}

Feel free to ask me details about:
1. What are the main **risks and warnings** for this anomaly?
2. How is the **win rate** and percentiles computed?
3. What are the **closest historical analogs** matched?

Past performance does not guarantee future results."""

        return {"answer": answer, "engine": "heuristic"}
```
- **Rationale:** Trong khi tất cả các endpoint lấy báo cáo (như `/api/v1/reports/pdf`, `/api/v1/reports/raw`) đều có tiêm `qma_access_token: Optional[str] = Security(...)`, thì `chat.py` hoàn toàn KHÔNG CÓ biến số nào để nhận và check Access Token. Nó chỉ kiểm tra xem `invoice_id` người dùng truyền lên có trạng thái `paid` trong DB hay không. Hệ quả là một Insecure Direct Object Reference (IDOR): Nếu kẻ xấu bằng cách nào đó biết được (hoặc đoán được) một `invoice_id` đã thanh toán, họ có thể dùng API này chat và trích xuất dữ liệu của báo cáo mà không cần trả tiền.
- **Severity: High (IDOR)** (Mặc dù `invoice_id` là UUID/Hash khó đoán, nhưng việc rò rỉ ID qua block explorer hoặc network logs sẽ lập tức lộ toàn bộ nội dung chat).
- **Recommendation:** Thêm tham số `qma_access_token: Optional[str] = Security(qma_access_token_header)` và gọi `deps.hydrate_access_entitlement(invoice_id, token=qma_access_token)` để buộc phải có Access Token mới được chat.

### 1.2 Xác nhận Bảo Vệ Access Token trên Route Reports
**Evidence (`reports.py:47-60`):**
```python
    @migrated.post(
        "/api/v1/providers/{provider_id}/full-report",
        tags=["Reports"],
        response_model=ProviderReportResponse,
        response_model_exclude_unset=True,
        responses=documented_errors(400, 402, 403, 404, 429, 500),
    )
    def provider_full_report(
        provider_id: str,
        query: QueryModel,
        invoice_id: str = Query(...),
        qma_access_token: Optional[str] = Security(qma_access_token_header),
        access_token: Optional[str] = Query(default=None),
    ):
```
- **Rationale:** Các route trong `reports.py` đều có tham số `qma_access_token` được lấy từ HTTP Header thông qua `Security(qma_access_token_header)`. Biến token này sau đó được truyền xuống `deps.run_paid_provider_report`. Để chứng minh token này bị bắt buộc (enforced), chúng ta trace xuống core logic:

**Evidence 1.2.1: Truyền token vào hàm `authorize_paid_invoice` (`main.py:1272-1280`)**
```python
def run_paid_provider_report(*, provider_id, query, invoice_id, token, required_tier):
...
    invoice = authorize_paid_invoice(
        query=normalized_query, invoice_id=invoice_id, token=token,
        required_tier=required_tier, provider_id=getattr(provider, "provider_id", provider_id),
    )
```

**Evidence 1.2.2: Hàm xác thực chặn token None (`payment_signing.py:161-165` và `main.py:1206-1210`)**
Trong `main.py`:
```python
def authorize_paid_invoice(*, query, invoice_id, token, required_tier, provider_id="funding_memory"):
...
    token_payload = verify_access_token(token or "")
    try:
        paid_kit.require_access(token_payload, invoice, required_tier=required_tier)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
```

Trong `payment_signing.py`:
```python
def verify_access_token(token: str) -> dict:
    try:
        return paid_kit.verify_access_token(token, secret=ACCESS_TOKEN_SECRET)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
```

- **Kết luận:** Nếu tham số `token` là `None` (do user không truyền header `X-QMA-Access-Token`), nó sẽ trở thành `""` (chuỗi rỗng). Khi đẩy vào `verify_access_token()`, nó sẽ bị bắt lỗi `ValueError` và lập tức `raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)`. Do đó, khác hoàn toàn với `chat.py`, `reports.py` **bắt buộc** phải có Access Token hợp lệ. Bằng chứng này xác nhận thiết kế của `reports.py` hoàn toàn an toàn trước lỗi IDOR.
- **Về các Legacy routes (`/api/v1/preview`, `/api/v1/analyze`):** Theo mã nguồn `reports.py`, 2 route legacy này (được đánh dấu `deprecated=True`) cũng có signature khai báo `qma_access_token: Optional[str] = Security(qma_access_token_header)` và truyền trực tiếp xuống `provider_preview_signal` / `provider_full_report`. Vì mọi logic đều hội tụ về `run_paid_provider_report` và bị `verify_access_token` chặn đứng nếu token sai/rỗng, 2 route cũ này hoàn toàn an toàn và được thừa hưởng bảo mật giống hệt các route mới.
- **Severity: Low** (Thiết kế an toàn tuyệt đối).

### 1.3 Xác nhận Quyền Sở Hữu (Ownership) trên Route Wallets
**Evidence (`wallets.py:293-314`):**
```python
    @migrated.get(
        "/api/v1/wallets/{address}/reports/{entitlement_id}",
...
    def get_wallet_report_detail(
        address: str,
        entitlement_id: str,
        qma_wallet_token: Optional[str] = Security(qma_wallet_token_header),
        wallet_token: Optional[str] = Query(default=None),
    ):
        deps.verify_wallet_profile_token(address, qma_wallet_token or wallet_token or "")
        record = deps.load_paid_report_by_id(address, entitlement_id)
        if not record:
            raise HTTPException(status_code=404, detail="Paid report snapshot not found for this wallet.")
```
- **Rationale:** Route đọc chi tiết entitlement (báo cáo đã mua) sử dụng hàm `verify_wallet_profile_token(address, token)`. Hàm này sẽ văng lỗi 403 nếu token không hợp lệ hoặc không thuộc về `address`. Tiếp đó, hàm `load_paid_report_by_id(address, entitlement_id)` tiếp tục dùng biến `address` (đã được uỷ quyền bằng token) để query trong database. Do đó, user không thể truy xuất báo cáo của user khác bằng cách truyền bừa `entitlement_id`. (Không có IDOR ở đây).
- **Severity: Low** (An toàn).

## 2. Timing Attack Prevention (Internal Secret)
**Evidence (`internal.py:20-25`):**
```python
    def require_internal_gateway_secret(x_qma_internal_secret: str = Security(qma_internal_secret_header)):
        if not deps.arc_gateway_internal_secret:
            raise HTTPException(status_code=503, detail="QMA_ARC_GATEWAY_INTERNAL_SECRET is not configured.")
        if not hmac.compare_digest(str(x_qma_internal_secret or ""), deps.arc_gateway_internal_secret):
            raise HTTPException(status_code=403, detail="Internal gateway secret required.")
        return True
```
- **Rationale:** Các hàm xử lý webhook/gateway chuyển tiền (Route: `/api/internal/...`) được bảo vệ bằng secret chia sẻ. Hàm so sánh đã sử dụng `hmac.compare_digest()` chuẩn mực, không dùng toán tử `==`. Kẻ tấn công không thể dựa vào thời gian phản hồi (Time-to-Response) của server để đoán ngược từng ký tự của Secret.
- **Severity: Low** (Được lập trình rất chuẩn).
- **Recommendation:** Giữ nguyên. 

## 3. Quản lý Quyền Admin (Admin Token Logic)
Cần xác minh xem Admin Token có thực sự bắt buộc (enforced) ở những hàm nhạy cảm hay không.

### 3.1 Cấp duyệt ứng dụng (Creator Application Review)
**Evidence (`providers.py:243-257`):**
```python
    @migrated.post("/api/v1/creators/applications/{application_id}/review", ...)
    def review_creator_application(
        application_id: str,
        req: CreatorReviewRequest,
        x_qma_admin_token: Optional[str] = Security(qma_admin_token_header),
    ):
        """Admin review endpoint for marketplace provider applications."""
        deps.require_admin_token(x_qma_admin_token)
```
- **Rationale:** Lời gọi hàm `deps.require_admin_token()` được đặt ngay dòng đầu tiên. Không có điều kiện `if` nào bao bọc. Bắt buộc 100% phải có token hợp lệ mới được thay đổi trạng thái đơn của Creator. Kẻ gian không thể tự cấp quyền Provider cho mình.
- **Severity: Low** 
- **Recommendation:** Giữ nguyên thiết kế an toàn này.

### 3.2 List Danh sách API (Bypass bằng Parameter)
**Evidence (`providers.py:73-83`):**
```python
    def list_providers(
        include_disabled: bool = Query(default=False),
        x_qma_admin_token: Optional[str] = Security(qma_admin_token_header),
    ):
        if include_disabled:
            deps.require_admin_token(x_qma_admin_token)
```
- **Rationale:** API này đóng vai trò hỗn hợp (Mixed Auth). Nếu gọi bình thường, nó là API Public (dành cho end-user xem danh sách Marketplace). Nếu admin muốn xem cả các provider bị ẩn/disabled, họ truyền `include_disabled=True`. Khi đó, code mới ép buộc (`require`) Admin Token. Thiết kế này gọn gàng và không làm lộ tài nguyên ẩn. Lối kiểm tra tương tự cũng được dùng cho `/api/v1/creators/applications` (User tự xem đơn của mình không cần admin, Admin xem toàn bộ đơn thì cần admin token).
- **Severity: Low**
- **Recommendation:** Chấp nhận thiết kế Mixed Auth vì đáp ứng tốt UX.

### 3.3 Public Config Exposure
**Evidence (`providers.py:140-147`):**
```python
    def get_admin_public_config():
        """Public hints for showing admin/seller controls in the browser."""
        return {
            "seller_wallet": deps.normalize_address(deps.payment_wallet_address),
            "admin_wallet": deps.normalize_address(deps.admin_wallet_address),
            "admin_token_required": True,
            "admin_token_configured": bool(deps.admin_token),
        }
```
- **Rationale:** API cấu hình hệ thống hoàn toàn mở. Tuy nhiên, dữ liệu trả về chỉ là địa chỉ Public Wallet của người nhận tiền và cờ bool `admin_token_configured`. Không có lộ Private Key, Secret hay Admin Token thực.
- **Severity: Low**
- **Recommendation:** Giữ nguyên.

---
**TỔNG KẾT PHASE 3**: Đa số các nhánh logic authorization của QMA được thiết kế rất tỉ mỉ, đặc biệt là cơ chế Mixed Auth và Cryptographic verification trên payload. Tuy nhiên, việc bỏ quên hoàn toàn cơ chế kiểm tra `Access Token` trên endpoint `/api/v1/chat` là một lỗi **IDOR nghiêm trọng** cần được xử lý ngay lập tức khi vào Phase fix code.
