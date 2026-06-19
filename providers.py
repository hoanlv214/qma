import os
from abc import ABC, abstractmethod
from typing import Dict, Optional

try:
    import paid_intelligence_kit as paid_kit
except ImportError:
    from qma import paid_intelligence_kit as paid_kit

try:
    from qma_engine import QMAEngine
except ImportError:
    from qma.qma_engine import QMAEngine


class IntelligenceProvider(ABC):
    provider_id: str
    provider_name: str
    description: str
    owner_wallet: str

    def __init__(self, *, owner_wallet: str):
        self.owner_wallet = owner_wallet

    def get_pricing(self) -> dict:
        return {
            tier: {
                "label": meta["label"],
                "amount_usdc": paid_kit.tier_price(tier),
            }
            for tier, meta in paid_kit.SUPPORTED_TIERS.items()
        }

    @abstractmethod
    def get_input_schema(self) -> dict:
        pass

    @abstractmethod
    def get_output_schema(self) -> dict:
        pass

    @abstractmethod
    def preview(self, query: dict) -> dict:
        pass

    @abstractmethod
    def full_report(self, query: dict) -> dict:
        pass

    def metadata(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "description": self.description,
            "owner_wallet": self.owner_wallet,
            "pricing": self.get_pricing(),
            "supported_report_types": ["preview", "full"],
            "resource_types": ["qma_signal_report"],
            "input_schema": self.get_input_schema(),
            "output_schema": self.get_output_schema(),
        }


def build_preview_from_full(full_report: dict) -> dict:
    analogs = full_report.get("analogs", [])[:3]
    win_rate = float(full_report.get("weighted_win_rate") or 0)
    if win_rate >= 70:
        win_rate_band = "high"
    elif win_rate >= 50:
        win_rate_band = "medium"
    else:
        win_rate_band = "low"
    return {
        "query_symbol": full_report.get("query_symbol"),
        "query": full_report.get("query"),
        "query_hash": full_report.get("query_hash"),
        "tier": "preview",
        "funding_context": {
            "fundingRate": full_report.get("query", {}).get("fundingRate"),
            "marketCap": full_report.get("query", {}).get("marketCap"),
            "circRatio": full_report.get("query", {}).get("circRatio"),
            "fromATH": full_report.get("query", {}).get("fromATH"),
            "volume24h": full_report.get("query", {}).get("volume24h"),
        },
        "regime_cluster": full_report.get("regime_cluster"),
        "regime_description": full_report.get("regime_description"),
        "is_ood": full_report.get("is_ood"),
        "ood_p_value": full_report.get("ood_p_value"),
        "win_rate_band": win_rate_band,
        "rough_win_rate": round(win_rate, 1),
        "top_analogs": [
            {
                "symbol": item.get("symbol"),
                "fundingRate": item.get("fundingRate"),
                "similarity": item.get("similarity"),
                "profit_pct": item.get("profit_pct"),
            }
            for item in analogs
        ],
        "upgrade_cta": "Upgrade to the full report for all analogs, weighted percentiles, confidence intervals, and evidence diagnostics.",
        "invoice": full_report.get("invoice"),
    }


class FundingMemoryProvider(IntelligenceProvider):
    provider_id = "funding_memory"
    provider_name = "Funding Memory Provider"
    description = (
        "MEXC futures funding anomaly memory. Matches a live token snapshot "
        "against historical negative-funding events and returns regime analogs."
    )

    def __init__(self, *, engine: Optional[QMAEngine] = None, owner_wallet: str):
        super().__init__(owner_wallet=owner_wallet)
        self.engine = engine or QMAEngine()

    def get_input_schema(self) -> dict:
        return {
            "type": "object",
            "required": ["symbol", "fundingRate", "marketCap", "FDV", "circRatio", "fromATH", "volume24h"],
            "properties": {
                "symbol": {"type": "string", "description": "Token symbol, for example HYPE."},
                "fundingRate": {"type": "number", "description": "Current futures funding rate as decimal."},
                "marketCap": {"type": "number"},
                "FDV": {"type": "number"},
                "circRatio": {"type": "number"},
                "fromATH": {"type": "number", "description": "Percent distance from all-time high."},
                "volume24h": {"type": "number"},
                "amount": {"type": "number", "description": "Optional turnover/open-interest proxy."},
            },
        }

    def get_output_schema(self) -> dict:
        return {
            "preview": {
                "type": "object",
                "fields": ["query_symbol", "regime_cluster", "is_ood", "win_rate_band", "top_analogs"],
            },
            "full": {
                "type": "object",
                "fields": ["weighted_win_rate", "avg_profit", "analogs", "percentiles", "diagnostics", "invoice"],
            },
        }

    def full_report(self, query: dict) -> dict:
        return self.engine.analyze_signal(query)

    def preview(self, query: dict) -> dict:
        return build_preview_from_full(self.full_report(query))


class ProviderRegistry:
    def __init__(self, providers: Dict[str, IntelligenceProvider]):
        self._providers = providers

    def list(self) -> list[dict]:
        return [provider.metadata() for provider in self._providers.values()]

    def get(self, provider_id: str) -> Optional[IntelligenceProvider]:
        return self._providers.get((provider_id or "").strip())

    def require(self, provider_id: str) -> IntelligenceProvider:
        provider = self.get(provider_id)
        if provider is None:
            raise KeyError(provider_id)
        return provider


def create_default_registry(*, engine: QMAEngine, default_owner_wallet: str) -> ProviderRegistry:
    funding_owner = os.getenv("QMA_FUNDING_MEMORY_OWNER_WALLET", default_owner_wallet)
    return ProviderRegistry({
        FundingMemoryProvider.provider_id: FundingMemoryProvider(
            engine=engine,
            owner_wallet=funding_owner,
        )
    })
