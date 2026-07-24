# 02. Payment Lifecycle Review

Báo cáo này phân tích vòng đời thanh toán và các cơ chế chống gian lận/lỗi hệ thống (fraud & race condition) trên kiến trúc QMA x402.

## 1. Settlement Validation (Chống Fake Payment)
Các logic chủ chốt nằm trong `backend/app/services/settlement_validation.py` và caller tại `main.py`.

### 1.1 Xác thực Nguồn Dữ Liệu Thanh Toán (Data Origin Validation)
**Evidence (`main.py:937-977` - Nhánh xử lý Split Leg Payment mới):**
```python
937:             has_authoritative_gateway_claims = bool(submitted.payer_address and submitted.gateway_status)
938:             receipt_valid = verify_split_receipt(
939:                 invoice_id=invoice_id, leg_id=leg_id, pay_to=leg.get("pay_to"),
940:                 settled_amount_raw=submitted.amount_raw, settlement_id=submitted.settlement_id,
941:                 receipt=submitted.sidecar_receipt,
942:                 payer_address=submitted.payer_address,
943:                 gateway_status=submitted.gateway_status,
944:             ) if has_authoritative_gateway_claims else verify_split_receipt(
945:                 invoice_id=invoice_id, leg_id=leg_id, pay_to=leg.get("pay_to"),
946:                 settled_amount_raw=submitted.amount_raw, settlement_id=submitted.settlement_id,
947:                 receipt=submitted.sidecar_receipt,
948:             )
949:             if not receipt_valid and has_authoritative_gateway_claims:
950:                 # A legacy relay may include payer/status in its body while
951:                 # still returning a five-field receipt. Keep it on the
952:                 # authoritative Circle-lookup path instead of rejecting it.
953:                 has_authoritative_gateway_claims = False
954:                 receipt_valid = verify_split_receipt(
955:                     invoice_id=invoice_id, leg_id=leg_id, pay_to=leg.get("pay_to"),
956:                     settled_amount_raw=submitted.amount_raw, settlement_id=submitted.settlement_id,
957:                     receipt=submitted.sidecar_receipt,
958:                 )
959:             if not receipt_valid:
960:                 raise HTTPException(status_code=400, detail=f"Invalid sidecar receipt for split leg {leg_id}.")
...
963:             if has_authoritative_gateway_claims:
964:                 # Arc Gateway already fetched and validated this settlement
965:                 # against Circle before signing the sidecar receipt. The HMAC
966:                 # binds payer and status, so avoid repeating the remote GET.
967:                 settlement = {
968:                     "status": submitted.gateway_status,
969:                     "toAddress": leg.get("pay_to"),
970:                     "fromAddress": submitted.payer_address,
971:                     "amount": submitted.amount_raw,
972:                 }
973:             else:
974:                 # Compatibility path for receipts issued before payer/status
975:                 # were included in the signed sidecar proof.
976:                 settlement = fetch_circle_settlement(submitted.settlement_id)
977:             validate_arc_split_leg_payment(invoice, leg, settlement, payer_address=proof.payer_address)
```

**Evidence (`main.py:1053-1054` - Nhánh xử lý Non-Split Legacy):**
```python
1053:         settlement = fetch_circle_settlement(proof.settlement_id)
1054:         validate_arc_payment(invoice, settlement, payer_address=proof.payer_address)
```

- **Rationale:** 
  - Tại dòng 937, `has_authoritative_gateway_claims` lấy giá trị trực tiếp từ request payload (`submitted`).
  - Tuy nhiên, trước khi biến `settlement` được khởi tạo tại dòng 967, toàn bộ payload phải vượt qua hàm `verify_split_receipt()`. 
  - **Dòng 949-958 làm gì?** Có 1 đoạn fallback xử lý cho trường hợp Client/Relay gửi đủ 7 trường lên (cờ = `True`) nhưng lại chỉ ký HMAC bằng 5 trường (chữ ký legacy). Khi đó `receipt_valid` fail ở lần check đầu tiên (dòng 938). Code ở dòng 949 sẽ tự động set cờ về `False` và gọi check HMAC 5 trường một lần nữa.
  - **Fallback này có bị lợi dụng để bypass không?** KHÔNG. Dù nó ghi đè lại kết quả `receipt_valid`, nó VẪN bắt buộc phải thoả mãn logic check HMAC legacy 5 trường (dòng 954). Quan trọng nhất là nó đã giáng cấp cờ `has_authoritative_gateway_claims = False` (dòng 953). Do cờ đã bị giáng cấp, ở dòng 963 nó sẽ chạy vào nhánh `else` (dòng 973) và bắt buộc gọi thẳng `fetch_circle_settlement()` từ Gateway API server thay vì tin tưởng `submitted.gateway_status`. Mọi con đường đều dẫn tới việc xác thực an toàn tuyệt đối.
  - **Khi nào code chạy vào nhánh `else` (dòng 944)?** Nhánh này thực thi khi client payload thiếu `payer_address` hoặc `gateway_status` ngay từ đầu. Payload vẫn BẮT BUỘC phải được ký HMAC đúng chuẩn legacy. Nếu hợp lệ, hệ thống xuống dòng 976 và tự chủ động gọi API an toàn.
  - Với các receipt mới, hàm gọi HMAC với đủ 7 trường. Nếu kẻ tấn công thay đổi flag `submitted.gateway_status` thành `completed`, HMAC verification sẽ thất bại và bị block ở dòng 960.
- **Severity: Low** (Thiết kế luồng an toàn).
- **Recommendation:** Luồng thiết kế hiện tại rất chặt chẽ vì sử dụng chữ ký HMAC để uỷ quyền (trust delegation) giảm thiểu số lượng HTTP request. Giữ nguyên kiến trúc này.


### 1.2 Xác thực Currency & Gateway Support
**Evidence (`settlement_validation.py:15-21`):**
```python
    settlement_meta = invoice.get("settlement") or {}
    settlement_currency = settlement_meta.get("currency", "USDC")
    if settlement_currency != "USDC" or settlement_meta.get("gateway_supported") is False:
        raise HTTPException(
            status_code=400,
            detail=f"{settlement_currency} settlement is not enabled for Circle Gateway runtime.",
        )
```
- **Rationale:** Dữ liệu `invoice.get("settlement")` không phải payload client. Nó được sinh ra từ `hydrate_payment_schema()` (`invoice_builder.py:75`) sử dụng biến môi trường nội bộ. Do đó, logic block non-USDC này là "tĩnh cấu hình" và hoàn toàn đáng tin cậy. Kẻ gian không thể inject currency="ETH" qua API.
- **Severity: Low**
- **Recommendation:** Giữ nguyên.

### 1.3 Xác thực Trạng Thái Giao Dịch
**Evidence (`settlement_validation.py:66-73`):**
```python
    if REQUIRE_COMPLETED_SETTLEMENT:
        accepted_statuses = {"completed", "confirmed"}
        rejected_msg = f"Strict mode: settlement status is '{settlement.get('status')}'."
    else:
        accepted_statuses = {"received", "batched", "completed", "confirmed"}
        rejected_msg = f"Settlement status is '{settlement.get('status')}'; payment has not been accepted by Circle yet."
    if settlement.get("status") not in accepted_statuses:
        raise HTTPException(status_code=402, detail=rejected_msg)
```
- **Rationale:** Việc chấp nhận `received` và `batched` mang lại rủi ro off-chain: gateway có thể gỡ batch và báo `failed` sau khi hệ thống đã cấp quyền. QMA chấp nhận rủi ro này để có "fast-finality". Hàm `invoice_has_failed_settlement` sau đó sẽ đưa hoá đơn về `disputed`.
- **Severity: Low (Accepted Risk)**
- **Recommendation:** Đảm bảo cronjob đồng bộ trạng thái (sync_split_payment_events) hoạt động tốt để xử lý các thanh toán disputed bị revert kịp thời.

## 2. Token & Receipt Signing (Chống Giả Mạo)
### 2.1 Split Receipt Verification
**Evidence (`payment_signing.py:114-125`):**
```python
    if payer_address is not None and gateway_status is not None:
        fields.extend([
            normalize_address(payer_address),
            str(gateway_status).strip().lower(),
        ])
        if buyer_wallet_address is not None:
            fields.append(normalize_address(buyer_wallet_address))
    payload = split_hmac_payload(fields)
    return hmac.new(SPLIT_RECEIPT_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
```
- **Rationale:** Kẻ tấn công có thể thay đổi biên giới các tham số nếu mảng nối bằng `/` (HMAC canonicalization attack). Tuy nhiên, các giá trị hex address, số nguyên (amount) và từ khoá enum (status) có format giới hạn ngặt nghèo, không chứa `/`. Hàm `compare_digest` chống Timing Attack.
- **Severity: Low**
- **Recommendation:** Không thay đổi format. Nếu có thêm trường open text (như memo) trong tương lai, cần escape ký tự delimiter cẩn thận.

## 3. Split Leg Reserve/Record Lifecycle (Chống Race Condition)
### 3.1 Double Claim Prevention (Chống sử dụng lại mã thanh toán)
**Evidence (`invoice_builder.py:182-189`):**
```python
    for other_id, other_invoice in (all_invoices or {}).items():
        if other_id == exclude_invoice_id:
            continue
        if other_invoice.get("settlement_id") == settlement_id:
            return True
        for leg in (other_invoice.get("split") or {}).get("legs") or []:
            if leg.get("settlement_id") == settlement_id:
                return True
```
- **Rationale:** Quét O(N) toàn bộ dict `all_invoices` in-memory. Security không bị đe doạ do receipt đã bị ràng buộc HMAC với `invoice_id`/`leg_id`. Kẻ tấn công không thể claim chéo invoice. Nhưng ở scale lớn, event loop Python sẽ bị block do độ trễ tìm kiếm.
- **Severity: Medium (Performance/Scalability Risk)**
- **Recommendation:** Khi chuyển sang hệ thống lưu trữ bền vững (SQL/Redis), thay thế quét O(N) bằng database index (`UNIQUE` constraint trên `settlement_id`).

### 3.2 Khóa Cục Bộ (Cross-Process Lock)
**Evidence (`core/state.py:68-101`):**
```python
class cross_process_lock:
    def __init__(self, key: str, timeout_seconds: float = 15.0):
        safe_key = "".join(c if c.isalnum() or c in "-_:." else "_" for c in key)
        self._path = os.path.join(_LOCK_DIR, f"{safe_key}.lock")
        self._timeout = timeout_seconds
        self._fh = None

    def __enter__(self):
        if not _FLOCK_AVAILABLE:
            return self
        os.makedirs(_LOCK_DIR, exist_ok=True)
        self._fh = open(self._path, "a+")
        deadline = time.time() + self._timeout
        while True:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.time() > deadline:
                    self._fh.close()
                    self._fh = None
                    raise HTTPException(status_code=409, detail="Another settlement verification...")
                time.sleep(0.05)
```
- **Rationale:** Việc kiểm tra mã nguồn cho thấy `cross_process_lock` được thiết kế bằng khóa cấp hệ điều hành (OS-level advisory lock) sử dụng `fcntl.flock` trên file cục bộ tại thư mục `/tmp/qma-locks`. Giải pháp này hoàn toàn an toàn khi chạy trên 1 server duy nhất. Tuy nhiên, nếu ứng dụng được scale theo chiều ngang (ví dụ: nhiều pod trên Kubernetes) mà không có ổ đĩa chia sẻ chung, cơ chế khóa này sẽ vô dụng và dẫn tới race condition (cho phép Double Claim).
- **Severity: High (Rủi ro mở rộng phân tán)**
- **Recommendation:** Cần chuyển đổi cơ chế khóa từ `fcntl.flock` sang khóa phân tán (Distributed Lock) như Redis (sử dụng Redlock) khi triển khai hệ thống lên kiến trúc Multi-node/Kubernetes.

## 4. Invoice Integrity (Split Allocation & Wallet Routing)
**Evidence (`invoice_builder.py:86-94`):**
```python
def allocate_split_legs_raw(total_raw: int, creator_bps: int, platform_bps: int) -> dict:
    weights = [max(0, int(creator_bps)), max(0, int(platform_bps))]
    if sum(weights) != 10000:
        raise HTTPException(status_code=400, detail="Creator/platform split must total 10000 bps.")
    if total_raw <= 0:
        raise HTTPException(status_code=400, detail="Invoice amount must be greater than 0.")
    ideals = [(total_raw * weight) / 10000 for weight in weights]
    floors = [int(value) for value in ideals]
    leftover = total_raw - sum(floors)
```
- **Rationale:** Thuật toán Largest-Remainder ngăn chặn float drift và thiếu hụt USDC. `provider_revenue_wallet_for_build` đảm bảo tiền luôn có đích đến hợp lệ.
- **Severity: Low**
- **Recommendation:** Thuật toán rất chuẩn mực, giữ nguyên.

## 5. Entitlement Logic (Phân Quyền Truy Cập)
**Evidence (`invoice_builder.py:257-271`):**
```python
    access_status = invoice_access_status(invoice)
    access_token = None
    if access_status in {"settlement_confirmed", "access_issued_pending_batch"}:
        access_token = sign_access_token(
            invoice_id=invoice_id,
            provider_id=invoice.get("provider_id"),
            tier=invoice.get("tier"),
            buyer_wallet_address=invoice.get("buyer_wallet_address"),
            payer_address=invoice.get("payer_address"),
            expires_at=time.time() + ACCESS_TOKEN_TTL_SECONDS,
        )
```
- **Rationale:** Chỉ cấp khi `invoice_access_status` hợp lệ. Token gắn kèm với `invoice_id`, `provider_id` và `payer_address`. Kẻ tấn công không thể dùng token này cho report đắt hơn.
- **Severity: Low**
- **Recommendation:** Luồng này đủ an toàn để phân quyền theo session.

## 6. Operational Risks (Lỗi Hệ Thống & Gateway Outage)
**Evidence (`x402_gateway.py:7-16`):**
```python
def fetch_circle_settlement(settlement_id: str, *, gateway_api: str) -> dict:
    try:
        resp = requests.get(f"{gateway_api}/v1/x402/transfers/{settlement_id}", timeout=10)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Circle Gateway lookup failed: {exc}")
```
- **Rationale:** Hàm `fetch_circle_settlement` gọi Gateway và timeout ở 10 giây nhưng không có Retry cục bộ.
- **Severity: Low (UX Risk)**
- **Recommendation:** Nếu xảy ra timeout mạng tạm thời, có thể bổ sung thư viện `tenacity` để retry 1-2 lần trước khi throw HTTP 502, tránh bắt client phải thủ công thử lại.

---
**TỔNG KẾT PHASE 2**: Quá trình khởi tạo, chia tiền (Largest-Remainder), và xác minh thanh toán được cài đặt rất vững chắc bằng cơ chế HMAC validation xen kẽ, đảm bảo không thể bypass gateway. Lỗ hổng O(N) Double Claim là rủi ro mở rộng chính, có thể giải quyết khi chuyển sang Database SQL/Redis.
