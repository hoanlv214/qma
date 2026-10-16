import time
import pytest
from fastapi.testclient import TestClient
from backend.app.core.rate_limit import rate_limit_for_path
import backend.app.main as app_module
from backend.app.core import config, state


def test_rate_limit_for_path_heavy_endpoints():
    """Verify newly protected heavy endpoints have dedicated scopes and sensible limits."""
    scope, limit = rate_limit_for_path("/api/v1/treasury/agent/decide")
    assert scope == "treasury_agent"
    assert limit == 15

    scope, limit = rate_limit_for_path("/api/v1/treasury/audit/verify")
    assert scope == "treasury_audit"
    assert limit == 12

    scope, limit = rate_limit_for_path("/api/v1/treasury/spend-intent")
    assert scope == "treasury_spend"
    assert limit == 20

    scope, limit = rate_limit_for_path("/api/v1/swap/quote")
    assert scope == "swap_quote"
    assert limit == 60

    scope, limit = rate_limit_for_path("/api/v1/sessions")
    assert scope == "sessions"
    assert limit == 30


def test_origin_shield_blocks_unauthorized_remote_calls(monkeypatch):
    """Verify remote requests lacking the origin shield secret are rejected with 403."""
    client = TestClient(app_module.app)

    # Enable Origin Shield Secret
    monkeypatch.setattr(app_module, "ORIGIN_SHIELD_SECRET", "super-secret-origin-token")

    # 1. Health check is always permitted for monitoring
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200

    # 2. Remote IP simulated via cf-connecting-ip or without loopback
    resp = client.get(
        "/api/v1/platform/summary",
        headers={"cf-connecting-ip": "198.51.100.24"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "origin_shield_blocked"

    # 3. Remote IP with invalid secret header
    resp = client.get(
        "/api/v1/platform/summary",
        headers={
            "cf-connecting-ip": "198.51.100.24",
            "x-qma-origin-secret": "wrong-secret",
        },
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "origin_shield_blocked"

    # 4. Remote IP with valid secret header
    resp = client.get(
        "/api/v1/platform/summary",
        headers={
            "cf-connecting-ip": "198.51.100.24",
            "x-qma-origin-secret": "super-secret-origin-token",
        },
    )
    assert resp.status_code == 200


def test_headless_scraper_blocked(monkeypatch):
    """Verify automated headless scrapers from remote IPs are rejected with 403 bot_blocked."""
    client = TestClient(app_module.app)
    monkeypatch.setattr(app_module, "ORIGIN_SHIELD_SECRET", "")

    # HeadlessChrome User-Agent from remote IP
    resp = client.get(
        "/api/v1/platform/summary",
        headers={
            "cf-connecting-ip": "54.183.149.156",
            "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/141.0.7390.54 Safari/537.36",
        },
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "bot_blocked"

    # HeadlessChrome Sec-Ch-Ua header
    resp = client.get(
        "/api/v1/platform/summary",
        headers={
            "cf-connecting-ip": "54.183.149.156",
            "sec-ch-ua": '"HeadlessChrome";v="141"',
        },
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "bot_blocked"


def test_public_tunnel_direct_access_blocked_without_proxy_or_auth(monkeypatch):
    """Verify direct calls to ngrok/tunnel domains are rejected unless routed through Vercel or authenticated."""
    client = TestClient(app_module.app)
    monkeypatch.setattr(app_module, "ORIGIN_SHIELD_SECRET", "")

    # 1. Direct call to ngrok host without Vercel header or auth
    resp = client.get(
        "/api/v1/platform/summary",
        headers={
            "cf-connecting-ip": "54.183.149.156",
            "host": "driveway-expansive-onyx.ngrok-free.dev",
            "user-agent": "Mozilla/5.0",
        },
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "direct_tunnel_access_forbidden"

    # 2. Ngrok call with Vercel proxy header (x-vercel-id)
    resp = client.get(
        "/api/v1/platform/summary",
        headers={
            "cf-connecting-ip": "118.70.52.15",
            "host": "driveway-expansive-onyx.ngrok-free.dev",
            "x-vercel-id": "hkg1::iad1::v4lsw-1760513904992-0b73c4481b49",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        },
    )
    assert resp.status_code == 200

    # 3. Ngrok call with Authorization header (e.g. Agent CLI or API client)
    resp = client.get(
        "/api/v1/platform/summary",
        headers={
            "cf-connecting-ip": "54.183.149.156",
            "host": "driveway-expansive-onyx.ngrok-free.dev",
            "authorization": "Bearer test-token",
            "user-agent": "QMA-Agent-Client/1.0",
        },
    )
    assert resp.status_code == 200


def test_origin_shield_cannot_be_bypassed_by_spoofed_vercel_id(monkeypatch):
    """Verify that when ORIGIN_SHIELD_SECRET is enabled, callers cannot bypass it using spoofed x-vercel-id."""
    client = TestClient(app_module.app)
    monkeypatch.setattr(app_module, "ORIGIN_SHIELD_SECRET", "super-secret-origin-token")

    resp = client.get(
        "/api/v1/platform/summary",
        headers={
            "cf-connecting-ip": "198.51.100.24",
            "host": "driveway-expansive-onyx.ngrok-free.dev",
            "x-vercel-id": "hkg1::iad1::spoofed-id-12345",
            "user-agent": "Mozilla/5.0",
        },
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "origin_shield_blocked"


def test_rate_limit_memory_bounded_under_ip_explosion(monkeypatch):
    """Verify that rate limiter memory stays strictly bounded even under high-cardinality IP scans."""
    from collections import deque
    client = TestClient(app_module.app)
    monkeypatch.setattr(app_module, "RATE_LIMIT_ENABLED", True)

    # Pre-seed 2500 active IP buckets
    now = time.time()
    for i in range(2500):
        app_module.state.rate_limit_buckets[f"public:10.0.{i // 256}.{i % 256}"] = deque([now])

    assert len(app_module.state.rate_limit_buckets) >= 2500

    resp = client.get(
        "/api/v1/platform/summary",
        headers={"cf-connecting-ip": "10.10.10.10", "user-agent": "SafeAgent/1.0"},
    )
    assert resp.status_code == 200
    # Must be pruned down to the hard bound of 2000
    assert len(app_module.state.rate_limit_buckets) <= 2000


