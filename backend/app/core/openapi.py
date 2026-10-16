"""QMA OpenAPI 3.1.0 and Audience Documentation Generator.

Extracts OpenAPI customization, bazaar extensions, audience-specific filtering,
and Scalar documentation routes out of the main application entrypoint.
"""

import copy
from typing import Dict, List, Set
from fastapi import FastAPI, HTTPException
from scalar_fastapi import get_scalar_api_reference

from backend.app.core.x402_spec import AGENT_GUIDANCE, BAZAAR_EXTENSIONS, X_PAYMENT_INFO


AUDIENCE_TAGS: Dict[str, Set[str]] = {
    "agent": {"Agent decisioning", "Agent sessions", "MCP", "Market data", "Provider discovery", "Payments & settlement", "Reports", "System"},
    "wallet": {"Agent sessions", "Wallet & entitlements", "Traction & analytics", "System", "Payments & settlement", "Creator operations", "Report chat", "Reports"},
    "admin": {"Admin / operations", "Provider discovery", "Traction & analytics", "System", "Internal gateway", "Payments & settlement"},
}

DOCUMENTATION_AUDIENCES: Set[str] = {"public", "agent", "wallet", "admin", "private"}

SIGNED_PAYLOAD_OPERATIONS = {
    ("post", "/api/v1/creators/claim"),
    ("post", "/api/v1/payment/withdraw"),
    ("post", "/api/v1/wallets/{address}/session"),
}


def _operation_access(path: str, method: str, operation: dict) -> str:
    if (method, path) in SIGNED_PAYLOAD_OPERATIONS:
        return "signed-payload"

    requirements = operation.get("security") or []
    if not requirements:
        return "public"
    if {} in requirements:
        return "public-optional-auth"

    schemes = {
        scheme
        for requirement in requirements
        if isinstance(requirement, dict)
        for scheme in requirement
    }
    if schemes == {"X-QMA-Access-Token"}:
        return "paid-access"
    if schemes == {"X-QMA-Wallet-Token"}:
        return "wallet-owner"
    if schemes == {"X-QMA-Invoice-Secret"}:
        return "invoice-owner"
    if schemes == {"x-qma-admin-token"}:
        return "admin"
    if schemes == {"x-qma-internal-secret"}:
        return "internal-worker"
    if schemes == {"X-QMA-Wallet-Token", "x-qma-internal-secret"}:
        return "wallet-or-worker"
    return "protected"


def _operation_audiences(path: str, method: str, operation: dict, access: str) -> list[str]:
    tags = set(operation.get("tags") or [])
    audiences = {
        audience
        for audience, allowed_tags in AUDIENCE_TAGS.items()
        if tags.intersection(allowed_tags)
    }
    if access == "internal-worker":
        audiences.discard("wallet")
    audiences.add("public" if access in {"public", "public-optional-auth"} else "private")
    return sorted(audiences)


def generate_qma_openapi(app: FastAPI, default_openapi_fn) -> dict:
    """Add optional-auth semantics, OpenAPI 3.1.0 metadata, and x402 payment specifications."""
    if app.openapi_schema:
        return app.openapi_schema

    schema = default_openapi_fn()
    schema["openapi"] = "3.1.0"
    info = schema.setdefault("info", {})
    info["contact"] = {
        "name": "QMA Agent Support",
        "email": "agent-support@qma.com",
        "url": "https://qma-three.vercel.app/",
    }
    info["x-guidance"] = AGENT_GUIDANCE
    info["x-capabilities"] = [
        "dualRail",
        "circleGateway",
        "proofOfHuman",
        "siwx",
        "multiChain",
        "bazaarSchema",
    ]
    info["x-payment-rails"] = ["x402", "mpp"]
    schema["externalDocs"] = {
        "description": "QMA Documentation and Agent Integration Guide",
        "url": "https://qma-three.vercel.app/docs",
    }

    components = schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes.setdefault(
        "x-qma-internal-secret",
        {
            "type": "apiKey",
            "in": "header",
            "name": "x-qma-internal-secret",
            "description": "Internal gateway secret. Internal routes are intentionally hidden from the public schema.",
        },
    )
    security_schemes.setdefault(
        "walletAuth",
        {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "SIWE",
            "description": "Wallet authentication via EIP-4361 (Sign-In with Ethereum). Authenticate using verified wallet session token in Authorization: Bearer <token> or X-QMA-Wallet-Token header.",
        },
    )
    security_schemes.setdefault(
        "x402",
        {
            "type": "apiKey",
            "in": "header",
            "name": "X-PAYMENT",
            "description": "x402 v2 payment authorization header (or PAYMENT-SIGNATURE) providing signed exact USDC transfer intent on supported multi-chain networks.",
        },
    )

    optional_security = {
        "/api/v1/metrics/wallet/{address}": "X-QMA-Wallet-Token",
        "/api/v1/wallets/{address}/payments": "X-QMA-Wallet-Token",
        "/api/v1/entitlements/wallet/{address}": "X-QMA-Wallet-Token",
        "/api/v1/providers": "x-qma-admin-token",
        "/api/v1/providers/{provider_id}": "x-qma-admin-token",
        "/api/v1/providers/{provider_id}/stats": "x-qma-admin-token",
        "/api/v1/creators/applications": "x-qma-admin-token",
        "/api/v1/treasury/agent/decide": "x-qma-admin-token",
        "/api/v1/treasury/usyc/sweep": "x-qma-admin-token",
        "/api/v1/treasury/usyc/jit-redeem": "x-qma-admin-token",
    }
    for path in optional_security:
        for operation in schema.get("paths", {}).get(path, {}).values():
            if not isinstance(operation, dict) or "security" not in operation:
                continue
            requirements = operation["security"]
            if {} not in requirements:
                requirements.append({})

    for path, path_item in schema.get("paths", {}).items():
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "delete", "patch", "options", "head", "trace"}:
                continue
            access = _operation_access(path, method, operation)
            operation["x-qma-access"] = access
            operation["x-qma-audiences"] = _operation_audiences(path, method, operation, access)
            if access == "paid-access":
                operation["x-payment-info"] = X_PAYMENT_INFO
                operation["x-capabilities"] = [
                    "dualRail",
                    "circleGateway",
                    "proofOfHuman",
                    "siwx",
                    "multiChain",
                    "bazaarSchema",
                ]
                responses = operation.setdefault("responses", {})
                responses["402"] = {
                    "description": "Payment Required. Returns an x402 challenge with accepts[] containing supported multi-chain networks and Bazaar schema.",
                    "headers": {
                        "PAYMENT-REQUIRED": {
                            "description": "Base64-encoded x402 payment challenge JSON with multi-network accepts[] array and Bazaar schema",
                            "schema": {"type": "string"},
                        },
                        "WWW-Authenticate": {
                            "description": "Payment challenge realm, requirements, and supported schemes",
                            "schema": {"type": "string"},
                        },
                    },
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                            "example": {
                                "error": "payment_required",
                                "message": "Payment required: $0.005000 USDC over x402 / Circle Gateway to access report.",
                                "status_code": 402,
                                "price": {
                                    "mode": "fixed",
                                    "currency": "USDC",
                                    "amount": "0.005000",
                                },
                                "x402Version": 2,
                                "protocols": X_PAYMENT_INFO.get("protocols", []),
                                "rails": ["x402", "mpp"],
                                "dualRail": True,
                                "multiChain": True,
                                "auth": {
                                    "scheme": "siwx",
                                    "type": "wallet",
                                    "standards": ["EIP-4361", "CAIP-122"],
                                },
                                "proofOfHuman": {
                                    "enabled": True,
                                    "provider": "world-id",
                                },
                                "schema": BAZAAR_EXTENSIONS["bazaar"]["schema"],
                                "bazaarSchema": BAZAAR_EXTENSIONS["bazaar"]["schema"],
                                "accepts": X_PAYMENT_INFO.get("accepts", []),
                                "extensions": {
                                    **BAZAAR_EXTENSIONS,
                                    "siwx": {"enabled": True, "standards": ["EIP-4361", "CAIP-122"]},
                                    "proofOfHuman": {"enabled": True, "provider": "world-id"},
                                },
                            },
                        }
                    },
                }

    app.openapi_schema = schema
    return schema
