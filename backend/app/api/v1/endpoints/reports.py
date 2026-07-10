"""Paid report endpoints."""

from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from backend.app.schemas import QueryModel

router = APIRouter(tags=["reports"])


def create_reports_router(deps: SimpleNamespace) -> APIRouter:
    migrated = APIRouter(tags=["reports"])

    @migrated.post("/api/v1/providers/{provider_id}/preview")
    def provider_preview_signal(
        provider_id: str,
        query: QueryModel,
        invoice_id: str = Query(...),
        qma_access_token: Optional[str] = Header(default=None, alias="X-QMA-Access-Token"),
        access_token: Optional[str] = Query(default=None),
    ):
        """Returns a paid provider preview for the exact query snapshot bound to the invoice."""
        try:
            return deps.run_paid_provider_report(
                provider_id=provider_id,
                query=query,
                invoice_id=invoice_id,
                token=qma_access_token or access_token,
                required_tier="preview",
            )
        except Exception as e:
            if isinstance(e, HTTPException):
                raise e
            deps.logger.error(f"Error running provider preview: {e}")
            raise HTTPException(status_code=500, detail=f"Provider preview failure: {str(e)}")

    @migrated.post("/api/v1/providers/{provider_id}/full-report")
    def provider_full_report(
        provider_id: str,
        query: QueryModel,
        invoice_id: str = Query(...),
        qma_access_token: Optional[str] = Header(default=None, alias="X-QMA-Access-Token"),
        access_token: Optional[str] = Query(default=None),
    ):
        """Returns a paid provider full report for the exact query snapshot bound to the invoice."""
        try:
            return deps.run_paid_provider_report(
                provider_id=provider_id,
                query=query,
                invoice_id=invoice_id,
                token=qma_access_token or access_token,
                required_tier="full",
            )
        except Exception as e:
            if isinstance(e, HTTPException):
                raise e
            deps.logger.error(f"Error running provider full report: {e}")
            raise HTTPException(status_code=500, detail=f"Provider full report failure: {str(e)}")

    @migrated.post("/api/v1/preview")
    def preview_signal(
        query: QueryModel,
        invoice_id: str = Query(...),
        qma_access_token: Optional[str] = Header(default=None, alias="X-QMA-Access-Token"),
        access_token: Optional[str] = Query(default=None),
    ):
        """Backward-compatible Funding Memory preview endpoint."""
        return provider_preview_signal(
            provider_id="funding_memory",
            query=query,
            invoice_id=invoice_id,
            qma_access_token=qma_access_token,
            access_token=access_token,
        )

    @migrated.post("/api/v1/analyze")
    def analyze_signal(
        query: QueryModel,
        invoice_id: str = Query(...),
        qma_access_token: Optional[str] = Header(default=None, alias="X-QMA-Access-Token"),
        access_token: Optional[str] = Query(default=None),
    ):
        """Backward-compatible Funding Memory full report endpoint."""
        return provider_full_report(
            provider_id="funding_memory",
            query=query,
            invoice_id=invoice_id,
            qma_access_token=qma_access_token,
            access_token=access_token,
        )

    return migrated
