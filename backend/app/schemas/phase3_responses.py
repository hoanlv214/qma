"""Response models for the remaining public API groups.

Provider report payloads, provider metadata, and analytics rows intentionally
remain extensible: built-in providers and persisted records can add fields
without changing the public endpoint envelope.
"""

from typing import Any, Dict, List, Optional
from pydantic import Field

from backend.app.schemas.health_responses import GatewayBalanceResponse
from backend.app.schemas.response_base import ResponseModel
from backend.app.schemas.wallet_responses import Page, PayerBreakdownItem, PaymentEventItem


class LiveAnomaliesResponse(ResponseModel):
    last_updated: float
    count: int
    anomalies: List[Dict[str, Any]]


class AgentRecommendationItem(ResponseModel):
    provider_id: str
    provider_name: str
    provider_category: str
    symbol: str
    score: float
    suggested_tier: str
    suggested_price_usdc: float
    complexity_score: float
    estimated_value: str
    reasons: List[str]
    query: Dict[str, Any]
    live: Dict[str, Any]


class AgentRecommendationsResponse(ResponseModel):
    mode: str
    provider_strategy: str
    pricing: Dict[str, Any]
    last_updated: float
    recommendations: List[AgentRecommendationItem]


class ProviderReportResponse(ResponseModel):
    """Paid report envelope with extensible provider-specific report fields."""

    query_symbol: Optional[str] = None
    query: Optional[Dict[str, Any]] = None
    query_hash: Optional[str] = None
    tier: Optional[str] = None
    funding_context: Optional[Dict[str, Any]] = None
    regime_cluster: Optional[str] = None
    regime_description: Optional[str] = None
    is_ood: Optional[bool] = None
    ood_p_value: Optional[float] = None
    win_rate_band: Optional[str] = None
    rough_win_rate: Optional[float] = None
    top_analogs: Optional[List[Dict[str, Any]]] = None
    upgrade_cta: Optional[str] = None
    invoice: Optional[Dict[str, Any]] = None
    provider_note: Optional[str] = None
    analysis_focus: Optional[str] = None
    turnover_context: Optional[Dict[str, Any]] = None
    provider_diagnostics: Optional[Dict[str, Any]] = None
    provider_specific_data: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Provider-specific report data that may vary by provider. "
            "Built-in providers can expose additional fields beyond the "
            "common QMA report envelope."
        ),
    )
    provider_id: Optional[str] = None
    provider_name: Optional[str] = None
    provider_owner_wallet: Optional[str] = None
    paid_at: Optional[float] = None


class ProviderListResponse(ResponseModel):
    providers: List[Dict[str, Any]]


class ProviderDetailResponse(ResponseModel):
    provider: Dict[str, Any]


class ProviderStatsResponse(ResponseModel):
    stats: Dict[str, Any]


class AdminPublicConfigResponse(ResponseModel):
    seller_wallet: str
    admin_wallet: str
    admin_token_required: bool
    admin_token_configured: bool


class ProviderApplicationResponse(ResponseModel):
    message: Optional[str] = None
    application: Dict[str, Any]


class CreatorApplicationsResponse(ResponseModel):
    count: int
    applications: List[Dict[str, Any]]


class CreatorClaimResponse(ResponseModel):
    claim: Dict[str, Any]
    message: str


class PlatformSummaryResponse(ResponseModel):
    seller_address: str
    seller_gateway_balance: Optional[GatewayBalanceResponse] = None
    invoice_count: int
    paid_count: int
    current_paid_count: int
    legacy_paid_count: int
    unique_payers: int
    current_unique_payers: Optional[int] = None
    revenue_usdc: float
    current_revenue_usdc: float
    legacy_revenue_usdc: float
    tier_counts: Dict[str, int]
    buyer_type_counts: Dict[str, int]
    current_buyer_type_counts: Optional[Dict[str, int]] = None
    legacy_buyer_type_counts: Optional[Dict[str, int]] = None
    revenue_by_tier: Dict[str, float]
    revenue_by_provider: List[Dict[str, Any]]
    top_symbols: List[Dict[str, Any]]
    last_payment_key: Optional[str] = None
    last_paid_at: Optional[float] = None


class PlatformMetricsResponse(PlatformSummaryResponse):
    payer_breakdown: List["PayerBreakdownItem"]
    payer_breakdown_page: Page["PayerBreakdownItem"]
    recent_payments: List[Dict[str, Any]] = Field(
        description=(
            "Raw payment event (superset of PaymentEventItem) with internal "
            "fields such as query, resource_type, seller_address, amount_raw, "
            "pricing, settlement, accounting, synthetic, agent_label, "
            "run_source, and split_leg. Use PaymentEventItem for the compact "
            "shape returned by the other payment routes."
        )
    )
    recent_payments_page: Page[Dict[str, Any]]


class PlatformPaymentsResponse(ResponseModel):
    recent_payments: List["PaymentEventItem"]
    recent_payments_page: Page["PaymentEventItem"]


class PlatformPayersResponse(ResponseModel):
    payer_breakdown: List["PayerBreakdownItem"]
    payer_breakdown_page: Page["PayerBreakdownItem"]


class ChatResponse(ResponseModel):
    answer: str
    engine: str


class AgentPlanResponse(ResponseModel):
    action: str
    candidate_id: Optional[str] = None
    requested_tier: str
    budget_usdc: float
    max_price_usdc: float
    reason: str
    rejected_candidate_ids: List[str]


class AgentValidationResponse(ResponseModel):
    valid: bool
    errors: List[Any]
    warnings: List[Any]


class AgentDecisionResponse(ResponseModel):
    plan: AgentPlanResponse
    validation: AgentValidationResponse
    resolved_candidate: Optional[Dict[str, Any]] = None
    canonical_query: Optional[Dict[str, Any]] = None
    policy_check: Dict[str, Any]
    rejected_candidates: List[Dict[str, Any]]
    evaluated_candidates: List[Dict[str, Any]]
    selection_basis: Dict[str, Any]
    candidate_count: int
    decision_source: str
