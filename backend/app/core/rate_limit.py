"""Rate-limit helpers for the QMA API."""

from fastapi import Request

from backend.app.core.static_config import app_setting


def _per_minute(bucket: str) -> int:
    """Per-minute request budget for a bucket, from config/app.json rateLimit.perMinute."""
    return int(app_setting("rateLimit", "perMinute", bucket))


def client_ip_from_request(request: Request) -> str:
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit_for_path(path: str) -> tuple[str, int]:
    if path in ("/api/v1/health", "/health", "/healthz", "/metrics"):
        return "health", 0
    if path.startswith("/api/v1/payment/verify"):
        return "payment_verify", _per_minute("paymentVerify")
    if path.startswith("/api/v1/payment/invoice"):
        return "payment_invoice", _per_minute("invoice")
    if (
        path.startswith("/api/v1/oauth/register")
        or path.startswith("/api/v1/oauth/token")
        or path in ("/register", "/oauth/register", "/token", "/oauth/token")
    ):
        return "oauth_token", _per_minute("oauth")
    if path == "/mcp" or path.startswith("/mcp/"):
        return "mcp", _per_minute("mcp")
    if path.startswith("/api/v1/providers/") and (path.endswith("/preview") or path.endswith("/full-report")):
        return "paid_report", _per_minute("report")
    if path.startswith("/api/v1/preview") or path.startswith("/api/v1/analyze"):
        return "paid_report", _per_minute("report")
    if (path.startswith("/api/v1/providers/") and path.endswith("/live-anomalies")) or path.startswith("/api/v1/agent/recommendations"):
        return "public_market", _per_minute("publicMarket")
    if path.startswith("/api/v1/creators/apply"):
        return "creator_apply", _per_minute("creatorApply")
    if path.startswith("/api/v1/treasury/agent/decide") or path.startswith("/api/v1/treasury/agent/"):
        return "treasury_agent", _per_minute("treasuryAgent")
    if path.startswith("/api/v1/treasury/audit/verify"):
        return "treasury_audit", _per_minute("auditVerify")
    if path.startswith("/api/v1/treasury/spend-intent"):
        return "treasury_spend", _per_minute("spendIntent")
    if path.startswith("/api/v1/swap/quote"):
        return "swap_quote", _per_minute("swapQuote")
    if path == "/api/v1/sessions" or path.startswith("/api/v1/sessions"):
        return "sessions", _per_minute("sessions")
    if path.startswith("/api/v1/"):
        return "api_default", _per_minute("apiDefault")
    return "html", 0

