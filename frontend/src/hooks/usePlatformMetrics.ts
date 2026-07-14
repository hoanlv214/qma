import { useState } from "react";
import { API_BASE_URL } from "../services/api";

export function usePlatformMetrics() {
  const [metrics, setMetrics] = useState({
    paid_count: 0,
    revenue_usdc: 0,
    available_usdc: 0,
  });
  const [platformSummary, setPlatformSummary] = useState<any>(null);
  const [platformPayments, setPlatformPayments] = useState<any[]>([]);
  const [platformPaymentsPage, setPlatformPaymentsPage] = useState(1);
  const [platformPaymentsTotalPages, setPlatformPaymentsTotalPages] = useState(1);
  const [platformPaymentsTotal, setPlatformPaymentsTotal] = useState(0);
  const [platformPayers, setPlatformPayers] = useState<any[]>([]);
  const [platformPayersPage, setPlatformPayersPage] = useState(1);
  const [platformPayersTotalPages, setPlatformPayersTotalPages] = useState(1);
  const [platformPayersTotal, setPlatformPayersTotal] = useState(0);
  const [platformTablesLoading, setPlatformTablesLoading] = useState(false);
  const [platformTablesError, setPlatformTablesError] = useState("");

  const loadPlatformSummary = async () => {
    const resp = await fetch(`${API_BASE_URL}/api/v1/platform/summary`);
    if (!resp.ok) throw new Error(`Platform summary returned ${resp.status}`);
    const data = await resp.json();
    setPlatformSummary(data);
    setMetrics({
      paid_count: data.current_paid_count ?? data.paid_count ?? 0,
      revenue_usdc: data.revenue_usdc || 0,
      available_usdc: data.seller_gateway_balance?.available_usdc ?? data.available_usdc ?? 0,
    });
    return data;
  };

  const loadPlatformPayments = async (page = platformPaymentsPage) => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: "10",
    });
    const resp = await fetch(`${API_BASE_URL}/api/v1/platform/payments?${params.toString()}`);
    if (!resp.ok) throw new Error(`Platform payments returned ${resp.status}`);
    const data = await resp.json();
    const rows = Array.isArray(data.recent_payments) ? data.recent_payments : [];
    const meta = data.recent_payments_page || {};
    setPlatformPayments(rows);
    setPlatformPaymentsPage(Number(meta.page || page || 1));
    setPlatformPaymentsTotalPages(Number(meta.total_pages || 1));
    setPlatformPaymentsTotal(Number(meta.total || rows.length));
    return data;
  };

  const loadPlatformPayers = async (page = platformPayersPage) => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: "10",
    });
    const resp = await fetch(`${API_BASE_URL}/api/v1/platform/payers?${params.toString()}`);
    if (!resp.ok) throw new Error(`Platform payers returned ${resp.status}`);
    const data = await resp.json();
    const rows = Array.isArray(data.payer_breakdown) ? data.payer_breakdown : [];
    const meta = data.payer_breakdown_page || {};
    setPlatformPayers(rows);
    setPlatformPayersPage(Number(meta.page || page || 1));
    setPlatformPayersTotalPages(Number(meta.total_pages || 1));
    setPlatformPayersTotal(Number(meta.total || rows.length));
    return data;
  };

  const refreshPlatformTables = async (paymentPage = platformPaymentsPage, payerPage = platformPayersPage) => {
    setPlatformTablesLoading(true);
    setPlatformTablesError("");
    try {
      await Promise.all([
        loadPlatformSummary(),
        loadPlatformPayments(paymentPage),
        loadPlatformPayers(payerPage),
      ]);
    } catch (err: any) {
      console.warn("Platform analytics unavailable", err);
      setPlatformTablesError(err?.message || "Platform analytics unavailable.");
    } finally {
      setPlatformTablesLoading(false);
    }
  };

  const changePlatformPaymentsPage = async (nextPage: number) => {
    setPlatformTablesLoading(true);
    setPlatformTablesError("");
    try {
      await loadPlatformPayments(nextPage);
    } catch (err: any) {
      setPlatformTablesError(err?.message || "Platform payments unavailable.");
    } finally {
      setPlatformTablesLoading(false);
    }
  };

  const changePlatformPayersPage = async (nextPage: number) => {
    setPlatformTablesLoading(true);
    setPlatformTablesError("");
    try {
      await loadPlatformPayers(nextPage);
    } catch (err: any) {
      setPlatformTablesError(err?.message || "Platform payers unavailable.");
    } finally {
      setPlatformTablesLoading(false);
    }
  };

  return {
    metrics,
    platformSummary,
    platformPayments,
    platformPaymentsPage,
    platformPaymentsTotalPages,
    platformPaymentsTotal,
    platformPayers,
    platformPayersPage,
    platformPayersTotalPages,
    platformPayersTotal,
    platformTablesLoading,
    platformTablesError,
    loadPlatformSummary,
    loadPlatformPayments,
    loadPlatformPayers,
    refreshPlatformTables,
    changePlatformPaymentsPage,
    changePlatformPayersPage,
  };
}
