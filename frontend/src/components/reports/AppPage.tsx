import { useEffect, useState, useRef, useMemo } from "react";
import { API_BASE_URL } from "../../services/api";
import { getInjectedWallet, shortAddress } from "../../services/wallet";
import { clearAllWalletProfileSessions, clearWalletProfileSession, requestWalletProfileSession } from "../../services/walletProfileSession";
import { payX402Resource } from "../../services/x402";
import { getInvoiceStatus } from "../../services/invoices";

interface Provider {
  provider_id: string;
  provider_name: string;
  description: string;
  owner_wallet: string;
  pricing?: {
    preview?: { amount_usdc: number };
    full?: { amount_usdc: number };
  };
  ui_schema?: {
    display_mode?: string;
    fields?: {
      key: string;
      label: string;
      type: string;
      step?: string;
      required?: boolean;
      default?: any;
    }[];
  };
  category?: string;
}

interface Anomaly {
  symbol: string;
  fundingRate: number;
  marketCap: number;
  circRatio: number;
  volume24h: number;
  fromATH: number;
  amount?: number;
  openInterest?: number;
  openInterestChange24h?: number;
  longShortRatio?: number;
  price?: number;
}

interface Recommendation {
  symbol: string;
  score: number;
  tier?: string;
  suggested_tier?: string;
  suggested_price_usdc?: number;
  provider_id: string;
  reason?: string;
  reasons?: string[];
  query?: Record<string, any>;
}

type PaymentStatus = "waiting" | "active" | "completed" | "failed";
type PaymentStepKey = "wallet" | "gateway" | "settlement" | "report";
type AgentSessionStage =
  | "idle"
  | "scanning"
  | "selected"
  | "invoicing"
  | "awaiting_signature"
  | "verifying"
  | "unlocked"
  | "error";

export function AppPage({
  onNavigate,
}: {
  onNavigate: (route: any) => void;
}) {
  const [wallet, setWallet] = useState(() => localStorage.getItem("qma_connected_wallet") || "");
  const [viewMode, setViewModeState] = useState<"basic" | "advanced">(() => {
    return (localStorage.getItem("qma_view_mode") as "basic" | "advanced") || "basic";
  });

  // Time / Clock
  const [timeStr, setTimeStr] = useState("");

  // Dropdown Panels
  const [statsDropdownOpen, setStatsDropdownOpen] = useState(false);
  const [walletDropdownOpen, setWalletDropdownOpen] = useState(false);

  // Platform Metrics
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
  const [platformTablesLoaded, setPlatformTablesLoaded] = useState(false);
  const [platformTablesLoading, setPlatformTablesLoading] = useState(false);
  const [platformTablesError, setPlatformTablesError] = useState("");

  // Sidebar Data
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [lastUpdatedTime, setLastUpdatedTime] = useState<Date | null>(null);
  const [anomaliesLoading, setAnomaliesLoading] = useState(false);
  const [anomaliesError, setAnomaliesError] = useState("");
  const [cacheRevision, setCacheRevision] = useState(0);

  // Current Selection
  const [selectedProviderId, setSelectedProviderId] = useState("funding_memory");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [activeQuery, setActiveQuery] = useState<Record<string, any>>({
    symbol: "HYPE",
    fundingRate: -0.005,
    marketCap: 250000000,
    FDV: 500000000,
    circRatio: 0.5,
    fromATH: -35.2,
    volume24h: 15000000,
  });

  // Basic vs Advanced form edits
  const [showBasicFields, setShowBasicFields] = useState(false);

  // Quotes Price
  const [quotedPrices, setQuotedPrices] = useState<Record<string, number>>({});

  // Paywall & Payment state
  const [paywallOpen, setPaywallOpen] = useState(false);
  const [currentInvoice, setCurrentInvoice] = useState<any>(null);
  const [paymentStep, setPaymentStep] = useState<PaymentStepKey>("wallet");
  const [paymentStepStatus, setPaymentStepStatus] = useState<Record<PaymentStepKey, { status: PaymentStatus; label: string; detail?: string }>>({
    wallet: { status: "waiting", label: "Waiting" },
    gateway: { status: "waiting", label: "Waiting" },
    settlement: { status: "waiting", label: "Waiting" },
    report: { status: "waiting", label: "Waiting" },
  });
  const [payStatusText, setPayStatusText] = useState("");
  const [payErrorText, setPayErrorText] = useState("");
  const [paymentSuccess, setPaymentSuccess] = useState(false);
  const [paymentDetails, setPaymentDetails] = useState({
    buyerGatewayBalance: "",
    settlementId: "",
    sellerAvailable: "",
    sellerPending: "",
    txHash: "",
    explorerUrl: "",
  });

  // Deposit Assist Modal inside paywall
  const [showDepositModal, setShowDepositModal] = useState(false);
  const [depositAmountInput, setDepositAmountInput] = useState("0.005");
  const [allowanceApproved, setAllowanceApproved] = useState(false);
  const [depositConfirmed, setDepositConfirmed] = useState(false);

  // Unlocked Report
  const [unlockedReport, setUnlockedReport] = useState<any>(null);
  const [reportCollapsed, setReportCollapsed] = useState(true);

  // Agent control bar trace logs
  const [agentPrompt, setAgentPrompt] = useState("");
  const [agentTrace, setAgentTrace] = useState<{ text: string; tone?: string }[]>([]);
  const [agentRunning, setAgentRunning] = useState(false);
  const [showAgentBuyerModal, setShowAgentBuyerModal] = useState(false);
  const [agentSessionStage, setAgentSessionStage] = useState<AgentSessionStage>("idle");
  const [agentSelectedPick, setAgentSelectedPick] = useState<any>(null);
  const [agentSessionInvoice, setAgentSessionInvoice] = useState<any>(null);
  const [agentVerifyResult, setAgentVerifyResult] = useState<any>(null);

  // Config addresses
  const [sellerAddress, setSellerAddress] = useState("");
  const [adminAddress, setAdminAddress] = useState("");
  const [arcGatewayUrl, setArcGatewayUrl] = useState("");
  const [gatewayContractAddress, setGatewayContractAddress] = useState("");

  // Dropdown copy status
  const [copySuccess, setCopySuccess] = useState(false);
  const [toast, setToast] = useState<{ message: string; tone: "info" | "success" | "warning" | "error" } | null>(null);

  // Modal display toggles
  const [showProfileModal, setShowProfileModal] = useState(false);
  const [showAgentRunModal, setShowAgentRunModal] = useState(false);
  const [showFundArcModal, setShowFundArcModal] = useState(false);

  // Quick Profile data
  const [profileChainUsdc, setProfileChainUsdc] = useState("n/a");
  const [profileGatewayUsdc, setProfileGatewayUsdc] = useState("n/a");
  const [profileReportsCount, setProfileReportsCount] = useState(0);
  const [profileTotalSpent, setProfileTotalSpent] = useState("0.00 USDC");
  const [profilePurchasedSymbols, setProfilePurchasedSymbols] = useState<string[]>([]);
  const [profileVerifiedPayments, setProfileVerifiedPayments] = useState<any[]>([]);
  const [profileVerifiedPaymentsPage, setProfileVerifiedPaymentsPage] = useState(1);
  const [profileVerifiedPaymentsTotalPages, setProfileVerifiedPaymentsTotalPages] = useState(1);
  const [profilePaymentsLoading, setProfilePaymentsLoading] = useState(false);
  const [profilePaymentsError, setProfilePaymentsError] = useState("");

  // Agent run modal policy & trace
  const [agentRunBudget, setAgentRunBudget] = useState("0.010");
  const [agentRunMaxPrice, setAgentRunMaxPrice] = useState("0.005");
  const [agentRunTraceLines, setAgentRunTraceLines] = useState<{ text: string; tone?: string }[]>([]);
  const [agentRunMode, setAgentRunMode] = useState<"judge" | "cli">("judge");
  const [agentRunInProgress, setAgentRunInProgress] = useState(false);

  // Fund Arc Wallet readiness status
  const [fundReadinessStatus, setFundReadinessStatus] = useState("Checking");
  const [fundReadinessTone, setFundReadinessTone] = useState("");
  const [fundWalletStatus, setFundWalletStatus] = useState("Not connected");
  const [fundProviderStatus, setFundProviderStatus] = useState("n/a");
  const [fundChainStatus, setFundChainStatus] = useState("n/a");
  const [fundArcStatus, setFundArcStatus] = useState("Unknown");
  const [fundWalletUsdc, setFundWalletUsdc] = useState("n/a");
  const [fundGatewayBalance, setFundGatewayBalance] = useState("n/a");
  const [fundRequiredAmount, setFundRequiredAmount] = useState("n/a");
  const [fundNextStep, setFundNextStep] = useState("Connect wallet first");
  const [fundPrimaryAction, setFundPrimaryAction] = useState({ action: "connect", label: "Connect wallet first" });

  const activeProvider = useMemo(() => {
    return providers.find((p) => p.provider_id === selectedProviderId);
  }, [providers, selectedProviderId]);

  const walletRole = useMemo(() => {
    const normalized = wallet.toLowerCase();
    if (!normalized) return { label: "Buyer", className: "role-buyer" };
    if (adminAddress && normalized === adminAddress.toLowerCase()) return { label: "Admin", className: "role-admin" };
    if (sellerAddress && normalized === sellerAddress.toLowerCase()) return { label: "Treasury", className: "role-treasury" };
    const ownedProvider = providers.find((provider) =>
      [provider.owner_wallet, (provider as any).revenue_wallet]
        .filter(Boolean)
        .some((address) => String(address).toLowerCase() === normalized)
    );
    if (ownedProvider) return { label: "Provider", className: "role-creator" };
    return { label: "Buyer", className: "role-buyer" };
  }, [adminAddress, providers, sellerAddress, wallet]);

  // Sync view mode class to body so public/app.css acts properly
  useEffect(() => {
    document.body.classList.toggle("advanced-view", viewMode === "advanced");
    document.body.classList.toggle("basic-view", viewMode === "basic");
    localStorage.setItem("qma_view_mode", viewMode);
  }, [viewMode]);

  // Update Clock
  useEffect(() => {
    const timer = setInterval(() => {
      setTimeStr(new Date().toLocaleTimeString());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Fetch Providers & Configuration
  useEffect(() => {
    async function loadConfig() {
      try {
        const resp = await fetch(`${API_BASE_URL}/api/v1/config`);
        if (!resp.ok) return;
        const data = await resp.json();
        setSellerAddress(data.seller_wallet || "");
        setAdminAddress(data.seller_wallet || "");
        setArcGatewayUrl(String(data.arc_gateway || "").replace(/\/$/, ""));
        // correct key from backend is circle_deposit_contract
        if (data.circle_deposit_contract || data.arc_gateway_contract) {
          setGatewayContractAddress(data.circle_deposit_contract || data.arc_gateway_contract);
        }
      } catch (err) {
        console.warn("Failed to load platform configuration", err);
      }
    }

    async function loadMetrics() {
      try {
        const resp = await fetch(`${API_BASE_URL}/api/v1/platform/summary`);
        if (!resp.ok) return;
        const data = await resp.json();
        setPlatformSummary(data);
        setMetrics({
          paid_count: data.current_paid_count ?? data.paid_count ?? 0,
          revenue_usdc: data.revenue_usdc || 0,
          available_usdc: data.seller_gateway_balance?.available_usdc ?? data.available_usdc ?? 0,
        });
      } catch (err) {
        console.warn("Failed to load metrics", err);
      }
    }

    loadConfig();
    loadMetrics();
    loadProviders();
    loadLiveAnomalies();
    loadAgentRecommendations();

    const interval = setInterval(() => {
      loadLiveAnomalies(true);
    }, 30000);

    const handleAccountsChanged = (accounts: any) => {
      clearAllWalletProfileSessions();
      const next = accounts && accounts[0] ? String(accounts[0]) : "";
      setWallet(next);
      if (next) localStorage.setItem("qma_connected_wallet", next);
      else localStorage.removeItem("qma_connected_wallet");
    };
    if (window.ethereum?.on) {
      window.ethereum.on("accountsChanged", handleAccountsChanged);
    }

    return () => {
      clearInterval(interval);
      if (window.ethereum?.removeListener) {
        window.ethereum.removeListener("accountsChanged", handleAccountsChanged);
      }
    };
  }, []);

  // Quote prices on query updates
  useEffect(() => {
    if (activeQuery?.symbol) {
      scheduleQuoteRefresh();
    }
  }, [activeQuery, selectedProviderId]);

  // Load Quick Profile data when opened or page changes
  useEffect(() => {
    if (showProfileModal) {
      loadQuickProfileData();
    }
  }, [showProfileModal, profileVerifiedPaymentsPage]);

  const handleCopyAddress = () => {
    if (!wallet) return;
    navigator.clipboard.writeText(wallet);
    setCopySuccess(true);
    setTimeout(() => setCopySuccess(false), 2000);
  };

  const showToast = (message: string, tone: "info" | "success" | "warning" | "error" = "info") => {
    setToast({ message, tone });
    window.setTimeout(() => {
      setToast((current) => (current?.message === message ? null : current));
    }, 3600);
  };

  const loadProviders = async () => {
    try {
      const resp = await fetch(`${API_BASE_URL}/api/v1/providers`);
      if (!resp.ok) return;
      const data = await resp.json();
      setProviders(data.providers || []);
    } catch (err) {
      console.warn("Failed to load providers list", err);
    }
  };

  const loadLiveAnomalies = async (silent = false) => {
    if (!silent) setAnomaliesLoading(true);
    setAnomaliesError("");
    try {
      const resp = await fetch(`${API_BASE_URL}/api/v1/live-anomalies`);
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "Failed to load anomalies");
      setAnomalies(data.anomalies || []);
      setLastUpdatedTime(data.last_updated ? new Date(data.last_updated) : new Date());

      // Auto select first anomaly on initial load if query is basic
      if (data.anomalies && data.anomalies.length > 0 && !silent) {
        loadAnomalyIntoQuery(data.anomalies[0]);
      }
    } catch (err: any) {
      setAnomaliesError(err.message || "Exchange scan error");
    } finally {
      setAnomaliesLoading(false);
    }
  };

  const loadAgentRecommendations = async () => {
    try {
      const resp = await fetch(`${API_BASE_URL}/api/v1/agent/recommendations`);
      if (!resp.ok) return;
      const data = await resp.json();
      setRecommendations(data.recommendations || []);
    } catch (err) {
      console.warn("Failed to load recommendations", err);
    }
  };

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
      setPlatformTablesLoaded(true);
    } catch (err: any) {
      console.warn("Platform analytics unavailable", err);
      setPlatformTablesError(err?.message || "Platform analytics unavailable.");
    } finally {
      setPlatformTablesLoading(false);
    }
  };

  const quoteTimer = useRef<any>(null);
  const scheduleQuoteRefresh = () => {
    clearTimeout(quoteTimer.current);
    quoteTimer.current = setTimeout(async () => {
      try {
        const tiers = ["preview", "full"];
        const results = await Promise.all(
          tiers.map(async (t) => {
            const resp = await fetch(`${API_BASE_URL}/api/v1/payment/quote`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                ...activeQuery,
                provider_id: selectedProviderId,
                tier: t,
              }),
            });
            if (!resp.ok) return [t, null];
            const resData = await resp.json();
            return [t, Number(resData.amount_usdc)];
          })
        );
        const nextQuotes: Record<string, number> = {};
        results.forEach(([t, val]) => {
          if (t && val !== null) nextQuotes[t as string] = val as number;
        });
        setQuotedPrices(nextQuotes);
      } catch (err) {
        console.warn("Quote refresh failed", err);
      }
    }, 400);
  };

  const connect = async () => {
    if (!window.ethereum?.request) {
      showToast("EVM wallet provider required.", "error");
      return;
    }
    try {
      const accounts = (await window.ethereum.request({ method: "eth_requestAccounts" })) as any;
      const next = accounts && accounts[0] ? String(accounts[0]) : "";
      setWallet(next);
      if (next) {
        localStorage.setItem("qma_connected_wallet", next);
        showToast("Wallet connected.", "success");
        try {
          await requestWalletProfileSession(next);
          showToast("Private profile access unlocked for this session.", "success");
        } catch (sessionErr: any) {
          showToast(sessionErr?.message || "Connected. Private snapshots can be unlocked later in Profile.", "warning");
        }
      }
    } catch (err: any) {
      showToast(err.message || "Connection failed", "error");
    }
  };

  const paymentClass = (status: PaymentStatus) => {
    if (status === "active") return "is-active";
    if (status === "completed") return "is-completed";
    if (status === "failed") return "is-failed";
    return "is-pending";
  };


  const disconnect = () => {
    if (wallet) clearWalletProfileSession(wallet);
    setWallet("");
    localStorage.removeItem("qma_connected_wallet");
    setWalletDropdownOpen(false);
    showToast("Wallet disconnected. Private profile session cleared.", "info");
  };

  const openQuickProfileModal = () => {
    setWalletDropdownOpen(false);
    setProfileVerifiedPaymentsPage(1);
    setProfileChainUsdc("loading...");
    setProfileGatewayUsdc("loading...");
    setProfileReportsCount(0);
    setProfileTotalSpent("loading...");
    setProfilePurchasedSymbols([]);
    setProfileVerifiedPayments([]);
    setProfilePaymentsError("");
    setShowProfileModal(true);
  };

  const normalizeSignalPayload = (source: Record<string, any> = {}) => {
    const numberOrNull = (value: any) => {
      if (value === undefined || value === null || value === "") return null;
      const num = Number(value);
      return Number.isFinite(num) ? Number(num.toFixed(12)) : null;
    };
    return {
      symbol: String(source.symbol || "").trim().toUpperCase(),
      fundingRate: numberOrNull(source.fundingRate ?? source.funding_rate),
      marketCap: numberOrNull(source.marketCap ?? source.market_cap),
      FDV: numberOrNull(source.FDV ?? source.fdv),
      circRatio: numberOrNull(source.circRatio ?? source.circ_ratio),
      fromATH: numberOrNull(source.fromATH ?? source.fromATHPercent ?? source["fromATH(%)"]),
      volume24h: numberOrNull(source.volume24h ?? source.volume_24h),
      amount: numberOrNull(source.amount ?? source.openInterest ?? source.open_interest),
      openInterest: numberOrNull(source.openInterest ?? source.open_interest ?? source.amount),
      openInterestChange24h: numberOrNull(source.openInterestChange24h ?? source.open_interest_change_24h),
      longShortRatio: numberOrNull(source.longShortRatio ?? source.long_short_ratio),
      price: numberOrNull(source.price),
    };
  };

  const normalizeTierForCache = (tier: any): "preview" | "full" => {
    return String(tier || "").toLowerCase() === "preview" ? "preview" : "full";
  };

  const signalFingerprint = (source: Record<string, any> = {}) => {
    return b64encode(normalizeSignalPayload(source));
  };

  const signalCacheKey = (
    signal: Record<string, any>,
    tier: "preview" | "full" = "full",
    providerId: string = selectedProviderId,
    account = wallet
  ) => {
    const normalized = normalizeSignalPayload(signal);
    const normalizedWallet = String(account || "").toLowerCase();
    if (!normalizedWallet || !normalized.symbol) return "";
    return `qma_paid_signal_v5_${normalizedWallet}_${providerId}_${tier}_${normalized.symbol}_${signalFingerprint(normalized)}`;
  };

  const pendingInvoiceStoreKey = (account = wallet) => {
    return `qma_pending_invoices_${String(account || "browser").toLowerCase()}`;
  };

  const pendingInvoiceMatchKey = (
    signal: Record<string, any>,
    tier: "preview" | "full",
    providerId: string = selectedProviderId
  ) => {
    const normalized = normalizeSignalPayload(signal);
    if (!normalized.symbol) return "";
    return `${providerId || "funding_memory"}:${tier}:${signalFingerprint(normalized)}`;
  };

  const readPendingInvoiceStore = (account = wallet) => {
    try {
      return JSON.parse(localStorage.getItem(pendingInvoiceStoreKey(account)) || "{}") || {};
    } catch {
      return {};
    }
  };

  const writePendingInvoiceStore = (store: Record<string, any>, account = wallet) => {
    try {
      localStorage.setItem(pendingInvoiceStoreKey(account), JSON.stringify(store || {}));
    } catch (err) {
      console.warn("Could not persist pending invoice", err);
    }
  };

  const rememberPendingInvoice = (
    invoice: any,
    signal: Record<string, any> = activeQuery,
    tier: "preview" | "full" = normalizeTierForCache(invoice?.tier || "full"),
    providerId: string = invoice?.provider_id || selectedProviderId,
    account = wallet
  ) => {
    if (!invoice?.invoice_id || !invoice?.invoice_secret || !signal) return;
    const key = pendingInvoiceMatchKey(signal, tier, providerId);
    if (!key) return;
    const store = readPendingInvoiceStore(account);
    store[key] = {
      saved_at: Date.now(),
      signal: normalizeSignalPayload(signal),
      invoice: {
        ...invoice,
        invoice_secret: invoice.invoice_secret,
        split_legs: Array.isArray(invoice.split_legs) ? invoice.split_legs : [],
      },
    };
    store.__last_key = key;
    writePendingInvoiceStore(store, account);
  };

  const clearPendingInvoice = (
    signal: Record<string, any> = activeQuery,
    tier: "preview" | "full" = "full",
    providerId: string = selectedProviderId,
    account = wallet
  ) => {
    const key = pendingInvoiceMatchKey(signal, tier, providerId);
    if (!key) return;
    const store = readPendingInvoiceStore(account);
    delete store[key];
    if (store.__last_key === key) delete store.__last_key;
    writePendingInvoiceStore(store, account);
  };

  const refreshPendingInvoice = async (
    signal: Record<string, any>,
    tier: "preview" | "full",
    providerId: string = selectedProviderId,
    account = wallet
  ) => {
    const key = pendingInvoiceMatchKey(signal, tier, providerId);
    const entry = key ? readPendingInvoiceStore(account)[key] : null;
    const invoice = entry?.invoice;
    if (!invoice?.invoice_id || !invoice?.invoice_secret) return null;
    try {
      const state = await getInvoiceStatus(invoice.invoice_id, invoice.invoice_secret);
      return {
        ...invoice,
        ...state,
        invoice_secret: invoice.invoice_secret,
        arc_gateway_url: invoice.arc_gateway_url || state.arc_gateway_url,
        split_legs: Array.isArray(state.split_legs) ? state.split_legs : invoice.split_legs,
      };
    } catch (err) {
      console.warn("Pending invoice status check failed", err);
      return null;
    }
  };

  const getCachedReport = (signal: any, tier: "preview" | "full" = "full", providerId: string = selectedProviderId) => {
    if (!wallet) return null;
    const normalized = normalizeSignalPayload(signal);
    const keys = [
      signalCacheKey(normalized, tier, providerId),
      `qma_paid_signal_v5_${wallet.toLowerCase()}_${providerId}_${tier}_${normalized.symbol}_${b64encode(signal)}`,
    ].filter(Boolean);
    if (tier === "preview") {
      keys.push(signalCacheKey(normalized, "full", providerId));
      keys.push(`qma_paid_signal_v5_${wallet.toLowerCase()}_${providerId}_full_${normalized.symbol}_${b64encode(signal)}`);
    }
    const raw = keys.map((key) => localStorage.getItem(key)).find(Boolean);
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  };

  const getCachedReportsForSymbol = (symbol: string, providerId?: string) => {
    if (!wallet) return [];
    const normalizedSymbol = String(symbol || "").trim().toUpperCase();
    const prefix = `qma_paid_signal_v5_${wallet.toLowerCase()}_`;
    const found: any[] = [];
    const seen = new Set<string>();
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith(prefix) && key.includes(`_${normalizedSymbol}_`)) {
        try {
          const entry = JSON.parse(localStorage.getItem(key) || "{}");
          const entryProvider = entry.provider_id || entry.report?.provider_id || entry.report?.invoice?.provider_id;
          const entrySymbol = String(entry.signal?.symbol || entry.report?.query_symbol || "").toUpperCase();
          const cacheId = entry.report?.query_hash || entry.report?.invoice?.settlement_id || key;
          if (
            entry?.report &&
            entrySymbol === normalizedSymbol &&
            (!providerId || !entryProvider || entryProvider === providerId) &&
            !seen.has(cacheId)
          ) {
            seen.add(cacheId);
            found.push(entry);
          }
        } catch {}
      }
    }
    return found.sort((a, b) => (b.saved_at || 0) - (a.saved_at || 0));
  };

  const paidBadgeText = (entry: any) => {
    const tier = normalizeTierForCache(entry?.tier || entry?.report?.tier || entry?.report?.invoice?.tier || "full");
    return tier === "preview" ? "Paid Preview" : "Paid Full";
  };

  const entitlementBadgeForSignal = (signal: Record<string, any>, providerId: string = selectedProviderId) => {
    void cacheRevision;
    const normalized = normalizeSignalPayload(signal);
    const cachedEntry = getCachedReport(normalized, "full", providerId) || getCachedReport(normalized, "preview", providerId);
    const historyEntries = cachedEntry ? [] : getCachedReportsForSymbol(normalized.symbol, providerId);
    if (cachedEntry?.report) {
      return {
        className: "paid",
        text: paidBadgeText(cachedEntry),
        meta: cachedEntry.saved_at ? `Bought ${formatDateTime(cachedEntry.saved_at)}` : "Paid snapshot",
        entry: cachedEntry,
      };
    }
    if (historyEntries.length) {
      return {
        className: "history",
        text: "Paid History",
        meta: historyEntries[0].saved_at ? `Last paid ${formatDateTime(historyEntries[0].saved_at)}` : "Previous snapshot",
        entry: historyEntries[0],
      };
    }
    return { className: "unpaid", text: "Pay to Unlock", meta: "Live scan", entry: null };
  };

  const openCachedReportEntry = (entry: any, fallbackSignal: Record<string, any>, providerId = selectedProviderId) => {
    if (!entry?.report) return false;
    const reportSignal = normalizeSignalPayload(entry.signal || entry.report?.query || fallbackSignal || { symbol: entry.report?.query_symbol });
    setSelectedProviderId(entry.provider_id || entry.report?.provider_id || entry.report?.invoice?.provider_id || providerId);
    setActiveQuery(reportSignal);
    setUnlockedReport({
      ...entry.report,
      query: entry.report?.query || reportSignal,
      tier: entry.report?.tier || entry.tier,
      provider_id: entry.report?.provider_id || entry.provider_id || providerId,
    });
    setCurrentInvoice(entry.report?.invoice || entry.invoice || null);
    setPaywallOpen(false);
    setReportCollapsed(false);
    refreshPlatformTables(1, 1).catch((err) => console.warn("Platform analytics refresh for cached report failed", err));
    return true;
  };

  const loadAnomalyIntoQuery = (anom: Anomaly) => {
    const signal = normalizeSignalPayload({
      symbol: anom.symbol,
      fundingRate: anom.fundingRate,
      marketCap: anom.marketCap,
      FDV: anom.fromATH ? anom.marketCap / (1 + anom.fromATH / 100) : anom.marketCap,
      circRatio: anom.circRatio,
      fromATH: anom.fromATH,
      volume24h: anom.volume24h,
      amount: anom.amount || anom.openInterest,
      openInterest: anom.openInterest || anom.amount,
      openInterestChange24h: anom.openInterestChange24h,
      longShortRatio: anom.longShortRatio,
      price: anom.price,
    });
    setActiveQuery(signal);

    const cachedFull = getCachedReport(signal, "full");
    if (openCachedReportEntry(cachedFull, signal)) return;

    const cachedPreview = getCachedReport(signal, "preview");
    if (openCachedReportEntry(cachedPreview, signal)) return;

    const previousReports = getCachedReportsForSymbol(signal.symbol);
    if (previousReports.length) {
      const prev = previousReports[0];
      openCachedReportEntry(prev, signal);
      showToast(`Showing previous paid ${signal.symbol} report from ${new Date(prev.saved_at).toLocaleString()}. The current live snapshot still needs a new purchase.`, "info");
    } else {
      setUnlockedReport(null);
      setReportCollapsed(true);
      if (wallet) {
        setPaywallOpen(true);
        openPaywall("full");
      }
    }
  };

  const loadQuickProfileData = async () => {
    if (!wallet) return;
    const account = wallet;
    const page = profileVerifiedPaymentsPage;
    setProfilePaymentsLoading(true);
    setProfilePaymentsError("");

    const cleanGatewayUrl = arcGatewayUrl.replace(/\/$/, "");
    if (cleanGatewayUrl) {
      try {
        const statusResp = await fetch(`${cleanGatewayUrl}/api/wallet-status/${account}`);
        if (statusResp.ok) {
          const statusData = await statusResp.json();
          const chainBal = getOnChainUsdcBalance(statusData);
          setProfileChainUsdc(chainBal ? `${Number(chainBal).toFixed(6)} USDC` : "0.000000 USDC");
        } else {
          setProfileChainUsdc("n/a");
        }
      } catch (err) {
        console.warn("Failed to load quick profile wallet status", err);
        setProfileChainUsdc("n/a");
      }

      try {
        const balResp = await fetch(`${cleanGatewayUrl}/api/balance/${account}`);
        if (balResp.ok) {
          const balData = await balResp.json();
          const formattedGatewayBal = extractGatewayBalanceUsdc(balData) ?? 0;
          setProfileGatewayUsdc(`${formattedGatewayBal.toFixed(6)} USDC`);
        } else {
          setProfileGatewayUsdc("n/a");
        }
      } catch (err) {
        console.warn("Failed to load quick profile gateway balance", err);
        setProfileGatewayUsdc("n/a");
      }
    } else {
      setProfileChainUsdc("n/a");
      setProfileGatewayUsdc("n/a");
    }

    try {
      const summaryResp = await fetch(`${API_BASE_URL}/api/v1/wallets/${account}/summary`);
      if (summaryResp.ok) {
        const summaryData = await summaryResp.json();
        setProfileReportsCount(summaryData.current_payments ?? summaryData.payments ?? 0);
        setProfileTotalSpent(`${Number(summaryData.spent_usdc || 0).toFixed(3)} USDC`);
        setProfilePurchasedSymbols(Array.isArray(summaryData.purchased_symbols) ? summaryData.purchased_symbols : []);
      }
    } catch (err) {
      console.warn("Failed to load quick profile summary", err);
    }

    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: "10",
      });
      const paymentsResp = await fetch(`${API_BASE_URL}/api/v1/wallets/${account}/payments?${params.toString()}`);
      if (paymentsResp.ok) {
        const paymentsData = await paymentsResp.json();
        const rows = paymentsData.recent_payments || paymentsData.payments || [];
        const pageMeta = paymentsData.recent_payments_page || paymentsData.meta || {};
        setProfileVerifiedPayments(Array.isArray(rows) ? rows : []);
        setProfileVerifiedPaymentsTotalPages(Number(pageMeta.total_pages || pageMeta.pages || 1));
      } else {
        setProfileVerifiedPayments([]);
        setProfilePaymentsError(`Could not load payments (${paymentsResp.status}).`);
      }
    } catch (err) {
      console.warn("Failed to load quick profile payments", err);
      setProfileVerifiedPayments([]);
      setProfilePaymentsError("Could not load verified payments.");
    } finally {
      setProfilePaymentsLoading(false);
    }
  };

  const getOnChainUsdcBalance = (walletStatus: any) => {
    return walletStatus?.usdc?.formatted ?? walletStatus?.usdcBalance?.formatted ?? null;
  };

  // Mirror of app.js extractGatewayBalanceUsdc; handles all Circle API response shapes.
  // Circle returns: { token, balances: [{ domain, depositor, balance: "0.99", pendingBatch: "0" }] }
  const extractGatewayBalanceUsdc = (data: any): number | null => {
    const candidates = [
      data?.balance,
      data?.available,
      data?.amount,
      data?.balances?.[0]?.amount,
      data?.balances?.[0]?.balance,
      data?.sources?.[0]?.amount,
      data?.sources?.[0]?.balance,
      data?.data?.balances?.[0]?.amount,
    ];
    for (const c of candidates) {
      if (c === undefined || c === null) continue;
      const raw = Number(c);
      if (!Number.isFinite(raw)) continue;
      return raw > 1000 ? raw / 1_000_000 : raw;
    }
    return null;
  };

  const refreshFundingReadiness = async () => {
    const required = 0.005;
    const requiredLabel = `${required.toFixed(3)} USDC`;
    setFundRequiredAmount(requiredLabel);

    if (!wallet) {
      setFundReadinessStatus("Wallet needed");
      setFundReadinessTone("warn");
      setFundWalletStatus("Not connected");
      setFundProviderStatus("n/a");
      setFundChainStatus("n/a");
      setFundArcStatus("Unknown");
      setFundWalletUsdc("n/a");
      setFundGatewayBalance("n/a");
      setFundNextStep("Connect wallet first");
      setFundPrimaryAction({ action: "connect", label: "Connect wallet first" });
      return;
    }

    setFundWalletStatus(shortAddress(wallet));

    let provider = null;
    let chainIdHex = "";
    let isArc = false;
    let chainLabel = "n/a";
    let providerLabel = "Injected Wallet";
    let error: any = null;

    try {
      provider = getInjectedWallet();
      if (provider) {
        const pAny = provider as any;
        if (pAny.isMetaMask) providerLabel = "MetaMask";
        else if (pAny.isRabby) providerLabel = "Rabby";
        else if (pAny.isOKX || pAny.isOKExWallet) providerLabel = "OKX Wallet";
        setFundProviderStatus(providerLabel);

        const rawChainId = await provider.request<string>({ method: "eth_chainId" });
        chainIdHex = String(rawChainId).toLowerCase();
        isArc = chainIdHex === "0x4cef52";
        chainLabel = isArc ? "Arc Testnet" : `Other Network (${chainIdHex})`;
        setFundChainStatus(chainLabel);
        setFundArcStatus(isArc ? "Arc Testnet" : "Wrong network");
      }
    } catch (err) {
      error = err;
      setFundChainStatus("Chain detection failed");
      setFundArcStatus("Unknown");
    }

    if (error || !provider) {
      setFundReadinessStatus("Check failed");
      setFundReadinessTone("warn");
      setFundNextStep("Funding status is unavailable. Retry or continue to payment.");
      setFundPrimaryAction({ action: "refresh", label: "Retry readiness check" });
      return;
    }

    if (!isArc) {
      setFundReadinessStatus("Wrong chain");
      setFundReadinessTone("warn");
      setFundNextStep("Add or switch to Arc Testnet. Your wallet will show the network details for approval.");
      setFundPrimaryAction({ action: "switch", label: "Add / Switch Arc Testnet" });
      return;
    }

    try {
      const cleanGatewayUrl = arcGatewayUrl.replace(/\/$/, "");
      const [statusResp, balResp] = await Promise.all([
        fetch(`${cleanGatewayUrl}/api/wallet-status/${wallet}`),
        fetch(`${cleanGatewayUrl}/api/balance/${wallet}`),
      ]);

      let walletBal = 0;
      if (statusResp.ok) {
        const statusData = await statusResp.json();
        const chainBal = getOnChainUsdcBalance(statusData);
        walletBal = chainBal ? Number(chainBal) : 0;
        setFundWalletUsdc(`${walletBal.toFixed(3)} USDC`);
      } else {
        setFundWalletUsdc("n/a");
      }

      let gatewayBal = 0;
      if (balResp.ok) {
        const balData = await balResp.json();
        gatewayBal = extractGatewayBalanceUsdc(balData) ?? 0;
        setFundGatewayBalance(`${gatewayBal.toFixed(3)} USDC`);
      } else {
        setFundGatewayBalance("n/a");
      }

      if (gatewayBal >= required) {
        setFundReadinessStatus("Ready");
        setFundReadinessTone("ready");
        setFundNextStep("Gateway balance is ready for the selected report.");
        setFundPrimaryAction({ action: "close", label: "Continue to payment" });
      } else if (walletBal + gatewayBal >= required) {
        setFundReadinessStatus("Gateway low");
        setFundReadinessTone("warn");
        setFundNextStep("Continue to payment; QMA will prompt Gateway Deposit");
        setFundPrimaryAction({ action: "close", label: "Continue to payment" });
      } else {
        setFundReadinessStatus("Funding needed");
        setFundReadinessTone("warn");
        setFundNextStep("Use Faucet or CCTP/App Kit, then retry. Arc uses USDC for gas and payment funding.");
        setFundPrimaryAction({ action: "faucet", label: "Open Circle Faucet" });
      }
    } catch (err) {
      setFundReadinessStatus("Check failed");
      setFundReadinessTone("warn");
      setFundNextStep("Funding status is unavailable. Retry or continue to payment.");
      setFundPrimaryAction({ action: "refresh", label: "Retry readiness check" });
    }
  };

  const recommendationTierPrice = (pick: any, tier: string, pricing: Record<string, number>) => {
    const baseKey = `${pick.provider_id || "funding_memory"}_${tier}`;
    return pricing[baseKey] || (tier === "preview" ? 0.001 : 0.005);
  };

  const recommendationTier = (pick: any): "preview" | "full" => {
    const tier = String(pick?.tier || pick?.suggested_tier || "").toLowerCase();
    return tier === "full" ? "full" : "preview";
  };

  const agentPendingInvoiceFor = (signal: any, tier: string) => {
    if (currentInvoice && currentInvoice.tier === tier && currentInvoice.symbol === signal.symbol) {
      return currentInvoice;
    }
    return null;
  };

  const getLatestCachedReportForSymbolTier = (symbol: string, tier: "preview" | "full", providerId: string) => {
    const list = getCachedReportsForSymbol(symbol, providerId);
    return list.find((entry) => entry.tier === tier) || null;
  };

  const agentPolicyPick = (recommendationsList: any[] = [], budget = 0.01, maxPrice = 0.005, pricing = {}) => {
    const audit: any[] = [];
    const candidates = recommendationsList.map((pick) => {
      let tier = recommendationTier(pick);
      const signal = pick.query || { symbol: pick.symbol };
      const providerId = pick.provider_id || selectedProviderId || "funding_memory";
      
      const fullEntry = getCachedReport(signal, "full", providerId);
      const exactPreviewEntry = fullEntry ? null : getCachedReport(signal, "preview", providerId);
      const symbolPreviewEntry = exactPreviewEntry || getLatestCachedReportForSymbolTier(signal.symbol, "preview", providerId);
      
      const shouldUpgrade = tier === "preview" && symbolPreviewEntry?.report && !fullEntry?.report;
      if (shouldUpgrade) {
        tier = "full";
      }
      
      const price = recommendationTierPrice(pick, tier, pricing);
      const pendingInvoice = agentPendingInvoiceFor(signal, tier);
      let skippedReason = "";
      
      if (price <= 0) {
        skippedReason = "missing price";
      } else if (fullEntry?.report) {
        skippedReason = "Full Report already purchased";
      } else if (pendingInvoice) {
        skippedReason = `invoice is already waiting for payment`;
      } else if (price > budget) {
        skippedReason = `over budget (${price.toFixed(3)} > ${budget.toFixed(3)})`;
      } else if (price > maxPrice) {
        skippedReason = `over max/report (${price.toFixed(3)} > ${maxPrice.toFixed(3)})`;
      }
      
      return {
        ...pick,
        agent_tier: tier,
        agent_price: price,
        agent_signal: signal,
        agent_upgrade_from_preview: shouldUpgrade,
        agent_upgrade_match: exactPreviewEntry?.report ? "exact Preview snapshot" : "previous Preview for same symbol",
        agent_skipped_reason: skippedReason,
        agent_value_density: price > 0 ? Number(pick.score || 0) / price : 0,
      };
    });

    candidates.slice(0, 5).forEach((pick) => {
      if (pick.agent_skipped_reason) {
        audit.push({ text: `Skipped ${pick.symbol}: ${pick.agent_skipped_reason}.`, tone: "muted" });
      } else if (pick.agent_upgrade_from_preview) {
        audit.push({
          text: `Candidate ${pick.symbol}: ${pick.agent_upgrade_match} already paid, evaluating Full Report upgrade at ${pick.agent_price.toFixed(3)} USDC.`,
          tone: "active",
        });
      } else {
        audit.push({
          text: `Candidate ${pick.symbol}: score ${Number(pick.score || 0).toFixed(1)}, value density ${pick.agent_value_density.toFixed(1)}.`,
          tone: "active",
        });
      }
    });

    const selected = candidates
      .filter((pick) => !pick.agent_skipped_reason)
      .sort((a, b) => {
        const upgradeDiff = Number(Boolean(b.agent_upgrade_from_preview)) - Number(Boolean(a.agent_upgrade_from_preview));
        if (upgradeDiff) return upgradeDiff;
        const valueDiff = Number(b.agent_value_density || 0) - Number(a.agent_value_density || 0);
        return valueDiff || Number(b.score || 0) - Number(a.score || 0);
      })[0] || null;

    return { selected, audit };
  };

  const runAgentDecision = async () => {
    const budget = Number(agentRunBudget);
    const maxPrice = Number(agentRunMaxPrice);
    if (!Number.isFinite(budget) || budget <= 0 || !Number.isFinite(maxPrice) || maxPrice <= 0) {
      showToast("Agent policy needs a positive budget and max price.", "warning");
      return;
    }

    setAgentRunInProgress(true);
    setAgentRunTraceLines([
      { text: `Policy loaded: budget ${budget.toFixed(3)} USDC, max/report ${maxPrice.toFixed(3)} USDC.`, tone: "active" },
      { text: "Fetching live paid opportunities from /api/v1/agent/recommendations...", tone: "" }
    ]);

    try {
      const resp = await fetch(`${API_BASE_URL}/api/v1/agent/recommendations?limit=8`);
      if (!resp.ok) throw new Error(`Agent endpoint returned ${resp.status}`);
      const data = await resp.json();
      const picks = data.recommendations || [];
      
      setAgentRunTraceLines(prev => [...prev, { text: `Scanned ${picks.length} ranked opportunities.`, tone: "" }]);

      const pricing = data.pricing || {};
      const { selected, audit } = agentPolicyPick(picks, budget, maxPrice, pricing);
      
      audit.forEach((line: any) => {
        setAgentRunTraceLines(prev => [...prev, { text: line.text, tone: line.tone }]);
      });

      if (!selected) {
        setAgentRunTraceLines(prev => [...prev, { text: "No affordable report matched the current budget policy.", tone: "warning" }]);
        return;
      }

      const signal = selected.agent_signal || selected.query || { symbol: selected.symbol };
      setAgentRunTraceLines(prev => [...prev, {
        text: `Selected ${selected.symbol}: score ${Number(selected.score || 0).toFixed(1)}, ${selected.agent_tier} report, ${selected.agent_price.toFixed(3)} USDC.`,
        tone: "success"
      }]);

      if (selected.agent_upgrade_from_preview) {
        setAgentRunTraceLines(prev => [...prev, {
          text: "Upgrade rule: paid Preview exists, so agent is buying the Full Report instead of paying for Preview again.",
          tone: "success"
        }]);
      }

      setAgentRunTraceLines(prev => [...prev,
        { text: "Decision rule: complete paid Preview snapshots first, then choose highest value density under budget.", tone: "" },
        { text: `Reasoning: ${(selected.reasons || ["fresh live anomaly"]).join(" | ")}`, tone: "" },
        { text: "Creating provider-bound invoice with buyer_type=agent...", tone: "" }
      ]);

      if (!wallet) {
        setAgentRunTraceLines(prev => [...prev, { text: "No wallet address provided. Run cancelled.", tone: "error" }]);
        return;
      }

      setSelectedProviderId(selected.provider_id || "funding_memory");
      setActiveQuery(signal);
      setShowAgentRunModal(false);
      openPaywall(selected.agent_tier);
    } catch (err: any) {
      console.warn("Agent run failed", err);
      setAgentRunTraceLines(prev => [...prev, { text: `Agent run failed: ${err.message || err}`, tone: "error" }]);
    } finally {
      setAgentRunInProgress(false);
    }
  };

  const handleProviderChange = (providerId: string) => {
    setSelectedProviderId(providerId);
    const target = providers.find((p) => p.provider_id === providerId);
    if (target?.ui_schema?.fields) {
      const fieldsQuery: Record<string, any> = { symbol: activeQuery.symbol || "HYPE" };
      target.ui_schema.fields.forEach((f) => {
        fieldsQuery[f.key] = f.default !== undefined ? f.default : "";
      });
      setActiveQuery(fieldsQuery);
    }
  };

  // Paywall Actions
  const openPaywall = async (tier: "preview" | "full", event?: React.FormEvent) => {
    if (event) event.preventDefault();
    if (!wallet) {
      showToast("Please connect your wallet first.", "warning");
      return;
    }

    setPaywallOpen(true);
    setPaymentSuccess(false);
    setPayErrorText("");
    setUnlockedReport(null);
    setPaymentDetails({
      buyerGatewayBalance: "",
      settlementId: "",
      sellerAvailable: "",
      sellerPending: "",
      txHash: "",
      explorerUrl: "",
    });

    // Initial Stepper labels
    setPaymentStep("wallet");
    setPaymentStepStatus({
      wallet: { status: "active", label: "Checking" },
      gateway: { status: "waiting", label: "Waiting" },
      settlement: { status: "waiting", label: "Waiting" },
      report: { status: "waiting", label: "Waiting" },
    });

    try {
      // 1. Check Wallet & Arc Network chain ID
      const provider = getInjectedWallet();
      if (!provider) throw new Error("Wallet not found.");
      const chainId = await provider.request<string>({ method: "eth_chainId" });
      const ARC_TESTNET_HEX = "0x4cef52";
      if (String(chainId).toLowerCase() !== ARC_TESTNET_HEX) {
        setPayStatusText("Switching network to Arc Testnet...");
        try {
          await provider.request({
            method: "wallet_switchEthereumChain",
            params: [{ chainId: ARC_TESTNET_HEX }],
          });
        } catch (switchErr: any) {
          // If chain not added, try adding it
          if (switchErr.code === 4902 || String(switchErr.message).toLowerCase().includes("unrecognized")) {
            await provider.request({
              method: "wallet_addEthereumChain",
              params: [
                {
                  chainId: ARC_TESTNET_HEX,
                  chainName: "Arc Testnet",
                  nativeCurrency: { name: "USDC", symbol: "USDC", decimals: 18 },
                  rpcUrls: ["https://rpc.testnet.arc.network"],
                  blockExplorerUrls: ["https://testnet.arcscan.app"],
                },
              ],
            });
            await provider.request({
              method: "wallet_switchEthereumChain",
              params: [{ chainId: ARC_TESTNET_HEX }],
            });
          } else {
            throw switchErr;
          }
        }
      }

      setPaymentStepStatus((prev) => ({
        ...prev,
        wallet: { status: "completed", label: "Connected" },
        gateway: { status: "active", label: "Checking" },
      }));
      setPaymentStep("gateway");

      // 2. Resume an unfinished invoice first; invoice_secret only exists client-side.
      setPayStatusText("Checking pending invoice state...");
      let invoiceData = await refreshPendingInvoice(activeQuery, tier, selectedProviderId, wallet);
      if (invoiceData?.access_status === "expired" || invoiceData?.access_status === "disputed") {
        clearPendingInvoice(activeQuery, tier, selectedProviderId, wallet);
        invoiceData = null;
      }
      if (invoiceData?.status === "paid" && invoiceData.access_token) {
        setCurrentInvoice(invoiceData);
        sessionStorage.setItem(`qma_accessToken_${invoiceData.invoice_id}`, invoiceData.access_token);
        setPaymentStepStatus((prev) => ({
          ...prev,
          gateway: { status: "completed", label: "Funded" },
          settlement: { status: "completed", label: "Accepted" },
          report: { status: "active", label: "Opening" },
        }));
        setPayStatusText("Recovered paid invoice. Opening report...");
        await fetchReportContent(invoiceData.invoice_id, invoiceData.access_token, invoiceData, activeQuery, selectedProviderId);
        clearPendingInvoice(activeQuery, tier, selectedProviderId, wallet);
        return;
      }

      if (!invoiceData) {
        setPayStatusText("Creating payment invoice...");
        const invoiceResp = await fetch(`${API_BASE_URL}/api/v1/payment/invoice`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...activeQuery,
            provider_id: selectedProviderId,
            tier,
          }),
        });

        invoiceData = await invoiceResp.json();
        if (!invoiceResp.ok) throw new Error(invoiceData.detail || "Failed to create invoice");
      } else {
        showToast(`Resumed invoice ${shortAddress(invoiceData.invoice_id)}. Continue with remaining split leg.`, "info");
      }
      setCurrentInvoice(invoiceData);
      rememberPendingInvoice(invoiceData, activeQuery, tier, selectedProviderId, wallet);

      // Check user's Gateway balance via Arc Gateway (port 3000)
      // arcGatewayUrl = "http://127.0.0.1:3000" from /api/v1/config
      // Fallback: extract origin from arc_gateway_url in invoice (e.g. "http://127.0.0.1:3000/qma-access?...")
      setPayStatusText("Reading Gateway Balance...");
      let gatewayBase = arcGatewayUrl.replace(/\/$/, "");
      if (!gatewayBase && invoiceData.arc_gateway_url) {
        try { gatewayBase = new URL(invoiceData.arc_gateway_url).origin; } catch { gatewayBase = ""; }
      }
      if (!gatewayBase) throw new Error("Arc Gateway URL not configured. Retry or refresh.");
      const cleanGatewayUrl = gatewayBase;
      const balResp = await fetch(`${cleanGatewayUrl}/api/balance/${wallet}`);
      if (!balResp.ok) throw new Error("Could not check Gateway Balance");
      const balData = await balResp.json();
      // extractGatewayBalanceUsdc already normalises atomic values > 1000 to USDC
      const gatewayBal = extractGatewayBalanceUsdc(balData) ?? 0;
      setPaymentDetails((prev) => ({
        ...prev,
        buyerGatewayBalance: `${gatewayBal.toFixed(6)} USDC`,
      }));

      const invoiceCost = Number(invoiceData.amount);
      if (gatewayBal < invoiceCost) {
        // Enforce Top Up Assist Modal
        setPayStatusText(`Top Up required: need ${invoiceCost.toFixed(6)} USDC, have ${gatewayBal.toFixed(6)} USDC`);
        setPaymentStepStatus((prev) => ({
          ...prev,
          gateway: { status: "failed", label: "Top Up Needed" },
        }));
        setPaymentStep("gateway");
        setDepositAmountInput(Math.max(invoiceCost, 0.005).toFixed(6));
        setShowDepositModal(true);
        return;
      }

      // Preload ready for signing
      setPaymentStepStatus((prev) => ({
        ...prev,
        gateway: { status: "completed", label: "Funded" },
        settlement: { status: "active", label: "Sign Settlement" },
      }));
      setPaymentStep("settlement");
      setPayStatusText("Gateway funds confirmed. Ready for settlement signature.");
    } catch (err: any) {
      setPayErrorText(err.message || "Failed to initialize payment.");
      setPaymentStepStatus((prev) => ({
        ...prev,
        wallet: { status: "failed", label: "Failed" },
      }));
    }
  };

  const handleDepositToGateway = async () => {
    if (!currentInvoice || !wallet) return;
    const amount = Number(depositAmountInput);
    if (isNaN(amount) || amount <= 0) {
      showToast("Invalid deposit amount.", "warning");
      return;
    }

    setPayStatusText("Preparing gateway deposit transaction...");
    try {
      let gwBase = arcGatewayUrl.replace(/\/$/, "");
      if (!gwBase && currentInvoice?.arc_gateway_url) {
        try { gwBase = new URL(currentInvoice.arc_gateway_url).origin; } catch { gwBase = ""; }
      }
      const cleanGatewayUrl = gwBase;
      const walletStatusResp = await fetch(`${cleanGatewayUrl}/api/wallet-status/${wallet}`);
      const statusData = walletStatusResp.ok ? await walletStatusResp.json() : null;

      const approveDefault = statusData?.defaultApproveUsdc ?? 10;
      const approveAmount = Math.max(approveDefault, amount).toFixed(6);

      const calldataUrl = `${cleanGatewayUrl}/api/deposit-calldata/${wallet}?amount=${amount.toFixed(6)}&approveAmount=${approveAmount}`;
      const calldataResp = await fetch(calldataUrl);
      const data = await calldataResp.json();
      if (!calldataResp.ok) throw new Error(data.error || "Deposit calldata failed");

      const provider = getInjectedWallet();
      if (!provider) throw new Error("No wallet injection found.");

      const allowance = Number(statusData?.allowance?.formatted || 0);
      if (allowance < amount) {
        setPayStatusText("Requesting USDC allowance approval in wallet...");
        const appTxHash = await provider.request<string>({
          method: "eth_sendTransaction",
          params: [data.approveTx],
        });
        setPayStatusText("Waiting for allowance transaction receipt...");
        await waitForTxReceipt(appTxHash);
        setAllowanceApproved(true);
        saveLocalAction("approve", approveAmount, appTxHash);
      }

      setPayStatusText("Confirm Gateway deposit in your wallet...");
      const depTxHash = await provider.request<string>({
        method: "eth_sendTransaction",
        params: [data.depositTx],
      });
      setPayStatusText("Waiting for deposit transaction confirmation...");
      await waitForTxReceipt(depTxHash);
      setDepositConfirmed(true);
      saveLocalAction("deposit", amount.toFixed(6), depTxHash);

      // Verify balance update
      setPayStatusText("Updating gateway balances...");
      let balanceUpdated = false;
      for (let i = 0; i < 30; i++) {
        const check = await fetch(`${cleanGatewayUrl}/api/balance/${wallet}`);
        if (check.ok) {
          const res = await check.json();
          const normalBal = extractGatewayBalanceUsdc(res) ?? 0;
          if (normalBal >= Number(currentInvoice.amount)) {
            balanceUpdated = true;
            break;
          }
        }
        await new Promise((r) => setTimeout(r, 2000));
      }

      if (!balanceUpdated) throw new Error("Circle Gateway did not settle balance update in time.");
      setPaymentDetails((prev) => ({
        ...prev,
        buyerGatewayBalance: `${Number(currentInvoice.amount).toFixed(6)}+ USDC`,
      }));

      setShowDepositModal(false);
      setPaymentStepStatus((prev) => ({
        ...prev,
        gateway: { status: "completed", label: "Funded" },
        settlement: { status: "active", label: "Sign Settlement" },
      }));
      setPaymentStep("settlement");
      setPayStatusText("Circle deposit successful. Ready to sign settlement.");
    } catch (err: any) {
      showToast(err.message || "Gateway deposit failed.", "error");
      setPayStatusText("Deposit failed. Retry.");
    }
  };

  const waitForTxReceipt = async (hash: string) => {
    const provider = getInjectedWallet();
    if (!provider) return;
    for (let i = 0; i < 45; i++) {
      const rec = await provider.request<any>({
        method: "eth_getTransactionReceipt",
        params: [hash],
      });
      if (rec) {
        if (rec.status !== "0x1") throw new Error("Transaction reverted.");
        return rec;
      }
      await new Promise((r) => setTimeout(r, 1500));
    }
    throw new Error("Receipt timeout");
  };

  const saveLocalAction = (type: string, amount: string, hash: string) => {
    try {
      const key = `qma_wallet_events_${wallet.toLowerCase()}`;
      const events = JSON.parse(localStorage.getItem(key) || "[]");
      events.unshift({
        type,
        amount_usdc: amount,
        tx_hash: hash,
        explorer_url: `https://testnet.arcscan.app/tx/${hash}`,
        at: Date.now(),
      });
      localStorage.setItem(key, JSON.stringify(events.slice(0, 50)));
    } catch (err) {
      console.warn("Failed to write local event log", err);
    }
  };

  const signAndSettleX402 = async () => {
    if (!currentInvoice || !wallet) return;
    setPayErrorText("");
    setPayStatusText("Requesting EIP-712 payment authorization signature...");
    setPaymentStep("settlement");
    setPaymentStepStatus((prev) => ({
      ...prev,
      settlement: { status: "active", label: "Signing" },
    }));

    try {
      const splitLegs = Array.isArray(currentInvoice.split_legs) ? currentInvoice.split_legs : [];
      const splitSettlements: any[] = splitLegs
        .filter((leg: any) => leg.status === "paid" && leg.settlement_id && leg.sidecar_receipt)
        .map((leg: any) => ({
          leg_id: leg.leg_id,
          settlement_id: leg.settlement_id,
          pay_to: leg.pay_to,
          amount_raw: String(leg.amount_raw),
          sidecar_receipt: leg.sidecar_receipt,
        }));

      let settlementId = "";
      let paidAmountUsdc: number | undefined;

      if (splitLegs.length) {
        let workingSplitLegs = splitLegs;
        const paidLegIds = new Set(splitSettlements.map((item) => item.leg_id));
        const pendingLegs = splitLegs.filter((leg: any) => !paidLegIds.has(leg.leg_id) && leg.status !== "paid");
        for (const leg of pendingLegs) {
          setPayStatusText(`Signing ${leg.role || leg.leg_id} split leg...`);
          const paidLeg = await payX402Resource(leg.resource, wallet);
          const legSettlementId = paidLeg.settlement_id || paidLeg.settlementId;
          if (!legSettlementId || !paidLeg.sidecar_receipt) {
            throw new Error(`Split leg ${leg.leg_id} did not return a settlement receipt.`);
          }
          splitSettlements.push({
            leg_id: paidLeg.leg_id || leg.leg_id,
            settlement_id: legSettlementId,
            pay_to: paidLeg.pay_to || leg.pay_to,
            amount_raw: String(paidLeg.amount_raw || leg.amount_raw),
            sidecar_receipt: paidLeg.sidecar_receipt,
          });
          workingSplitLegs = workingSplitLegs.map((item: any) => (
            item.leg_id === (paidLeg.leg_id || leg.leg_id)
              ? {
                  ...item,
                  status: "paid",
                  settlement_id: legSettlementId,
                  sidecar_receipt: paidLeg.sidecar_receipt,
                  gateway_status: paidLeg.gateway_status || paidLeg.status || item.gateway_status,
                }
              : item
          ));
          const updatedInvoice = {
            ...currentInvoice,
            split_legs: workingSplitLegs,
          };
          setCurrentInvoice(updatedInvoice);
          rememberPendingInvoice(
            updatedInvoice,
            activeQuery,
            normalizeTierForCache(updatedInvoice.tier),
            updatedInvoice.provider_id || selectedProviderId,
            wallet
          );
          saveLocalAction("x402_split_leg", String(paidLeg.amount_usdc || leg.amount_usdc || currentInvoice.amount), legSettlementId);
        }
      } else {
        const paidData = await payX402Resource(currentInvoice.arc_gateway_url, wallet);
        settlementId = paidData.settlement_id || paidData.settlementId;
        paidAmountUsdc = Number(paidData.amount_usdc || currentInvoice.amount);
        if (!settlementId) {
          throw new Error("Arc Gateway did not return a settlement id.");
        }
        saveLocalAction("x402_settlement", String(paidAmountUsdc || currentInvoice.amount), settlementId);
      }

      setPaymentStep("report");
      setPaymentStepStatus((prev) => ({
        ...prev,
        settlement: { status: "completed", label: "Settled" },
        report: { status: "active", label: "Verifying" },
      }));
      setPayStatusText("Settlement accepted. Verifying tokens...");

      const verifyResp = await fetch(`${API_BASE_URL}/api/v1/payment/verify?invoice_id=${encodeURIComponent(
        currentInvoice.invoice_id
      )}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          invoice_secret: currentInvoice.invoice_secret,
          payer_address: wallet,
          ...(settlementId ? { settlement_id: settlementId, amount_usdc: paidAmountUsdc } : {}),
          ...(splitSettlements.length ? { split_settlements: splitSettlements } : {}),
        }),
      });

      const verifyData = await verifyResp.json();
      if (!verifyResp.ok) {
        const detail = typeof verifyData.detail === "object" ? JSON.stringify(verifyData.detail) : verifyData.detail;
        throw new Error(detail || "Verification failed");
      }
      if (!verifyData.access_token) {
        throw new Error("QMA verification did not return an access token.");
      }

      setPaymentStepStatus((prev) => ({
        ...prev,
        report: { status: "completed", label: "Unlocked" },
      }));
      setPaymentDetails((prev) => ({
        ...prev,
        settlementId: verifyData.settlement_id || settlementId || splitSettlements.map((item) => item.settlement_id).join(", "),
        sellerAvailable: verifyData.seller_gateway_available_usdc != null
          ? `${Number(verifyData.seller_gateway_available_usdc).toFixed(6)} USDC`
          : prev.sellerAvailable,
        sellerPending: verifyData.seller_gateway_pending_batch_usdc != null
          ? `${Number(verifyData.seller_gateway_pending_batch_usdc).toFixed(6)} USDC`
          : prev.sellerPending,
        txHash: verifyData.transaction_hash || prev.txHash,
        explorerUrl: verifyData.explorer_url || prev.explorerUrl,
      }));
      setPayStatusText("Report unlocked successfully.");
      setPaymentSuccess(true);
      sessionStorage.setItem(`qma_accessToken_${currentInvoice.invoice_id}`, verifyData.access_token);

      await fetchReportContent(currentInvoice.invoice_id, verifyData.access_token, currentInvoice);
      clearPendingInvoice(
        activeQuery,
        normalizeTierForCache(currentInvoice.tier),
        currentInvoice.provider_id || selectedProviderId,
        wallet
      );
    } catch (err: any) {
      setPayErrorText(err.message || "Settlement signature cancelled or failed.");
      setPaymentStepStatus((prev) => ({
        ...prev,
        settlement: { status: "failed", label: "Failed" },
      }));
    }
  };
  const fetchReportContent = async (
    invoiceId: string,
    accessToken: string,
    invoiceOverride?: any,
    queryOverride?: Record<string, any>,
    providerOverride?: string
  ) => {
    try {
      const invoiceForReport = invoiceOverride || currentInvoice;
      const reportQuery = queryOverride || activeQuery;
      const providerForReport = invoiceForReport?.provider_id || providerOverride || selectedProviderId;
      const endpoint =
        invoiceForReport?.tier === "preview"
          ? `/api/v1/providers/${encodeURIComponent(providerForReport)}/preview`
          : `/api/v1/providers/${encodeURIComponent(providerForReport)}/full-report`;

      const resp = await fetch(`${API_BASE_URL}${endpoint}?invoice_id=${encodeURIComponent(invoiceId)}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-QMA-Access-Token": accessToken,
        },
        body: JSON.stringify(reportQuery),
      });

      const reportData = await resp.json();
      if (!resp.ok) throw new Error(reportData.detail || "Could not read report data");

      const normalizedReportQuery = normalizeSignalPayload(reportQuery);
      const reportTier = normalizeTierForCache(invoiceForReport.tier);
      const cachedReportData = {
        ...reportData,
        invoice: reportData.invoice || invoiceForReport,
        provider_id: reportData.provider_id || providerForReport,
        tier: reportData.tier || reportTier,
        query: reportData.query || normalizedReportQuery,
      };

      setUnlockedReport(cachedReportData);
      setPaywallOpen(false);
      setReportCollapsed(false);

      // Cache report locally for wallet
      const key = signalCacheKey(normalizedReportQuery, reportTier, providerForReport);
      localStorage.setItem(
        key,
        JSON.stringify({
          saved_at: Date.now(),
          signal: normalizedReportQuery,
          tier: reportTier,
          provider_id: providerForReport,
          payer_address: wallet,
          invoice: invoiceForReport,
          report: cachedReportData,
        })
      );
      setCacheRevision((value) => value + 1);
    } catch (err: any) {
      showToast("Failed to load report contents: " + err.message, "error");
    }
  };

  const b64encode = (obj: any) => {
    return btoa(JSON.stringify(obj)).replace(/[=+/]/g, "_").slice(0, 96);
  };

  const handleOpenUnlockedReport = () => {
    setPaywallOpen(false);
    setReportCollapsed(false);
  };

  // Agent AI Run
  const handleAgentRun = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!agentPrompt.trim()) return;
    setShowAgentBuyerModal(true);
    setAgentRunning(true);
    setAgentSessionStage("scanning");
    setAgentSelectedPick(null);
    setAgentSessionInvoice(null);
    setAgentVerifyResult(null);
    setAgentTrace([{ text: "Initiating Buyer Agent...", tone: "t-key" }]);

    try {
      // Form recommendation invoice payload
      const resp = await fetch(`${API_BASE_URL}/api/v1/agent/recommendations`);
      const data = await resp.json();
      const pick = data.recommendations?.[0];

      if (!pick) {
        setAgentSessionStage("error");
        setAgentTrace((prev) => [
          ...prev,
          { text: "No anomalies found meeting parameters.", tone: "t-error" },
        ]);
        setAgentRunning(false);
        return;
      }

      const pickTier = recommendationTier(pick);
      const pickProviderId = pick.provider_id || "funding_memory";
      const pickQuery = pick.query || { symbol: pick.symbol };
      setAgentSessionStage("selected");
      setAgentSelectedPick({ ...pick, agent_tier: pickTier, agent_query: pickQuery });

      setAgentTrace((prev) => [
        ...prev,
        { text: `pick:   ${pick.symbol}  score=${pick.score}  tier=${pickTier}`, tone: "t-val" },
      ]);

      // Connect check
      if (!wallet) {
        setAgentSessionStage("error");
        setAgentTrace((prev) => [...prev, { text: "No wallet address provided. Run cancelled.", tone: "t-error" }]);
        setAgentRunning(false);
        return;
      }

      // Form agent invoice quote
      setAgentSessionStage("invoicing");
      setAgentTrace((prev) => [...prev, { text: "invoice: checking resumable payment state...", tone: "t-dim" }]);
      let invData = await refreshPendingInvoice(pickQuery, pickTier, pickProviderId, wallet);
      if (invData?.access_status === "expired" || invData?.access_status === "disputed") {
        clearPendingInvoice(pickQuery, pickTier, pickProviderId, wallet);
        invData = null;
      }
      if (!invData) {
        setAgentTrace((prev) => [...prev, { text: "invoice: requesting provider-bound payment terms...", tone: "t-dim" }]);
        const invResp = await fetch(`${API_BASE_URL}/api/v1/payment/invoice`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...pickQuery,
            provider_id: pickProviderId,
            tier: pickTier,
            buyer_type: "agent",
            synthetic: true,
            agent_label: "copilot",
          }),
        });

        invData = await invResp.json();
        if (!invResp.ok) {
          const detail = typeof invData.detail === "object" ? JSON.stringify(invData.detail) : invData.detail;
          throw new Error(detail || "Invoice creation failed");
        }
      } else {
        setAgentTrace((prev) => [...prev, { text: `invoice: resumed ${invData.invoice_id.slice(0, 10)}...`, tone: "t-green" }]);
      }
      rememberPendingInvoice(invData, pickQuery, pickTier, pickProviderId, wallet);
      setAgentSessionInvoice(invData);
      setAgentTrace((prev) => [
        ...prev,
        { text: `invoice: ${invData.invoice_id.slice(0, 10)}...  amount=${invData.amount} USDC`, tone: "t-dim" },
      ]);

      if (invData.status === "paid" && invData.access_token) {
        setAgentVerifyResult(invData);
        setSelectedProviderId(pickProviderId);
        setActiveQuery(pickQuery);
        setCurrentInvoice(invData);
        await fetchReportContent(invData.invoice_id, invData.access_token, invData, pickQuery, pickProviderId);
        clearPendingInvoice(pickQuery, pickTier, pickProviderId, wallet);
        setAgentTrace((prev) => [...prev, { text: "result:  recovered paid report ok", tone: "t-accent" }]);
        setAgentSessionStage("unlocked");
        return;
      }

      const splitLegs = Array.isArray(invData.split_legs) ? invData.split_legs : [];
      const splitSettlements: any[] = [];
      let settlementId = "";
      let paidAmountUsdc: number | undefined;

      setAgentSessionStage("awaiting_signature");
      setAgentTrace((prev) => [...prev, { text: "signature: wallet prompt opened for x402 authorization", tone: "t-val" }]);
      if (splitLegs.length) {
        let workingSplitLegs = splitLegs;
        for (const leg of splitLegs.filter((item: any) => item.status !== "paid")) {
          const paidLeg = await payX402Resource(leg.resource, wallet);
          const legSettlementId = paidLeg.settlement_id || paidLeg.settlementId;
          if (!legSettlementId || !paidLeg.sidecar_receipt) {
            throw new Error(`Split leg ${leg.leg_id} did not return a settlement receipt.`);
          }
          splitSettlements.push({
            leg_id: paidLeg.leg_id || leg.leg_id,
            settlement_id: legSettlementId,
            pay_to: paidLeg.pay_to || leg.pay_to,
            amount_raw: String(paidLeg.amount_raw || leg.amount_raw),
            sidecar_receipt: paidLeg.sidecar_receipt,
          });
          workingSplitLegs = workingSplitLegs.map((item: any) => (
            item.leg_id === (paidLeg.leg_id || leg.leg_id)
              ? {
                  ...item,
                  status: "paid",
                  settlement_id: legSettlementId,
                  sidecar_receipt: paidLeg.sidecar_receipt,
                  gateway_status: paidLeg.gateway_status || paidLeg.status || item.gateway_status,
                }
              : item
          ));
          invData = { ...invData, split_legs: workingSplitLegs };
          setAgentSessionInvoice(invData);
          rememberPendingInvoice(invData, pickQuery, pickTier, pickProviderId, wallet);
        }
      } else {
        const paidData = await payX402Resource(invData.arc_gateway_url, wallet);
        settlementId = paidData.settlement_id || paidData.settlementId;
        paidAmountUsdc = Number(paidData.amount_usdc || invData.amount);
        if (!settlementId) throw new Error("Arc Gateway did not return a settlement id.");
      }
      setAgentTrace((prev) => [...prev, { text: "pay:     x402 authorization accepted", tone: "t-green" }]);

      // Verify tokens split Leg on backend
      setAgentSessionStage("verifying");
      const verifyResp = await fetch(`${API_BASE_URL}/api/v1/payment/verify?invoice_id=${encodeURIComponent(
        invData.invoice_id
      )}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          invoice_secret: invData.invoice_secret,
          payer_address: wallet,
          ...(settlementId ? { settlement_id: settlementId, amount_usdc: paidAmountUsdc } : {}),
          ...(splitSettlements.length ? { split_settlements: splitSettlements } : {}),
        }),
      });

      const verifyData = await verifyResp.json();
      if (!verifyResp.ok) {
        const detail = typeof verifyData.detail === "object" ? JSON.stringify(verifyData.detail) : verifyData.detail;
        throw new Error(detail || "Verification failed");
      }
      setAgentVerifyResult(verifyData);
      setAgentTrace((prev) => [
        ...prev,
        { text: "result:  JSON report unlocked ok", tone: "t-accent" },
      ]);

      // Load report
      setSelectedProviderId(pickProviderId);
      setActiveQuery(pickQuery);
      setCurrentInvoice(invData);
      await fetchReportContent(invData.invoice_id, verifyData.access_token, invData, pickQuery, pickProviderId);
      clearPendingInvoice(pickQuery, pickTier, pickProviderId, wallet);
      await refreshPlatformTables(1, 1).catch((err) => {
        console.warn("Platform analytics refresh after Copilot payment failed", err);
      });
      setReportCollapsed(false);
      setAgentSessionStage("unlocked");
    } catch (err: any) {
      setAgentSessionStage("error");
      setAgentTrace((prev) => [...prev, { text: `Error: ${err.message || err}`, tone: "t-error" }]);
    } finally {
      setAgentRunning(false);
    }
  };

  const formatPercentage = (val?: number) => {
    if (val == null) return "0.0%";
    return `${val >= 0 ? "+" : ""}${(val * 100).toFixed(1)}%`;
  };

  const formatRawPercent = (val?: number) => {
    if (val == null) return "+0.00%";
    return `${val >= 0 ? "+" : ""}${val.toFixed(2)}%`;
  };

  const formatDateTime = (val?: number | string) => {
    if (val == null) return "";
    if (typeof val === "string") {
      const parsed = Number(val);
      if (!Number.isNaN(parsed)) return formatDateTime(parsed);
      const date = new Date(val);
      return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
    }
    const ms = val > 10_000_000_000 ? val : val * 1000;
    return new Date(ms).toLocaleString();
  };

  const formatUsdc = (value: any, digits = 3) => {
    const num = Number(value || 0);
    return `${Number.isFinite(num) ? num.toFixed(digits) : "0.000"} USDC`;
  };

  const tierLabel = (value: any) => {
    const tier = String(value || "legacy").trim();
    if (!tier) return "Legacy";
    return tier.charAt(0).toUpperCase() + tier.slice(1);
  };

  const gatewayStatusBadge = (status: any) => {
    const raw = String(status || "received");
    const normalized = raw.toLowerCase();
    const color = normalized === "completed" || normalized === "confirmed"
      ? "var(--green)"
      : normalized === "received"
        ? "#f59e0b"
        : "var(--t2)";
    return <span style={{ color, fontWeight: 700 }}>{raw}</span>;
  };

  const renderSettlementRef = (event: any) => {
    const txHash = event?.transaction_hash || event?.tx_hash || event?.settlement_tx_hash;
    const settlementId = event?.settlement_id;
    const isFinalStatus = ["completed", "confirmed"].includes(String(event?.gateway_status || "").toLowerCase());
    if (event?.explorer_url && txHash) {
      return (
        <a className="tx-link" href={event.explorer_url} target="_blank" rel="noreferrer" title={`Settlement: ${settlementId || ""}`}>
          {shortAddress(txHash)}
        </a>
      );
    }
    if (txHash) {
      return (
        <a className="tx-link" href={`https://testnet.arcscan.app/tx/${txHash}`} target="_blank" rel="noreferrer" title={`Settlement: ${settlementId || ""}`}>
          {shortAddress(txHash)}
        </a>
      );
    }
    if (settlementId) {
      return (
        <>
          <span className="mono-td" title={`Settlement ID: ${settlementId}`}>{shortAddress(settlementId)}</span>
          <div style={{ color: isFinalStatus ? "var(--t3)" : "#f59e0b", fontSize: "0.72rem", marginTop: 2 }}>
            {isFinalStatus ? "Arcscan tx unavailable" : "Arcscan tx pending"}
          </div>
        </>
      );
    }
    return <span style={{ color: "var(--t3)" }}>n/a</span>;
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


  return (
    <div className="body">
      {toast ? (
        <div className="toast-container" aria-live="polite">
          <div className={`toast toast-${toast.tone}`}>
            <span className="toast-message">{toast.message}</span>
            <button type="button" className="toast-close" onClick={() => setToast(null)} aria-label="Close notification">
              x
            </button>
          </div>
        </div>
      ) : null}
      <header className="header">
        <div className="logo-section">
          <a
            href="/"
            className="logo-item qma-logo-item"
            title="QMA"
            onClick={(e) => {
              e.preventDefault();
              onNavigate("landing");
            }}
          >
            <div className="logo-icon">QM</div>
            <div className="logo-text">QMA</div>
          </a>
          <span className="logo-tag">v1.0.0</span>

          <span className="header-divider"></span>
          <a href="https://thecanteenapp.com/" target="_blank" rel="noopener noreferrer" className="logo-item logo-img-item canteen-logo-item" title="Canteen">
            <img src="/assets/logos/canteen-logo.png" alt="Canteen" />
          </a>
          <a href="https://www.circle.com/" target="_blank" rel="noopener noreferrer" className="logo-item logo-img-item" title="Circle">
            <img src="/assets/logos/circle-logo-white.svg" alt="Circle" />
          </a>
          <a href="https://www.arc.network/" target="_blank" rel="noopener noreferrer" className="logo-item logo-img-item arc-logo-item" title="Arc Testnet">
            <img src="/assets/logos/arc-logo-white.svg" alt="Arc Testnet" />
          </a>

        </div>

        <div className="status-indicators">
          <div className="indicator" id="clock">
            {timeStr}
          </div>

          <div className="view-toggle" role="group" aria-label="View mode">
            <button
              type="button"
              className={`view-toggle-btn ${viewMode === "basic" ? "active" : ""}`}
              onClick={() => setViewModeState("basic")}
            >
              Simple
            </button>
            <button
              type="button"
              className={`view-toggle-btn ${viewMode === "advanced" ? "active" : ""}`}
              onClick={() => setViewModeState("advanced")}
            >
              Pro
            </button>
          </div>

          <div className="stats-dropdown-container">
            <button
              type="button"
              className="stats-dropdown-btn"
              onClick={() => setStatsDropdownOpen(!statsDropdownOpen)}
            >
              <svg className="dropdown-btn-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="18" y1="20" x2="18" y2="10"></line>
                <line x1="12" y1="20" x2="12" y2="4"></line>
                <line x1="6" y1="20" x2="6" y2="14"></line>
              </svg>
              <span className="dropdown-btn-text">Status & Metrics</span>
              <svg className="dropdown-btn-arrow" width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <polyline points="6 9 12 15 18 9"></polyline>
              </svg>
            </button>

            {statsDropdownOpen && (
              <div className="stats-dropdown-panel" style={{ display: "block" }}>
                <div className="dropdown-section">
                  <div className="dropdown-title">Engine diagnostics</div>
                  <div className="dropdown-row">
                    <span className="indicator-dot"></span>
                    <span style={{ fontWeight: 600, color: "var(--green)" }}>Ledoit-Wolf Active</span>
                  </div>
                  <div className="dropdown-row">
                    <span className="indicator-label">Time Half-life</span>
                    <span className="indicator-value">180 days</span>
                  </div>
                </div>

                <div className="dropdown-section">
                  <div className="dropdown-title">Platform Performance</div>
                  <div className="dropdown-row-single">
                    <span>Paid: {metrics.paid_count}</span>
                  </div>
                  <div className="dropdown-row-single highlight-green" style={{ marginTop: 6 }}>
                    <span>Rev: {Number(metrics.revenue_usdc).toFixed(3)} USDC</span>
                  </div>
                </div>

                <div className="dropdown-section">
                  <div className="dropdown-title">Seller Treasury (USDC)</div>
                  <div className="dropdown-row-single" title="Seller Gateway: funds confirmed on-chain and available to withdraw">
                    <span>Avail: {Number(metrics.available_usdc).toFixed(3)}</span>
                  </div>
                  <div className="dropdown-row-single" style={{ marginTop: 6 }}>
                    <span style={{ color: "var(--t3)" }}>Batch: -</span>
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="wallet-area">
            <button
              className={`wallet-button ${wallet ? "connected" : ""}`}
              onClick={wallet ? () => setWalletDropdownOpen(!walletDropdownOpen) : connect}
              type="button"
            >
              <span>{wallet ? shortAddress(wallet) : "Connect Wallet"}</span>
            </button>

            {walletDropdownOpen && (
              <div className="wallet-menu open">
                <div className="wallet-menu-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div className="wallet-menu-identity">
                    <div className="wallet-menu-identity-row">
                      <div className="wallet-menu-address" title={wallet}>
                        {shortAddress(wallet)}
                      </div>
                      <div className={`wallet-role-label ${walletRole.className}`}>{walletRole.label}</div>
                    </div>
                  </div>
                  <button
                    type="button"
                    className={`wallet-menu-icon-btn ${copySuccess ? "copied" : ""}`}
                    style={{ display: "inline-flex" }}
                    onClick={handleCopyAddress}
                    title="Copy address"
                    aria-label="Copy address"
                  >
                    <svg className="wallet-copy-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                    </svg>
                    <svg className="wallet-copy-check" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M20 6L9 17l-5-5"></path>
                    </svg>
                  </button>
                </div>
                <button type="button" className="wallet-menu-item" onClick={() => { setWalletDropdownOpen(false); onNavigate("profile"); }}>
                  <svg className="wallet-menu-item-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                    <circle cx="12" cy="7" r="4"></circle>
                  </svg>
                  <span>View Profile Page</span>
                </button>
                <button type="button" className="wallet-menu-item" onClick={openQuickProfileModal}>
                  <svg className="wallet-menu-item-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                    <line x1="9" y1="9" x2="15" y2="9"></line>
                    <line x1="9" y1="13" x2="15" y2="13"></line>
                    <line x1="9" y1="17" x2="13" y2="17"></line>
                  </svg>
                  <span>Quick Profile Modal</span>
                </button>
                <button type="button" className="wallet-menu-item" onClick={() => { setWalletDropdownOpen(false); setShowAgentRunModal(true); setAgentRunTraceLines([]); }}>
                  <svg className="wallet-menu-item-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 8V4H8"></path>
                    <rect x="4" y="8" width="16" height="12" rx="2"></rect>
                    <path d="M2 14h2"></path>
                    <path d="M20 14h2"></path>
                    <path d="M9 13h.01"></path>
                    <path d="M15 13h.01"></path>
                  </svg>
                  <span>Agent Run / Judge Mode</span>
                </button>
                <button type="button" className="wallet-menu-item" onClick={() => { setWalletDropdownOpen(false); setShowFundArcModal(true); refreshFundingReadiness(); }}>
                  <svg className="wallet-menu-item-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 2v20"></path>
                    <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7H14a3.5 3.5 0 0 1 0 7H6"></path>
                  </svg>
                  <span>Fund Arc Wallet</span>
                </button>
                <button type="button" className="wallet-menu-item" onClick={() => { setWalletDropdownOpen(false); onNavigate("marketplace"); }}>
                  <svg className="wallet-menu-item-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"></path>
                    <line x1="3" y1="6" x2="21" y2="6"></line>
                    <path d="M16 10a4 4 0 0 1-8 0"></path>
                  </svg>
                  <span>Marketplace</span>
                </button>
                <button type="button" className="wallet-menu-item wallet-menu-item-danger" onClick={disconnect}>
                  <svg className="wallet-menu-item-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
                    <polyline points="16 17 21 12 16 7"></polyline>
                    <line x1="21" y1="12" x2="9" y2="12"></line>
                  </svg>
                  <span>Disconnect</span>
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      <div className="workspace">
        {/* Left Sidebar */}
        <div className="live-feed-sidebar mobile-visible">
          <div className="sidebar-header">
            <span className="sidebar-title">Live Signals</span>
            <button className="refresh-btn" onClick={() => loadLiveAnomalies()}>
              ↻ Refresh
            </button>
          </div>

          {/* Ranked Opportunities */}
          <div className="agent-picks-panel sidebar-panel">
            <div className="sidebar-header agent-picks-header">
              <span className="sidebar-title">Ranked Opportunities</span>
              <span className="agent-mode-pill">Human review</span>
            </div>
            <div className="agent-picks-list">
              {recommendations.length === 0 ? (
                <div className="agent-empty">Ranking live signals...</div>
              ) : (
                recommendations.map((item, idx) => {
                  const providerId = item.provider_id || "funding_memory";
                  const signal = normalizeSignalPayload(item.query || { symbol: item.symbol });
                  const entitlement = entitlementBadgeForSignal(signal, providerId);
                  return (
                    <div
                      className="agent-pick-card"
                      key={idx}
                      onClick={() => {
                        setSelectedProviderId(providerId);
                        setActiveQuery(signal);
                        const exact = getCachedReport(signal, "full", providerId) || getCachedReport(signal, "preview", providerId);
                        if (openCachedReportEntry(exact, signal, providerId)) return;
                        const history = getCachedReportsForSymbol(signal.symbol, providerId);
                        if (history[0] && openCachedReportEntry(history[0], signal, providerId)) {
                          showToast(`Showing previous paid ${signal.symbol} report from ${new Date(history[0].saved_at).toLocaleString()}.`, "info");
                          return;
                        }
                        setUnlockedReport(null);
                        setReportCollapsed(true);
                      }}
                    >
                      <div className="card-header">
                        <span className="card-symbol">{item.symbol}</span>
                        <span className="card-score">Score: {item.score}</span>
                      </div>
                      {item.reason && <p className="pick-reason" style={{ fontSize: "0.68rem", color: "var(--t2)", marginTop: 4 }}>{item.reason}</p>}
                      <div className="card-meta-row" style={{ marginTop: 6 }}>
                        <span>{entitlement.meta || `Tier: ${recommendationTier(item)}`}</span>
                        <span className={`signal-badge ${entitlement.className}`}>
                          {entitlement.className === "unpaid" ? `Tier: ${recommendationTier(item)}` : entitlement.text}
                        </span>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* All Live Signals */}
          <div className="sidebar-header anomalies-header">
            <span className="sidebar-title">All Live Signals</span>
            <span className="anomalies-count-pill">Auto 30s</span>
          </div>

          <div className="anomalies-list">
            {anomaliesLoading ? (
              <div style={{ textAlign: "center", color: "var(--t3)", marginTop: 48 }}>
                <div className="spinner" style={{ margin: "0 auto 12px" }}></div>
                <span style={{ fontFamily: "var(--mono)", fontSize: "0.72rem" }}>Scanning MEXC…</span>
              </div>
            ) : anomaliesError ? (
              <div style={{ textAlign: "center", color: "var(--red)", marginTop: 48 }}>{anomaliesError}</div>
            ) : anomalies.length === 0 ? (
              <div className="agent-empty">No anomalies found.</div>
            ) : (
              anomalies.map((item, idx) => {
                const isActive = activeQuery?.symbol === item.symbol;
                const signal = normalizeSignalPayload({
                  symbol: item.symbol,
                  fundingRate: item.fundingRate,
                  marketCap: item.marketCap,
                  FDV: item.fromATH ? item.marketCap / (1 + item.fromATH / 100) : item.marketCap,
                  circRatio: item.circRatio,
                  fromATH: item.fromATH,
                  volume24h: item.volume24h,
                  amount: item.amount || item.openInterest,
                  openInterest: item.openInterest || item.amount,
                  openInterestChange24h: item.openInterestChange24h,
                  longShortRatio: item.longShortRatio,
                  price: item.price,
                });
                const entitlement = entitlementBadgeForSignal(signal);
                return (
                  <div
                    className={`anomaly-card ${isActive ? "active" : ""}`}
                    key={idx}
                    onClick={() => loadAnomalyIntoQuery(item)}
                  >
                    <div className="card-header">
                      <span className="card-symbol">{item.symbol}</span>
                      <span className="card-funding">{(item.fundingRate * 100).toFixed(3)}%</span>
                    </div>
                    <div className="card-stats">
                      <div>Mkt Cap: <span className="card-stat-val">${(item.marketCap / 1000000).toFixed(1)}M</span></div>
                      <div>Circ Ratio: <span className="card-stat-val">{item.circRatio.toFixed(2)}</span></div>
                      <div>24h Vol: <span className="card-stat-val">${(item.volume24h / 1000000).toFixed(1)}M</span></div>
                      <div>ATH Dist: <span className="card-stat-val">{item.fromATH.toFixed(2)}%</span></div>
                    </div>
                    <div className="card-meta-row">
                      <span>{entitlement.meta}</span>
                      <span className={`signal-badge ${entitlement.className}`}>{entitlement.text}</span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Right main panel */}
        <div className="main-panel">
          {/* Agent Control Bar */}
          <div className="agent-control-bar">
            <div className="agent-bar-info">
              <span className="agent-bar-title">Agent Buyer</span>
              <span className={`agent-status-indicator ${agentRunning ? "active" : "idle"}`}>
                {agentRunning ? "Running" : "Idle"}
              </span>
            </div>
            <form onSubmit={handleAgentRun} className="agent-bar-input-wrap" style={{ display: "flex", flex: 1, gap: 8 }}>
              <input
                type="text"
                className="agent-bar-input"
                value={agentPrompt}
                onChange={(e) => setAgentPrompt(e.target.value)}
                placeholder="e.g. find best funding_memory signal under 0.010 USDC budget"
              />
              <button type="submit" className="agent-bar-submit" disabled={agentRunning}>
                Run Copilot
              </button>
            </form>
            <div className="agent-bar-presets">
              <button
                type="button"
                className="preset-btn"
                onClick={() => setAgentPrompt("find best funding_memory signal under 0.010 USDC")}
              >
                Best Funding
              </button>
              <button
                type="button"
                className="preset-btn"
                onClick={() => setAgentPrompt("find best oi_memory signal under 0.005 USDC")}
              >
                Best OI
              </button>
            </div>
          </div>

          {/* Form / Selected signal card */}
          <div className="query-card-container">
            {viewMode === "basic" ? (
              <div className="basic-signal-card basic-only" id="basic-signal-card" style={{ display: "block" }}>
                <div className="basic-signal-top">
                  <span className="basic-signal-symbol">{activeQuery?.symbol || "HYPE"}</span>
                  <span className="basic-signal-tag">Selected market setup</span>
                </div>
                <p className="basic-signal-lead">
                  {activeQuery?.symbol || "HYPE"} currently shows{" "}
                  {activeQuery?.fundingRate ? `${(activeQuery.fundingRate * 100).toFixed(3)}%` : "0.000%"} funding rate anomaly. QMA will compare this setup with history.
                </p>
                <p className="basic-signal-meta">
                  Summary cost: {quotedPrices.preview ? `${quotedPrices.preview.toFixed(3)} USDC` : "0.001 USDC"}. Full report cost:{" "}
                  {quotedPrices.full ? `${quotedPrices.full.toFixed(3)} USDC` : "0.005 USDC"}.
                </p>
                <button
                  type="button"
                  className="basic-toggle-fields-btn"
                  onClick={() => setShowBasicFields(!showBasicFields)}
                >
                  {showBasicFields ? "Hide fields" : "Edit signal inputs"}
                </button>
              </div>
            ) : null}

            <form
              className="query-form-grid"
              onSubmit={(e) => e.preventDefault()}
              style={{ display: viewMode === "advanced" || showBasicFields ? "block" : "none" }}
            >
              <div className="query-fields-grid" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
                <div className="form-group provider-select-group">
                  <label className="form-label">Provider</label>
                  <select
                    className="form-input provider-select"
                    value={selectedProviderId}
                    onChange={(e) => handleProviderChange(e.target.value)}
                  >
                    {providers.map((p) => (
                      <option value={p.provider_id} key={p.provider_id}>
                        {p.provider_name || p.provider_id}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="form-group">
                  <label className="form-label">Symbol</label>
                  <input
                    type="text"
                    className="form-input"
                    value={activeQuery.symbol || ""}
                    onChange={(e) => setActiveQuery({ ...activeQuery, symbol: e.target.value })}
                  />
                </div>

                {activeProvider?.ui_schema?.fields?.map((f) => (
                  <div className="form-group" key={f.key}>
                    <label className="form-label">{f.label || f.key}</label>
                    <input
                      type={f.type === "number" ? "number" : "text"}
                      step={f.step || "any"}
                      className="form-input"
                      value={activeQuery[f.key] !== undefined ? activeQuery[f.key] : ""}
                      onChange={(e) =>
                        setActiveQuery({
                          ...activeQuery,
                          [f.key]: f.type === "number" ? Number(e.target.value) : e.target.value,
                        })
                      }
                    />
                  </div>
                ))}
              </div>
            </form>

            <div className="query-actions-row" style={{ display: "flex", gap: 12, marginTop: 12 }}>
              <button
                type="button"
                className="submit-btn tier-btn preview-tier"
                onClick={() => openPaywall("preview")}
              >
                <span>Preview Report - {quotedPrices.preview ? `${quotedPrices.preview.toFixed(3)} USDC` : "0.001 USDC"}</span>
              </button>
              <button
                type="button"
                className="submit-btn tier-btn full-tier"
                onClick={() => openPaywall("full")}
              >
                <span>Full Report - {quotedPrices.full ? `${quotedPrices.full.toFixed(3)} USDC` : "0.005 USDC"}</span>
              </button>
            </div>
          </div>

          {/* Viewport reports */}
          <div
            className={`report-viewport ${unlockedReport && !reportCollapsed ? "unlocked" : ""}`}
            id="viewport-container"
            style={{ position: "relative", minHeight: 300 }}
          >
            {/* PAYWALL */}
            {paywallOpen && currentInvoice && (
              <div className="paywall-overlay" id="paywall-element" style={{ display: "flex" }}>
                <div className="paywall-card">
                  <button className="paywall-close" type="button" onClick={() => setPaywallOpen(false)}>
                    x
                  </button>
                  <div className="paywall-layout">
                    <div className="paywall-main">
                      <div className="paywall-title">
                        {paymentSuccess ? "Payment Confirmed" : "Unlock this report"}
                      </div>
                      <div className="paywall-desc">
                        {paymentSuccess
                          ? "Settlement complete. Your report is ready."
                          : "QMA matches today's market setup against similar past events and shows how they played out: win rates, typical returns, and historical analogs."}
                      </div>

                      <div className="circle-invoice-details">
                        <div className="invoice-row">
                          <span className="invoice-label">Signal</span>
                          <span className="invoice-val">{currentInvoice.symbol || activeQuery.symbol}</span>
                        </div>
                        <div className="invoice-row invoice-row--amount">
                          <span className="invoice-label">Amount</span>
                          <span className="invoice-val">{Number(currentInvoice.amount).toFixed(3)} USDC</span>
                        </div>
                        <div className="invoice-row">
                          <span className="invoice-label">Tier</span>
                          <span className="invoice-val">{currentInvoice.tier === "preview" ? "Preview Report" : "Full Report"}</span>
                        </div>
                        <div className="invoice-row">
                          <span className="invoice-label">Network</span>
                          <span className="invoice-val">Arc Testnet</span>
                        </div>
                      </div>

                      {/* Payment step timeline progress */}
                      <div className="payment-flow-panel" style={{ display: "block", marginTop: 12 }}>
                        <div className="pf-header-label">Payment Progress</div>
                        <div className="pf-timeline">
                          <div className={`pf-row ${paymentClass(paymentStepStatus.wallet.status)} ${paymentStep === "wallet" ? "is-current" : ""}`} data-payment-step="wallet">
                            <div className="pf-step-icon" />
                            <div className="pf-body">
                              <div className="pf-step-top">
                                <div className="pf-label">Wallet Connected</div>
                                <span className={`pf-badge ${paymentClass(paymentStepStatus.wallet.status)}`}>
                                  {paymentStepStatus.wallet.label}
                                </span>
                              </div>
                              <div className="pf-val">
                                {wallet ? `Connected as ${shortAddress(wallet)}` : "Connect wallet to continue."}
                              </div>
                            </div>
                          </div>

                          <div className={`pf-row ${paymentClass(paymentStepStatus.gateway.status)} ${paymentStep === "gateway" ? "is-current" : ""}`} data-payment-step="gateway">
                            <div className="pf-step-icon" />
                            <div className="pf-body">
                              <div className="pf-step-top">
                                <div className="pf-label">Deposit USDC</div>
                                <span className={`pf-badge ${paymentClass(paymentStepStatus.gateway.status)}`}>
                                  {paymentStepStatus.gateway.label}
                                </span>
                              </div>
                              <div className="pf-val">
                                {paymentDetails.buyerGatewayBalance
                                  ? `Gateway balance checked: ${paymentDetails.buyerGatewayBalance}`
                                  : "Gateway balance is checked when you pay."}
                              </div>
                            </div>
                          </div>

                          <div className={`pf-row ${paymentClass(paymentStepStatus.settlement.status)} ${paymentStep === "settlement" ? "is-current" : ""}`} data-payment-step="settlement">
                            <div className="pf-step-icon" />
                            <div className="pf-body">
                              <div className="pf-step-top">
                                <div className="pf-label">Settlement</div>
                                <span className={`pf-badge ${paymentClass(paymentStepStatus.settlement.status)}`}>
                                  {paymentStepStatus.settlement.label}
                                </span>
                              </div>
                              <div className="pf-val">
                                {paymentDetails.settlementId
                                  ? `Settlement ID: ${shortAddress(paymentDetails.settlementId)}`
                                  : "Awaiting payment."}
                              </div>
                            </div>
                          </div>

                          <div className={`pf-row ${paymentClass(paymentStepStatus.report.status)} ${paymentStep === "report" ? "is-current" : ""}`} data-payment-step="report">
                            <div className="pf-step-icon" />
                            <div className="pf-body">
                              <div className="pf-step-top">
                                <div className="pf-label">Report Unlocked</div>
                                <span className={`pf-badge ${paymentClass(paymentStepStatus.report.status)}`}>
                                  {paymentStepStatus.report.label}
                                </span>
                              </div>
                              <div className="pf-val">
                                {paymentSuccess ? "Wallet-bound report access issued." : "Report opens after QMA verifies the settlement."}
                              </div>
                            </div>
                          </div>
                        </div>
                      </div>

                      <div className="status-messages" style={{ marginTop: 8 }}>
                        {payStatusText && <p style={{ fontSize: "0.76rem", color: "var(--t2)" }}>{payStatusText}</p>}
                        {payErrorText && <p style={{ fontSize: "0.76rem", color: "var(--red)" }}>{payErrorText}</p>}
                      </div>
                      <div className="testnet-help">
                        <div className="testnet-help-copy">
                          <strong className="testnet-help-title">Need Arc USDC?</strong>
                        </div>
                        <button type="button" className="testnet-help-action" onClick={() => { setShowFundArcModal(true); refreshFundingReadiness(); }}>
                          Open Funding Assistant
                        </button>
                      </div>
                      <p className="paywall-snapshot-note">
                        This exact paid snapshot is saved to Wallet History. If the live signal changes later, reopen this snapshot or unlock the new one.
                      </p>
                      <div className="paywall-trust-layer">
                        <div className="paywall-trust-title">Wallet connection only exposes your public address.</div>
                        <div className="paywall-trust-links">
                          <a href={`${API_BASE_URL}/docs`} target="_blank" rel="noreferrer">API docs</a>
                          <a href="https://testnet.arcscan.app/" target="_blank" rel="noreferrer">Arcscan</a>
                        </div>
                      </div>
                    </div>

                    {/* Paywall Side Details */}
                    <div className="paywall-side">
                      <div className="paywall-advanced-card">
                        <div className="paywall-advanced-title">Advanced Payment Details</div>
                        <div className="paywall-detail-row">
                          <span className="paywall-detail-label">Invoice ID</span>
                          <span className="paywall-detail-value">{currentInvoice.invoice_id}</span>
                        </div>
                        <div className="paywall-detail-row">
                          <span className="paywall-detail-label">Gateway Contract</span>
                          <span className="paywall-detail-value">{shortAddress(gatewayContractAddress)}</span>
                        </div>
                        <div className="paywall-detail-row">
                          <span className="paywall-detail-label">Seller Treasury</span>
                          <span className="paywall-detail-value">{shortAddress(sellerAddress)}</span>
                        </div>
                        <div className="paywall-detail-row">
                          <span className="paywall-detail-label">Settlement ID</span>
                          <span className="paywall-detail-value">{paymentDetails.settlementId ? shortAddress(paymentDetails.settlementId) : "-"}</span>
                        </div>
                        <div className="paywall-detail-row">
                          <span className="paywall-detail-label">Gateway Balance</span>
                          <span className="paywall-detail-value">{paymentDetails.buyerGatewayBalance || "-"}</span>
                        </div>
                        <div className="paywall-detail-row">
                          <span className="paywall-detail-label">Available Balance</span>
                          <span className="paywall-detail-value">{paymentDetails.sellerAvailable || "-"}</span>
                        </div>
                        <div className="paywall-detail-row">
                          <span className="paywall-detail-label">Pending Balance</span>
                          <span className="paywall-detail-value">{paymentDetails.sellerPending || "-"}</span>
                        </div>
                        <div className="paywall-detail-row">
                          <span className="paywall-detail-label">Wallet Address</span>
                          <span className="paywall-detail-value">{wallet ? shortAddress(wallet) : "-"}</span>
                        </div>
                        {paymentDetails.txHash ? (
                          <div className="paywall-detail-row">
                            <span className="paywall-detail-label">Arcscan Tx</span>
                            <a className="paywall-detail-value tx-link" href={paymentDetails.explorerUrl || `https://testnet.arcscan.app/tx/${paymentDetails.txHash}`} target="_blank" rel="noreferrer">
                              {shortAddress(paymentDetails.txHash)}
                            </a>
                          </div>
                        ) : null}
                      </div>
                    </div>
                  </div>
                  {paymentSuccess ? (
                    <button className="simulate-pay-btn" onClick={handleOpenUnlockedReport}>
                      <span>Open Report</span>
                    </button>
                  ) : (
                    <button
                      className="simulate-pay-btn"
                      onClick={signAndSettleX402}
                      disabled={paymentStepStatus.gateway.status !== "completed"}
                    >
                      <span>Pay on Arc Testnet</span>
                    </button>
                  )}
                </div>
              </div>
            )}

            {/* TOP UP MODAL */}
            {showDepositModal && (
              <div className="modal-backdrop open">
                <div className="modal-panel withdraw-modal" style={{ width: 420 }}>
                  <div className="modal-header">
                    <span className="modal-title">Deposit USDC to Circle Gateway</span>
                    <button type="button" className="icon-button" onClick={() => setShowDepositModal(false)}>
                      x
                    </button>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                    <p style={{ fontSize: "0.78rem", color: "var(--t2)" }}>
                      Your Circle Gateway balance is insufficient for this purchase. Choose an amount to deposit.
                    </p>
                    <label>
                      <span className="withdraw-label">Deposit amount (USDC)</span>
                      <input
                        type="number"
                        className="withdraw-input"
                        value={depositAmountInput}
                        onChange={(e) => setDepositAmountInput(e.target.value)}
                      />
                    </label>
                    <div className="deposit-quick-row">
                      <button
                        type="button"
                        className="deposit-quick-btn"
                        onClick={() => setDepositAmountInput(Number(currentInvoice?.amount || 0.005).toFixed(6))}
                      >
                        Exact Cost
                      </button>
                      <button type="button" className="deposit-quick-btn" onClick={() => setDepositAmountInput("0.005")}>
                        0.005 USDC
                      </button>
                      <button type="button" className="deposit-quick-btn" onClick={() => setDepositAmountInput("0.1")}>
                        0.10 USDC
                      </button>
                    </div>

                    {payStatusText && (
                      <p style={{ fontSize: "0.76rem", color: "var(--t2)", marginTop: 6 }}>{payStatusText}</p>
                    )}

                    <div className="withdraw-actions" style={{ marginTop: 12 }}>
                      <button type="button" className="submit-btn" onClick={handleDepositToGateway}>
                        Deposit
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* REPORT VIEW */}
            {unlockedReport && !reportCollapsed ? (
              <div className="report-container" id="report-view-element" style={{ display: "grid" }}>
                {/* Simple summary */}
                <div className="report-section section-span-all basic-summary-section">
                  <div className="section-header">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                      <polyline points="14 2 14 8 20 8" />
                      <line x1="16" y1="13" x2="8" y2="13" />
                      <line x1="16" y1="17" x2="8" y2="17" />
                    </svg>
                    Your result at a glance
                  </div>
                  <p className="plain-summary">
                    {unlockedReport.query_symbol || activeQuery.symbol} is being compared with{" "}
                    {unlockedReport.matched_k || unlockedReport.analogs?.length || 0} similar historical events in a{" "}
                    {unlockedReport.regime_cluster || "regime cluster"} context. In those past cases, outcomes were{" "}
                    {Number(unlockedReport.weighted_win_rate ?? unlockedReport.rough_win_rate) >= 60
                      ? "mostly positive"
                      : "mixed"}{" "}
                    with a {((unlockedReport.weighted_win_rate ?? unlockedReport.rough_win_rate) || 0).toFixed(1)}% win
                    rate.
                  </p>
                  <div className="summary-card-grid">
                    <div className="summary-card">
                      <span className="summary-card-label">Confidence</span>
                      <strong className="summary-card-value">
                        {unlockedReport.is_ood ? "Low" : "High"}
                      </strong>
                      <small className="summary-card-desc">How familiar this setup looks in history</small>
                    </div>
                    <div className="summary-card">
                      <span className="summary-card-label">Similar events</span>
                      <strong className="summary-card-value">
                        {(unlockedReport.matched_k ?? unlockedReport.analogs?.length) ?? 0}
                      </strong>
                      <small className="summary-card-desc">Historical matches in QMA's dataset</small>
                    </div>
                    <div className="summary-card">
                      <span className="summary-card-label">Win rate</span>
                      <strong className="summary-card-value">
                        {((unlockedReport.weighted_win_rate ?? unlockedReport.rough_win_rate) ?? 0).toFixed(1)}%
                      </strong>
                      <small className="summary-card-desc">How often similar cases finished positive</small>
                    </div>
                    <div className="summary-card">
                      <span className="summary-card-label">Typical outcome</span>
                      <strong className="summary-card-value">
                        {unlockedReport.percentiles?.P50_median
                          ? `${unlockedReport.percentiles.P50_median.toFixed(2)}%`
                          : "n/a"}
                      </strong>
                      <small className="summary-card-desc">Median peak result in past analogs</small>
                    </div>
                  </div>
                </div>

                {/* Weighted outcome KPI */}
                <div className="report-section section-span-2 advanced-control">
                  <div className="section-header">Historical Analog Outcome (Weighted)</div>
                  <div className="kpi-grid">
                    <div className="kpi-card">
                      <span className="kpi-title">Analog Win Rate</span>
                      <div className="kpi-value" style={{ color: "var(--green)" }}>
                        {(unlockedReport.weighted_win_rate || 0).toFixed(1)}%
                      </div>
                      <span className="kpi-sub">
                        95% CI: [
                        {unlockedReport.win_rate_confidence_interval
                          ? unlockedReport.win_rate_confidence_interval.map((x: number) => (x * 100).toFixed(1)).join(" – ")
                          : "0.0% – 0.0%"}
                        ]%
                      </span>
                    </div>
                    <div className="kpi-card">
                      <span className="kpi-title">Avg Historical Peak PnL</span>
                      <div className="kpi-value" style={{ color: "var(--green)" }}>
                        {formatRawPercent(unlockedReport.weighted_avg_profit)}
                      </div>
                      <span className="kpi-sub">
                        95% CI: [
                        {unlockedReport.avg_profit_confidence_interval
                          ? unlockedReport.avg_profit_confidence_interval.map((x: number) => x.toFixed(2)).join("% – ")
                          : "+0.0% – +0.0%"}
                        ]%
                      </span>
                    </div>
                  </div>
                </div>

                {/* Regime details */}
                <div className="report-section advanced-control">
                  <div className="section-header">Similar Historical Regime</div>
                  <div className="info-list">
                    <div className="info-item">
                      <span className="info-label" style={{ fontWeight: 600, fontSize: "0.9rem", color: "var(--t1)" }}>
                        {unlockedReport.regime_cluster || "n/a"}
                      </span>
                    </div>
                    <div className="info-desc" style={{ fontSize: "0.76rem", lineHeight: 1.5 }}>
                      {unlockedReport.regime_description || "Regime details loaded from matching catalogs."}
                    </div>
                    <div style={{ borderTop: "1px solid var(--bdr)", paddingTop: 10, marginTop: 4 }}>
                      <div className="info-item">
                        <span className="info-label">OOD Status</span>
                        <span className="pnl-badge" style={{ fontSize: "0.68rem" }}>
                          {unlockedReport.is_ood ? "Out-of-Distribution" : "In-Distribution"}
                        </span>
                      </div>
                      <div className="info-item" style={{ marginTop: 6 }}>
                        <span className="info-label">Chi2 p-value</span>
                        <span className="mono-td" style={{ color: "var(--t1)", fontSize: "0.78rem" }}>
                          {(unlockedReport.ood_chi2_p || 1.0).toFixed(5)}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Advanced details toggler */}
                <div className="advanced-only section-span-all advanced-dropdown-wrapper" style={{ marginTop: 12 }}>
                  <div className="report-section">
                    <div className="section-header">Historical Outcome Percentiles</div>
                    <div className="dist-chart">
                      {["P90", "P75", "P50_median", "P25", "P10"].map((percentile) => {
                        const val = unlockedReport.percentiles?.[percentile] || 0;
                        const fillWidth = Math.min(Math.max((val + 50) * 1.5, 0), 100);
                        return (
                          <div className="dist-row" key={percentile}>
                            <span className="dist-label">{percentile}</span>
                            <div className="dist-bar-bg">
                              <div className="dist-bar-fill" style={{ width: `${fillWidth}%` }}></div>
                            </div>
                            <span className="dist-val">{val.toFixed(2)}%</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  <div className="report-section section-span-2" style={{ marginTop: 12 }}>
                    <div className="section-header">Historical Analog Matches</div>
                    <div className="table-wrap">
                      <table className="activity-table">
                        <thead>
                          <tr>
                            <th>Asset</th>
                            <th>Historical Funding</th>
                            <th>Market Cap</th>
                            <th>Settle Age</th>
                            <th>Decay Wt.</th>
                            <th>Similarity</th>
                            <th>Outcome PnL</th>
                          </tr>
                        </thead>
                        <tbody>
                          {unlockedReport.analogs?.map((analog: any, analogIdx: number) => (
                            <tr key={analogIdx}>
                              <td className="mono-td" style={{ fontWeight: 600 }}>{analog.symbol}</td>
                              <td className="mono-td">{analog.fundingRate != null ? `${(Number(analog.fundingRate) * 100).toFixed(3)}%` : "n/a"}</td>
                              <td className="mono-td">{analog.marketCap != null ? `$${(Number(analog.marketCap) / 1_000_000).toFixed(1)}M` : "n/a"}</td>
                              <td className="mono-td">{analog.age_days != null ? `${Math.round(Number(analog.age_days))}d ago` : formatDateTime(analog.timestamp || analog.time)}</td>
                              <td className="mono-td">{analog.decay_weight != null ? Number(analog.decay_weight).toFixed(3) : "n/a"}</td>
                              <td className="mono-td">{analog.similarity != null ? `${(Number(analog.similarity) * 100).toFixed(2)}%` : "n/a"}</td>
                              <td>
                                <span className={`pnl-badge ${Number(analog.profit_pct ?? analog.peak_pnl ?? analog.pnl ?? 0) >= 0 ? "win" : "loss"}`}>
                                  {formatRawPercent(analog.profit_pct ?? analog.peak_pnl ?? analog.pnl)}
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  <div className="report-section section-span-all" style={{ marginTop: 12 }}>
                    <div className="section-header">Evidence Quality Diagnostics</div>
                    <div className="diagnostic-grid">
                      <div className="diagnostic-tile">
                        <span className="diagnostic-label">Clean Joined Rows</span>
                        <span className="diagnostic-value">
                          {`${unlockedReport.data_quality?.clean_joined_rows || 0} / ${unlockedReport.data_quality?.historical_feature_rows || 0}`}
                        </span>
                      </div>
                      <div className="diagnostic-tile">
                        <span className="diagnostic-label">Matched K / ESS</span>
                        <span className="diagnostic-value">
                          {`${unlockedReport.matched_k || 0} / ${Number(unlockedReport.effective_sample_size || 0).toFixed(1)}`}
                        </span>
                      </div>
                      <div className="diagnostic-tile">
                        <span className="diagnostic-label">Nearest Distance</span>
                        <span className="diagnostic-value">
                          {`${Number(unlockedReport.distance_summary?.nearest || 0).toFixed(3)} nearest`}
                        </span>
                      </div>
                      <div className="diagnostic-tile">
                        <span className="diagnostic-label">Empirical OOD %ile</span>
                        <span className="diagnostic-value">
                          {`${Number(unlockedReport.ood_empirical_percentile || 0).toFixed(1)}%`}
                        </span>
                      </div>
                    </div>
                    <div className="risk-list">
                      {unlockedReport.provider_note ? <div className="risk-item">{unlockedReport.provider_note}</div> : null}
                      {unlockedReport.analysis_focus ? <div className="risk-item">Analysis focus: {unlockedReport.analysis_focus}</div> : null}
                      {unlockedReport.invoice?.explorer_url && unlockedReport.invoice?.transaction_hash ? (
                        <div className="risk-item">
                          <span style={{ color: "var(--green)" }}>Arcscan batch tx confirmed:</span>{" "}
                          <a className="tx-link" href={unlockedReport.invoice.explorer_url} target="_blank" rel="noreferrer">
                            {shortAddress(unlockedReport.invoice.transaction_hash)}
                          </a>
                        </div>
                      ) : unlockedReport.invoice?.settlement_id ? (
                        <div className="risk-item">
                          <span style={{ color: "#f59e0b" }}>Circle accepted payment.</span> Arcscan batch tx is pending. Settlement ID:{" "}
                          <span className="mono-td">{shortAddress(unlockedReport.invoice.settlement_id)}</span>
                        </div>
                      ) : null}
                      {[...(unlockedReport.risk_flags || []), ...(unlockedReport.validation_warnings || [])].map((item: string, idx: number) => (
                        <div className="risk-item" key={idx}>{item}</div>
                      ))}
                      {!(unlockedReport.risk_flags || []).length && !(unlockedReport.validation_warnings || []).length && !unlockedReport.provider_note ? (
                        <div className="risk-item">No additional provider warnings for this report.</div>
                      ) : null}
                    </div>
                  </div>
                </div>

                <details
                  className="report-section section-span-all platform-stats-section"
                  style={{ paddingBottom: 0 }}
                  onToggle={(event) => {
                    if ((event.currentTarget as HTMLDetailsElement).open) {
                      refreshPlatformTables(1, 1);
                    }
                  }}
                >
                  <summary className="section-header" style={{ cursor: "pointer", userSelect: "none" }}>
                    Platform Analytics & Payment Activity <span style={{ fontSize: "0.65rem", color: "var(--t3)", fontWeight: 400 }}>(Click to view)</span>
                  </summary>
                  {platformTablesError ? (
                    <div className="risk-item" style={{ marginTop: 12, color: "var(--orange)" }}>{platformTablesError}</div>
                  ) : null}
                  <div className="seller-balance-grid" style={{ marginTop: 16 }}>
                    <div className="balance-tile green">
                      <span className="balance-tile-label">Seller Gateway - Available</span>
                      <span className="balance-tile-val">
                        {platformSummary?.seller_gateway_balance?.available_usdc != null
                          ? formatUsdc(platformSummary.seller_gateway_balance.available_usdc, 6)
                          : paymentDetails.sellerAvailable || "n/a"}
                      </span>
                      <span className="balance-tile-sub">On-chain confirmed, withdrawable</span>
                    </div>
                    <div className="balance-tile amber">
                      <span className="balance-tile-label">Seller Gateway - Pending Batch</span>
                      <span className="balance-tile-val">
                        {platformSummary?.seller_gateway_balance?.pending_batch_usdc != null
                          ? formatUsdc(platformSummary.seller_gateway_balance.pending_batch_usdc, 6)
                          : paymentDetails.sellerPending || "n/a"}
                      </span>
                      <span className="balance-tile-sub">Circle accepted, awaiting on-chain batch</span>
                    </div>
                    <div className="balance-tile neutral">
                      <span className="balance-tile-label">Seller Treasury Wallet</span>
                      <span className="balance-tile-val">{platformSummary?.seller_address || sellerAddress ? shortAddress(platformSummary?.seller_address || sellerAddress) : "n/a"}</span>
                      <span className="balance-tile-sub">Final destination after batch settlement</span>
                    </div>
                  </div>
                  <div className="split-tables">
                    <div className="split-table-col split-table-col--settlements">
                      <div className="subsection-title">
                        Recent Settlements
                        {platformPaymentsTotal ? <span style={{ color: "var(--t3)", marginLeft: 8 }}>({platformPaymentsTotal})</span> : null}
                      </div>
                      <div style={{ overflowX: "auto" }}>
                        <table className="activity-table">
                          <thead>
                            <tr>
                              <th>Symbol</th>
                              <th>Provider</th>
                              <th>Payer</th>
                              <th>Amount</th>
                              <th>Circle Status</th>
                              <th>Settlement / Arcscan Tx</th>
                            </tr>
                          </thead>
                          <tbody>
                            {platformTablesLoading && !platformPayments.length ? (
                              <tr><td colSpan={6} style={{ color: "var(--t3)", textAlign: "center" }}>Loading payments...</td></tr>
                            ) : platformPayments.length ? (
                              platformPayments.map((event, idx) => (
                                <tr key={event.event_id || event.settlement_id || event.invoice_id || idx}>
                                  <td className="mono-td">
                                    {event.symbol || "n/a"}
                                    <div style={{ color: "var(--t3)", fontSize: "0.66rem", marginTop: 2 }}>{formatDateTime(event.paid_at)}</div>
                                  </td>
                                  <td><span className="provider-badge">{event.provider_id || "funding_memory"}</span></td>
                                  <td title={event.payer_address || ""}>{event.payer_address ? shortAddress(event.payer_address) : "n/a"}</td>
                                  <td>
                                    {formatUsdc(event.amount_usdc)}
                                    <div style={{ color: "var(--t3)", fontSize: "0.66rem" }}>{tierLabel(event.tier_category || event.tier)}</div>
                                  </td>
                                  <td>{gatewayStatusBadge(event.gateway_status)}</td>
                                  <td className="mono-td">{renderSettlementRef(event)}</td>
                                </tr>
                              ))
                            ) : (
                              <tr><td colSpan={6} style={{ color: "var(--t3)", textAlign: "center" }}>No payments yet.</td></tr>
                            )}
                          </tbody>
                        </table>
                      </div>
                      <div className="table-pager profile-pager">
                        <button type="button" className="refresh-btn" disabled={platformPaymentsPage <= 1 || platformTablesLoading} onClick={() => changePlatformPaymentsPage(Math.max(1, platformPaymentsPage - 1))}>
                          Prev
                        </button>
                        <span style={{ margin: "0 10px", fontSize: "0.8rem" }}>Page {platformPaymentsPage} / {platformPaymentsTotalPages}</span>
                        <button type="button" className="refresh-btn" disabled={platformPaymentsPage >= platformPaymentsTotalPages || platformTablesLoading} onClick={() => changePlatformPaymentsPage(Math.min(platformPaymentsTotalPages, platformPaymentsPage + 1))}>
                          Next
                        </button>
                      </div>
                    </div>
                    <div className="split-table-col split-table-col--wallets">
                      <div className="subsection-title">Wallet Usage</div>
                      <div style={{ overflowX: "auto" }}>
                        <table className="activity-table">
                          <thead>
                            <tr>
                              <th>Wallet</th>
                              <th>Providers</th>
                              <th>Signals</th>
                              <th>Spent</th>
                            </tr>
                          </thead>
                          <tbody>
                            {platformTablesLoading && !platformPayers.length ? (
                              <tr><td colSpan={4} style={{ color: "var(--t3)", textAlign: "center" }}>Loading wallets...</td></tr>
                            ) : platformPayers.length ? (
                              platformPayers.map((payer, idx) => {
                                const symbols = (payer.symbols || []).slice(0, 5).join(", ") || "n/a";
                                const overflow = (payer.symbols || []).length > 5 ? ` +${payer.symbols.length - 5}` : "";
                                const providers = (payer.providers || []).join(", ") || "funding_memory";
                                return (
                                  <tr key={payer.payer_address || idx} title={`Last paid: ${formatDateTime(payer.last_paid_at)}`}>
                                    <td className="mono-td" title={payer.payer_address || ""}>{payer.payer_address ? shortAddress(payer.payer_address) : "n/a"}</td>
                                    <td style={{ fontSize: "0.75rem" }}>{providers}</td>
                                    <td>{payer.payments || 0} / {symbols}{overflow}</td>
                                    <td>
                                      {formatUsdc(payer.spent_usdc)}
                                      <div style={{ color: "var(--t3)", fontSize: "0.66rem" }}>P:{payer.preview_count || 0} F:{payer.full_count || 0}</div>
                                    </td>
                                  </tr>
                                );
                              })
                            ) : (
                              <tr><td colSpan={4} style={{ color: "var(--t3)", textAlign: "center" }}>No wallet activity yet.</td></tr>
                            )}
                          </tbody>
                        </table>
                      </div>
                      <div className="table-pager profile-pager">
                        <button type="button" className="refresh-btn" disabled={platformPayersPage <= 1 || platformTablesLoading} onClick={() => changePlatformPayersPage(Math.max(1, platformPayersPage - 1))}>
                          Prev
                        </button>
                        <span style={{ margin: "0 10px", fontSize: "0.8rem" }}>Page {platformPayersPage} / {platformPayersTotalPages}{platformPayersTotal ? ` (${platformPayersTotal})` : ""}</span>
                        <button type="button" className="refresh-btn" disabled={platformPayersPage >= platformPayersTotalPages || platformTablesLoading} onClick={() => changePlatformPayersPage(Math.min(platformPayersTotalPages, platformPayersPage + 1))}>
                          Next
                        </button>
                      </div>
                    </div>
                  </div>
                  <div className="split-table-col creator-split-ledger">
                    <div className="subsection-title">Marketplace Revenue Ledger</div>
                    <div style={{ overflowX: "auto" }}>
                      <table className="activity-table">
                        <thead>
                          <tr>
                            <th>Provider</th>
                            <th>Gross</th>
                            <th>Creator Earned</th>
                            <th>Platform Fee</th>
                            <th>Claimable</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(platformSummary?.revenue_by_provider || []).length ? (
                            platformSummary.revenue_by_provider.map((row: any, idx: number) => {
                              const sharePct = Number(row.creator_share_bps || 0) / 100;
                              return (
                                <tr key={row.provider_id || idx} title={row.split_note || "Ledger estimate only."}>
                                  <td className="mono-td" title={row.owner_wallet || ""}>
                                    {row.provider_name || row.provider_id || "provider"}
                                    <div style={{ color: "var(--t3)", fontSize: "0.66rem" }}>{row.owner_wallet ? shortAddress(row.owner_wallet) : "n/a"}</div>
                                  </td>
                                  <td>{formatUsdc(row.revenue_usdc)}<div style={{ color: "var(--t3)", fontSize: "0.66rem" }}>{row.payments || 0} sales</div></td>
                                  <td>{formatUsdc(row.creator_earned_usdc)}<div style={{ color: "var(--t3)", fontSize: "0.66rem" }}>{sharePct.toFixed(1)}%</div></td>
                                  <td>{formatUsdc(row.platform_fee_usdc)}</td>
                                  <td>{formatUsdc(row.creator_claimable_usdc)}<div style={{ color: "var(--t3)", fontSize: "0.66rem" }}>ledger only</div></td>
                                </tr>
                              );
                            })
                          ) : (
                            <tr><td colSpan={5} style={{ color: "var(--t3)", textAlign: "center" }}>No creator revenue yet.</td></tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </details>
              </div>
            ) : (
              <div className="empty-state" style={{ textAlign: "center", color: "var(--t3)", marginTop: 80 }}>
                No signal selected yet or payment pending.
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Render Modals */}
      {showAgentBuyerModal && (
        <div className="modal-backdrop open agent-buyer-backdrop" style={{ display: "flex" }}>
          <div className="agent-buyer-modal" role="dialog" aria-modal="true" aria-labelledby="agent-buyer-title">
            <div className="agent-buyer-header">
              <div>
                <div className="agent-buyer-eyebrow">QMA Buyer Agent</div>
                <div className="agent-buyer-title" id="agent-buyer-title">Live report purchase session</div>
                <div className="agent-buyer-subtitle">
                  The agent ranks opportunities, creates an invoice, then asks your wallet to authorize x402 payment.
                </div>
              </div>
              <button
                className="icon-button"
                type="button"
                title="Close"
                onClick={() => setShowAgentBuyerModal(false)}
              >
                x
              </button>
            </div>

            <div className={`agent-session-stage stage-${agentSessionStage}`}>
              {[
                ["scanning", "Scan"],
                ["selected", "Pick"],
                ["invoicing", "Invoice"],
                ["awaiting_signature", "Signature"],
                ["verifying", "Verify"],
                ["unlocked", "Unlocked"],
              ].map(([stage, label]) => {
                const order = ["scanning", "selected", "invoicing", "awaiting_signature", "verifying", "unlocked"];
                const current = order.indexOf(agentSessionStage);
                const index = order.indexOf(stage);
                const isDone = current > index || agentSessionStage === "unlocked";
                const isActive = agentSessionStage === stage;
                return (
                  <div className={`agent-stage-dot ${isDone ? "done" : ""} ${isActive ? "active" : ""}`} key={stage}>
                    <span />
                    {label}
                  </div>
                );
              })}
            </div>

            <div className="agent-buyer-grid">
              <section className="agent-chat-panel">
                <div className="agent-chat-topline">
                  <span className={`agent-live-pill ${agentRunning ? "active" : agentSessionStage === "error" ? "error" : ""}`}>
                    {agentRunning ? "agent running" : agentSessionStage === "error" ? "needs attention" : "session ready"}
                  </span>
                  <span className="agent-chat-wallet">{wallet ? shortAddress(wallet) : "wallet not connected"}</span>
                </div>
                <div className="agent-chat-log" role="log" aria-live="polite">
                  {agentTrace.length ? (
                    agentTrace.map((line, idx) => (
                      <div className={`agent-chat-message ${line.tone || ""}`} key={idx}>
                        <span className="agent-message-speaker">{line.tone === "t-error" ? "System" : "Agent"}</span>
                        <span>{line.text}</span>
                      </div>
                    ))
                  ) : (
                    <div className="agent-chat-message t-dim">
                      <span className="agent-message-speaker">Agent</span>
                      <span>Ready to scan live opportunities.</span>
                    </div>
                  )}
                </div>
              </section>

              <aside className="agent-decision-panel">
                <div className="agent-panel-label">Decision packet</div>
                {agentSelectedPick ? (
                  <div className="agent-pick-card">
                    <div>
                      <span className="agent-card-kicker">Selected signal</span>
                      <strong>{agentSelectedPick.symbol}</strong>
                    </div>
                    <div className="agent-score-orb">{Number(agentSelectedPick.score || 0).toFixed(1)}</div>
                    <div className="agent-pick-meta">
                      <span>{recommendationTier(agentSelectedPick)} report</span>
                      <span>{agentSelectedPick.provider_id || "funding_memory"}</span>
                    </div>
                    <p>{(agentSelectedPick.reasons || ["fresh live anomaly"]).join(" | ")}</p>
                  </div>
                ) : (
                  <div className="agent-empty-card">Waiting for the agent to pick a report.</div>
                )}

                {agentSessionInvoice ? (
                  <div className="agent-invoice-card">
                    <div className="agent-invoice-shine" />
                    <div className="agent-invoice-head">
                      <span>Invoice ready</span>
                      <strong>{formatUsdc(agentSessionInvoice.amount, 6)}</strong>
                    </div>
                    <div className="agent-invoice-row">
                      <span>Invoice</span>
                      <strong>{shortAddress(agentSessionInvoice.invoice_id)}</strong>
                    </div>
                    <div className="agent-invoice-row">
                      <span>Tier</span>
                      <strong>{tierLabel(agentSessionInvoice.tier)}</strong>
                    </div>
                    <div className="agent-invoice-row">
                      <span>Provider</span>
                      <strong>{agentSessionInvoice.provider_id || "funding_memory"}</strong>
                    </div>
                    <div className="agent-invoice-row">
                      <span>Buyer</span>
                      <strong>{wallet ? shortAddress(wallet) : "n/a"}</strong>
                    </div>
                    {Array.isArray(agentSessionInvoice.split_legs) && agentSessionInvoice.split_legs.length ? (
                      <div className="agent-split-note">
                        {agentSessionInvoice.split_legs.length} split payment legs will be signed.
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <div className="agent-empty-card">Invoice appears here after selection.</div>
                )}

                <div className={`agent-signature-card ${agentSessionStage}`}>
                  <span className="agent-signature-dot" />
                  {agentSessionStage === "awaiting_signature"
                    ? "Wallet signature requested. Confirm in your wallet."
                    : agentSessionStage === "verifying"
                      ? "Payment accepted. Verifying report access."
                      : agentSessionStage === "unlocked"
                        ? "Report unlocked and analytics refreshed."
                        : agentSessionStage === "error"
                          ? "Session stopped before unlock."
                          : "Signature step will start after invoice creation."}
                </div>

                <div className="agent-modal-actions">
                  {agentSessionStage === "unlocked" ? (
                    <button
                      type="button"
                      className="agent-modal-primary"
                      onClick={() => {
                        setShowAgentBuyerModal(false);
                        handleOpenUnlockedReport();
                      }}
                    >
                      Open Report
                    </button>
                  ) : (
                    <button type="button" className="agent-modal-secondary" onClick={() => setShowAgentBuyerModal(false)}>
                      Keep Running in Background
                    </button>
                  )}
                  {agentVerifyResult?.settlement_id ? (
                    <span className="agent-settlement-ref">{shortAddress(agentVerifyResult.settlement_id)}</span>
                  ) : null}
                </div>
              </aside>
            </div>
          </div>
        </div>
      )}

      {showProfileModal && (
        <div className="modal-backdrop open" style={{ display: "flex" }}>
          <div className="wallet-profile-modal" role="dialog" aria-modal="true" aria-labelledby="wallet-profile-title" style={{ display: "block" }}>
            <div className="modal-header">
              <div>
                <div className="modal-title" id="wallet-profile-title">Wallet Profile</div>
                <div className="modal-subtitle" id="wallet-profile-address" style={{ fontSize: "0.68rem", wordBreak: "break-all" }}>{wallet}</div>
              </div>
              <button className="icon-button" type="button" title="Close" onClick={() => setShowProfileModal(false)}>✕</button>
            </div>
            <div className="profile-grid">
              <div className="profile-tile">
                <span className="profile-label">Wallet On-chain USDC</span>
                <span className="profile-value">{profileChainUsdc}</span>
                <span style={{ fontSize: "0.62rem", color: "var(--t3)", marginTop: 4, display: "block", fontFamily: "var(--mono)" }}>
                  MetaMask balance
                </span>
              </div>
              <div className="profile-tile">
                <span className="profile-label">Buyer Gateway Balance</span>
                <span className="profile-value">{profileGatewayUsdc}</span>
                <span style={{ fontSize: "0.62rem", color: "var(--t3)", marginTop: 4, display: "block", fontFamily: "var(--mono)" }}>
                  Circle Gateway contract
                </span>
              </div>
              <div className="profile-tile">
                <span className="profile-label">Reports Bought</span>
                <span className="profile-value">{profileReportsCount}</span>
              </div>
              <div className="profile-tile">
                <span className="profile-label">Total Spent</span>
                <span className="profile-value">{profileTotalSpent}</span>
              </div>
            </div>
            <div className="subsection-title">Purchased Signals</div>
            <div className="token-list">
              {profilePurchasedSymbols.length === 0 ? (
                <span className="token-chip">None yet</span>
              ) : (
                profilePurchasedSymbols.map((sym, idx) => (
                  <span className="token-chip" key={idx}>{sym}</span>
                ))
              )}
            </div>
            <div className="subsection-title">Verified Web Payments</div>
            <div style={{ overflowX: "auto", marginBottom: 16 }}>
              <table className="activity-table">
                <thead>
                  <tr>
                    <th>Signal</th>
                    <th>Amount</th>
                    <th>Status</th>
                    <th>Settlement / Tx</th>
                    <th>Report</th>
                  </tr>
                </thead>
                <tbody>
                  {profilePaymentsLoading ? (
                    <tr>
                      <td colSpan={5} style={{ color: "var(--t3)", textAlign: "center" }}>Loading payments...</td>
                    </tr>
                  ) : profilePaymentsError ? (
                    <tr>
                      <td colSpan={5} style={{ color: "var(--orange)", textAlign: "center" }}>{profilePaymentsError}</td>
                    </tr>
                  ) : profileVerifiedPayments.length === 0 ? (
                    <tr>
                      <td colSpan={5} style={{ color: "var(--t3)", textAlign: "center" }}>No verified payments.</td>
                    </tr>
                  ) : (
                    profileVerifiedPayments.map((payment: any, idx) => {
                      const status = payment.gateway_status || payment.status || "completed";
                      const amount = payment.amount_usdc ?? payment.amount ?? payment.price_usdc;
                      const txHash = payment.transaction_hash || payment.tx_hash || payment.settlement_tx_hash;
                      const settlementLabel = txHash || payment.settlement_id || payment.invoice_id;
                      return (
                      <tr key={payment.entitlement_id || payment.settlement_id || payment.invoice_id || idx}>
                        <td>{payment.symbol || payment.query_symbol || "n/a"}</td>
                        <td className="mono-td">{amount != null ? `${Number(amount).toFixed(3)} USDC` : "-"}</td>
                        <td>
                          <span className={`pnl-badge ${status === "completed" || status === "received" ? "win" : "loss"}`}>
                            {status}
                          </span>
                        </td>
                        <td className="mono-td" style={{ fontSize: "0.66rem" }}>
                          {txHash ? (
                            <a href={payment.explorer_url || `https://testnet.arcscan.app/tx/${txHash}`} target="_blank" rel="noopener noreferrer">
                              {shortAddress(txHash)}
                            </a>
                          ) : settlementLabel ? shortAddress(settlementLabel) : "n/a"}
                        </td>
                        <td>
                          {payment.has_report || status === "completed" || status === "received" ? (
                            <button type="button" className="refresh-btn" onClick={() => {
                              setShowProfileModal(false);
                              setSelectedProviderId(payment.provider_id || "funding_memory");
                              setActiveQuery(payment.query || { symbol: payment.symbol || payment.query_symbol });
                              setUnlockedReport(payment.report || payment);
                              setReportCollapsed(false);
                              setPaywallOpen(false);
                            }}>
                              Open
                            </button>
                          ) : "n/a"}
                        </td>
                      </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
            <div className="table-pager profile-pager">
              <button type="button" className="refresh-btn" disabled={profileVerifiedPaymentsPage <= 1} onClick={() => setProfileVerifiedPaymentsPage(p => Math.max(1, p - 1))}>
                Prev
              </button>
              <span style={{ margin: "0 10px", fontSize: "0.8rem" }}>Page {profileVerifiedPaymentsPage} / {profileVerifiedPaymentsTotalPages}</span>
              <button type="button" className="refresh-btn" disabled={profileVerifiedPaymentsPage >= profileVerifiedPaymentsTotalPages} onClick={() => setProfileVerifiedPaymentsPage(p => Math.min(profileVerifiedPaymentsTotalPages, p + 1))}>
                Next
              </button>
            </div>
          </div>
        </div>
      )}

      {showAgentRunModal && (
        <div className="modal-backdrop open" style={{ display: "flex" }}>
          <div className="wallet-profile-modal agent-run-modal" role="dialog" aria-modal="true" aria-labelledby="agent-run-title" style={{ display: "block" }}>
            <div className="modal-header">
              <div>
                <div className="modal-title" id="agent-run-title">Browser Judge Mode</div>
                <div className="modal-subtitle">
                  QMA ranks live opportunities, chooses an affordable report, and creates an agent invoice.
                </div>
              </div>
              <button className="icon-button" type="button" title="Close" onClick={() => setShowAgentRunModal(false)}>✕</button>
            </div>
            <div className="agent-run-body">
              <div className="agent-mode-grid">
                <div className={`agent-mode-card ${agentRunMode === "judge" ? "active" : ""}`} onClick={() => setAgentRunMode("judge")}>
                  <span className="agent-mode-label">Browser Judge Mode</span>
                  <strong className="agent-mode-title">Human-safe payment</strong>
                  <small>Agent decides. Judge wallet confirms x402.</small>
                </div>
                <div className={`agent-mode-card ${agentRunMode === "cli" ? "active" : ""}`} onClick={() => setAgentRunMode("cli")}>
                  <span className="agent-mode-label">CLI Live Agent</span>
                  <strong className="agent-mode-title">Autonomous payment</strong>
                  <small>Server/CLI signs with AGENT_PRIVATE_KEY.</small>
                </div>
              </div>
              <div className="agent-run-policy">
                <label>
                  <span className="agent-policy-label">Budget</span>
                  <input type="number" min="0.001" step="0.001" value={agentRunBudget} onChange={(e) => setAgentRunBudget(e.target.value)} />
                </label>
                <label>
                  <span className="agent-policy-label">Max/report</span>
                  <input type="number" min="0.001" step="0.001" value={agentRunMaxPrice} onChange={(e) => setAgentRunMaxPrice(e.target.value)} />
                </label>
              </div>
              <button type="button" className="agent-run-btn" disabled={agentRunInProgress} onClick={runAgentDecision}>
                {agentRunInProgress ? "Agent running..." : "Run Agent Decision"}
              </button>
              <div className="agent-run-trace">
                {agentRunTraceLines.length === 0 ? (
                  <div className="agent-run-line muted">
                    Ready. The agent will rank live signals, choose an affordable report, and create an agent invoice.
                  </div>
                ) : (
                  agentRunTraceLines.map((line, idx) => (
                    <div className={`agent-run-line ${line.tone || ""}`} key={idx}>
                      {line.text}
                    </div>
                  ))
                )}
              </div>
              <div className="agent-run-help">
                Browser Judge Mode intentionally keeps private keys inside the wallet. Full autonomous mode runs
                inside the CLI agent using an isolated <code>AGENT_PRIVATE_KEY</code>. Both modes share the same
                payment engine: <code>node examples/agent_buyer.mjs --live</code>.
              </div>
            </div>
            <div className="withdraw-actions">
              <button className="refresh-btn" type="button" onClick={() => setShowAgentRunModal(false)}>Close</button>
            </div>
          </div>
        </div>
      )}

      {showFundArcModal && (
        <div className="modal-backdrop open" style={{ display: "flex" }}>
          <div className="wallet-profile-modal funding-modal" role="dialog" aria-modal="true" aria-labelledby="fund-arc-title" style={{ display: "block" }}>
            <div className="modal-header">
              <div>
                <div className="modal-title" id="fund-arc-title">Fund Arc Wallet</div>
                <div className="modal-subtitle">
                  Read-only funding readiness before QMA spends Gateway balance through x402.
                </div>
              </div>
              <button className="icon-button" type="button" title="Close" onClick={() => setShowFundArcModal(false)}>✕</button>
            </div>
            <div className="funding-body">
              <section className="funding-section">
                <div className="funding-section-top">
                  <div>
                    <div className="funding-section-title">Wallet Status</div>
                    <p className="funding-section-desc">QMA checks readiness before payment without bridging or depositing from this modal.</p>
                  </div>
                  <span className={`funding-status-pill ${fundReadinessTone}`}>{fundReadinessStatus}</span>
                </div>
                <div className="funding-status-grid">
                  <div className="funding-status-item">
                    <span className="funding-item-label">Connected wallet</span>
                    <strong className="funding-item-value" title={wallet}>{fundWalletStatus}</strong>
                  </div>
                  <div className="funding-status-item">
                    <span className="funding-item-label">Wallet provider</span>
                    <strong className="funding-item-value">{fundProviderStatus}</strong>
                  </div>
                  <div className="funding-status-item">
                    <span className="funding-item-label">Arc USDC balance</span>
                    <strong className="funding-item-value">{fundWalletUsdc}</strong>
                  </div>
                  <div className="funding-status-item">
                    <span className="funding-item-label">Gateway balance</span>
                    <strong className="funding-item-value">{fundGatewayBalance}</strong>
                  </div>
                  <div className="funding-status-item">
                    <span className="funding-item-label">Required amount</span>
                    <strong className="funding-item-value">{fundRequiredAmount}</strong>
                  </div>
                </div>
              </section>
              <section className="funding-section">
                <div className="funding-section-top">
                  <div className="funding-next-step">
                    <span className="funding-item-label">Next Step</span>
                    <strong className="funding-item-value">{fundNextStep}</strong>
                    <div style={{ marginTop: 10 }}>
                      {fundPrimaryAction.action === "connect" && (
                        <button type="button" className="funding-action-btn" onClick={connect}>
                          Connect wallet first
                        </button>
                      )}
                      {fundPrimaryAction.action === "switch" && (
                        <button type="button" className="funding-action-btn" onClick={async () => {
                          const provider = getInjectedWallet();
                          if (provider) {
                            await provider.request({
                              method: "wallet_switchEthereumChain",
                              params: [{ chainId: "0x4cef52" }],
                            });
                            refreshFundingReadiness();
                          }
                        }}>
                          Switch Network
                        </button>
                      )}
                      {fundPrimaryAction.action === "refresh" && (
                        <button type="button" className="funding-action-btn" onClick={refreshFundingReadiness}>
                          Retry check
                        </button>
                      )}
                      {fundPrimaryAction.action === "faucet" && (
                        <a className="funding-action-btn" href="https://faucet.circle.com/" target="_blank" rel="noopener noreferrer" style={{ textDecoration: "none", textAlign: "center", display: "inline-block" }}>
                          Open Circle Faucet
                        </a>
                      )}
                      {fundPrimaryAction.action === "close" && (
                        <button type="button" className="funding-action-btn" onClick={() => setShowFundArcModal(false)}>
                          Close
                        </button>
                      )}
                    </div>
                  </div>
                </div>
                <div className="funding-network-details">
                  <span className="funding-network-title">Arc Testnet network details</span>
                  <div className="funding-network-row">
                    <strong className="funding-network-label">Chain ID</strong>
                    <code>5042002 / 0x4cef52</code>
                  </div>
                  <div className="funding-network-row">
                    <strong className="funding-network-label">RPC URL</strong>
                    <code>https://rpc.testnet.arc.network</code>
                  </div>
                  <div className="funding-network-row">
                    <strong className="funding-network-label">Currency</strong>
                    <code>USDC</code>
                  </div>
                  <div className="funding-network-row">
                    <strong className="funding-network-label">Explorer</strong>
                    <code>https://testnet.arcscan.app</code>
                  </div>
                </div>
              </section>
              <section className="funding-section">
                <div className="funding-section-title">Funding Options</div>
                <div className="funding-route-grid">
                  <a className="funding-route-card" href="https://faucet.circle.com/" target="_blank" rel="noopener noreferrer" style={{ textDecoration: "none" }}>
                    <span className="funding-item-label">Option A</span>
                    <strong className="funding-item-value" style={{ display: "block" }}>Circle Faucet</strong>
                    <small>Get Arc Testnet USDC for demos, judge testing, and Arc network fees.</small>
                  </a>
                  <a className="funding-route-card" href="https://developers.circle.com/" target="_blank" rel="noopener noreferrer" style={{ textDecoration: "none" }}>
                    <span className="funding-item-label">Option B</span>
                    <strong className="funding-item-value" style={{ display: "block" }}>CCTP / Arc App Kit</strong>
                    <small>Move existing USDC from another supported chain into Arc. QMA does not execute the bridge in-browser.</small>
                  </a>
                  <div className="funding-route-card">
                    <span className="funding-item-label">Option C</span>
                    <strong className="funding-item-value" style={{ display: "block" }}>Gateway Deposit</strong>
                    <small>Gateway balance is what QMA spends during x402 checkout. Deposit prompts stay inside payment flow.</small>
                  </div>
                </div>
              </section>
            </div>
          </div>
        </div>
      )}
    </div >
  );
}
