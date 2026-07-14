import { useState, type Dispatch, type FormEvent, type SetStateAction } from "react";
import { API_BASE_URL } from "../services/api";
import { getInjectedWallet, shortAddress } from "../services/wallet";
import { payX402Resource, prepareX402Payment, submitX402Payment, X402PaymentError, type PreparedX402Payment } from "../services/x402";
import { createInvoice } from "../services/invoices";
import { extractGatewayBalanceUsdc } from "../services/gatewayCrypto";
import type { PaymentStepKey, PaymentStepState } from "../types/qma";
import { normalizeTierForCache } from "../utils/format";

type Signal = Record<string, any>;
type ToastTone = "info" | "success" | "warning" | "error";
type SameAddress = (a?: string, b?: string) => boolean;
type SetCacheRevision = Dispatch<SetStateAction<number>>;

interface UsePaymentOptions {
  wallet: string;
  activeQuery: Signal;
  selectedProviderId: string;
  sellerAddress: string;
  arcGatewayUrl: string;
  sameAddress: SameAddress;
  showToast: (message: string, tone?: ToastTone) => void;
  refreshPendingInvoice: (signal: Signal, tier: "preview" | "full", providerId: string, account: string) => Promise<any>;
  rememberPendingInvoice: (invoice: any, signal: Signal, tier: "preview" | "full", providerId: string, account: string) => void;
  clearPendingInvoice: (signal: Signal, tier: "preview" | "full", providerId: string, account: string) => void;
  normalizeSignalPayload: (source?: Signal) => Signal;
  signalCacheKey: (signal: Signal, tier: "preview" | "full", providerId: string, account?: string) => string;
  setCacheRevision: SetCacheRevision;
}

export function usePayment({
  wallet,
  activeQuery,
  selectedProviderId,
  sellerAddress,
  arcGatewayUrl,
  sameAddress,
  showToast,
  refreshPendingInvoice,
  rememberPendingInvoice,
  clearPendingInvoice,
  normalizeSignalPayload,
  signalCacheKey,
  setCacheRevision,
}: UsePaymentOptions) {
  const [paywallOpen, setPaywallOpen] = useState(false);
  const [currentInvoice, setCurrentInvoice] = useState<any>(null);
  const [paymentStep, setPaymentStep] = useState<PaymentStepKey>("wallet");
  const [paymentStepStatus, setPaymentStepStatus] = useState<Record<PaymentStepKey, { status: PaymentStepState; label: string; detail?: string }>>({
    wallet: { status: "waiting", label: "Waiting" },
    gateway: { status: "waiting", label: "Waiting" },
    settlement: { status: "waiting", label: "Waiting" },
    report: { status: "waiting", label: "Waiting" },
  });
  const [payStatusText, setPayStatusText] = useState("");
  const [payErrorText, setPayErrorText] = useState("");
  const [paymentSuccess, setPaymentSuccess] = useState(false);
  const [paySubmitting, setPaySubmitting] = useState(false);
  const [paymentDetails, setPaymentDetails] = useState({
    buyerGatewayBalance: "",
    settlementId: "",
    sellerAvailable: "",
    sellerPending: "",
    txHash: "",
    explorerUrl: "",
  });
  const [reportDetailsOpen, setReportDetailsOpen] = useState(true);
  const [showDepositModal, setShowDepositModal] = useState(false);
  const [depositAmountInput, setDepositAmountInput] = useState("0.005");
  const [unlockedReport, setUnlockedReport] = useState<any>(null);
  const [reportCollapsed, setReportCollapsed] = useState(true);

  const recommendationTierPrice = (pick: any, tier: string, pricing: Record<string, number>) => {
    const baseKey = `${pick.provider_id || "funding_memory"}_${tier}`;
    return pricing[baseKey] || (tier === "preview" ? 0.001 : 0.005);
  };

  const recommendationTier = (pick: any): "preview" | "full" => {
    const tier = String(pick?.tier || pick?.suggested_tier || "").toLowerCase();
    return tier === "full" ? "full" : "preview";
  };

  const openPaywall = async (tier: "preview" | "full", event?: FormEvent) => {
    if (event) event.preventDefault();
    if (!wallet) {
      showToast("Please connect your wallet first.", "warning");
      return;
    }

    setPaywallOpen(true);
    setPaymentSuccess(false);
    setPaySubmitting(false);
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
    setPaymentStep("wallet");
    setPaymentStepStatus({
      wallet: { status: "active", label: "Checking" },
      gateway: { status: "waiting", label: "Waiting" },
      settlement: { status: "waiting", label: "Waiting" },
      report: { status: "waiting", label: "Waiting" },
    });

    try {
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
          if (switchErr.code === 4902 || String(switchErr.message).toLowerCase().includes("unrecognized")) {
            await provider.request({
              method: "wallet_addEthereumChain",
              params: [{
                chainId: ARC_TESTNET_HEX,
                chainName: "Arc Testnet",
                nativeCurrency: { name: "USDC", symbol: "USDC", decimals: 18 },
                rpcUrls: ["https://rpc.testnet.arc.network"],
                blockExplorerUrls: ["https://testnet.arcscan.app"],
              }],
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
        invoiceData = await createInvoice({
          ...activeQuery,
          symbol: String(activeQuery.symbol || ""),
          provider_id: selectedProviderId,
          tier,
        });
      } else {
        showToast(`Resumed invoice ${shortAddress(invoiceData.invoice_id)}. Continue with remaining split leg.`, "info");
      }
      setCurrentInvoice(invoiceData);
      rememberPendingInvoice(invoiceData, activeQuery, tier, selectedProviderId, wallet);

      setPayStatusText("Reading Gateway Balance...");
      let gatewayBase = arcGatewayUrl.replace(/\/$/, "");
      if (!gatewayBase && invoiceData.arc_gateway_url) {
        try { gatewayBase = new URL(invoiceData.arc_gateway_url).origin; } catch { gatewayBase = ""; }
      }
      if (!gatewayBase) throw new Error("Arc Gateway URL not configured. Retry or refresh.");
      const balResp = await fetch(`${gatewayBase}/api/balance/${wallet}`);
      if (!balResp.ok) throw new Error("Could not check Gateway Balance");
      const balData = await balResp.json();
      const gatewayBal = extractGatewayBalanceUsdc(balData) ?? 0;
      setPaymentDetails((prev) => ({ ...prev, buyerGatewayBalance: `${gatewayBal.toFixed(6)} USDC` }));

      const invoiceCost = Number(invoiceData.amount);
      if (gatewayBal < invoiceCost) {
        setPayStatusText(`Top Up required: need ${invoiceCost.toFixed(6)} USDC, have ${gatewayBal.toFixed(6)} USDC`);
        setPaymentStepStatus((prev) => ({ ...prev, gateway: { status: "failed", label: "Top Up Needed" } }));
        setPaymentStep("gateway");
        setDepositAmountInput(Math.max(invoiceCost, 0.005).toFixed(6));
        setShowDepositModal(true);
        return;
      }

      setPaymentStepStatus((prev) => ({
        ...prev,
        gateway: { status: "completed", label: "Funded" },
        settlement: { status: "active", label: "Sign Settlement" },
      }));
      setPaymentStep("settlement");
      setPayStatusText("Gateway funds confirmed. Ready for settlement signature.");
    } catch (err: any) {
      setPayErrorText(err.message || "Failed to initialize payment.");
      setPaymentStepStatus((prev) => ({ ...prev, wallet: { status: "failed", label: "Failed" } }));
    }
  };

  const waitForTxReceipt = async (hash: string) => {
    const provider = getInjectedWallet();
    if (!provider) return;
    for (let i = 0; i < 45; i++) {
      const rec = await provider.request<any>({ method: "eth_getTransactionReceipt", params: [hash] });
      if (rec) {
        if (rec.status !== "0x1") throw new Error("Transaction reverted.");
        return rec;
      }
      await new Promise((resolve) => setTimeout(resolve, 1500));
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
      const walletStatusResp = await fetch(`${gwBase}/api/wallet-status/${wallet}`);
      const statusData = walletStatusResp.ok ? await walletStatusResp.json() : null;
      const approveDefault = statusData?.defaultApproveUsdc ?? 10;
      const approveAmount = Math.max(approveDefault, amount).toFixed(6);
      const calldataUrl = `${gwBase}/api/deposit-calldata/${wallet}?amount=${amount.toFixed(6)}&approveAmount=${approveAmount}`;
      const calldataResp = await fetch(calldataUrl);
      const data = await calldataResp.json();
      if (!calldataResp.ok) throw new Error(data.error || "Deposit calldata failed");

      const provider = getInjectedWallet();
      if (!provider) throw new Error("No wallet injection found.");
      const allowance = Number(statusData?.allowance?.formatted || 0);
      if (allowance < amount) {
        setPayStatusText("Requesting USDC allowance approval in wallet...");
        const appTxHash = await provider.request<string>({ method: "eth_sendTransaction", params: [data.approveTx] });
        setPayStatusText("Waiting for allowance transaction receipt...");
        await waitForTxReceipt(appTxHash);
        saveLocalAction("approve", approveAmount, appTxHash);
      }

      setPayStatusText("Confirm Gateway deposit in your wallet...");
      const depTxHash = await provider.request<string>({ method: "eth_sendTransaction", params: [data.depositTx] });
      setPayStatusText("Waiting for deposit transaction confirmation...");
      await waitForTxReceipt(depTxHash);
      saveLocalAction("deposit", amount.toFixed(6), depTxHash);

      setPayStatusText("Updating gateway balances...");
      let balanceUpdated = false;
      for (let i = 0; i < 30; i++) {
        const check = await fetch(`${gwBase}/api/balance/${wallet}`);
        if (check.ok) {
          const res = await check.json();
          const normalBal = extractGatewayBalanceUsdc(res) ?? 0;
          if (normalBal >= Number(currentInvoice.amount)) {
            balanceUpdated = true;
            break;
          }
        }
        await new Promise((resolve) => setTimeout(resolve, 2000));
      }
      if (!balanceUpdated) throw new Error("Circle Gateway did not settle balance update in time.");
      setPaymentDetails((prev) => ({ ...prev, buyerGatewayBalance: `${Number(currentInvoice.amount).toFixed(6)}+ USDC` }));
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

  const signAndSettleX402 = async () => {
    if (!currentInvoice || !wallet || paySubmitting) return;
    setPaySubmitting(true);
    setPayErrorText("");
    setPayStatusText("Requesting EIP-712 payment authorization signature...");
    setPaymentStep("settlement");
    setPaymentStepStatus((prev) => ({ ...prev, settlement: { status: "active", label: "Signing" } }));

      try {
        const splitLegs = Array.isArray(currentInvoice.split_legs) ? currentInvoice.split_legs : [];
        const hasPriorSplitProgress = splitLegs.some((leg: any) => leg.status === "paid" || leg.status === "processing" || leg.settlement_id);
        if (hasPriorSplitProgress) {
          const reconciled = await refreshPendingInvoice(activeQuery, normalizeTierForCache(currentInvoice.tier), currentInvoice.provider_id || selectedProviderId, wallet);
          const processingLeg = (reconciled?.split_legs || []).find((leg: any) => leg.status === "processing");
          if (processingLeg) {
            throw new Error(`The ${processingLeg.role || processingLeg.leg_id} settlement is still being reconciled. Check invoice status before retrying.`);
          }
        }
        const selfRecipientLeg = splitLegs.find((leg: any) => sameAddress(wallet, leg.pay_to));
      if (selfRecipientLeg) {
        throw new Error(`Connected wallet is the ${selfRecipientLeg.role || selfRecipientLeg.leg_id} split recipient (${selfRecipientLeg.pay_to}). Use a separate buyer wallet from the provider or treasury wallet.`);
      }
      if (!splitLegs.length && sameAddress(wallet, sellerAddress)) {
        throw new Error(`Connected wallet is the seller wallet (${sellerAddress}). Use a separate buyer wallet for report purchases.`);
      }

      const splitSettlements: any[] = splitLegs
        .filter((leg: any) => leg.status === "paid" && leg.settlement_id && leg.sidecar_receipt)
        .map((leg: any) => ({
          leg_id: leg.leg_id,
          settlement_id: leg.settlement_id,
          pay_to: leg.pay_to,
          amount_raw: String(leg.amount_raw),
          sidecar_receipt: leg.sidecar_receipt,
          payer_address: leg.payer_address,
          gateway_status: leg.gateway_status,
        }));
      let settlementId = "";
      let paidAmountUsdc: number | undefined;

      if (splitLegs.length) {
        let workingSplitLegs = splitLegs;
        const paidLegIds = new Set(splitSettlements.map((item) => item.leg_id));
        const pendingLegs = splitLegs.filter((leg: any) => !paidLegIds.has(leg.leg_id) && leg.status !== "paid");
        const preparedLegs: Array<{ leg: any; prepared: PreparedX402Payment }> = [];
        for (const leg of pendingLegs) {
          setPayStatusText(`Signing ${leg.role || leg.leg_id} split leg...`);
          preparedLegs.push({ leg, prepared: await prepareX402Payment(leg.resource, wallet) });
        }
        const settlementResults = await Promise.allSettled(
          preparedLegs.map(({ prepared }) => submitX402Payment(prepared)),
        );
        const failedLegs: Array<{ leg: any; reason: unknown }> = [];
        settlementResults.forEach((result, index) => {
          const leg = preparedLegs[index].leg;
          if (result.status === "rejected") {
            failedLegs.push({ leg, reason: result.reason });
            return;
          }
          const paidLeg = result.value;
          const legSettlementId = paidLeg.settlement_id || paidLeg.settlementId;
          if (!legSettlementId || !paidLeg.sidecar_receipt) throw new Error(`Split leg ${leg.leg_id} did not return a settlement receipt.`);
          splitSettlements.push({
            leg_id: paidLeg.leg_id || leg.leg_id,
            settlement_id: legSettlementId,
            pay_to: paidLeg.pay_to || leg.pay_to,
            amount_raw: String(paidLeg.amount_raw || leg.amount_raw),
            sidecar_receipt: paidLeg.sidecar_receipt,
            payer_address: paidLeg.payer,
            gateway_status: paidLeg.gateway_status,
          });
          workingSplitLegs = workingSplitLegs.map((item: any) => item.leg_id === (paidLeg.leg_id || leg.leg_id)
            ? { ...item, status: "paid", settlement_id: legSettlementId, sidecar_receipt: paidLeg.sidecar_receipt, payer_address: paidLeg.payer || item.payer_address, gateway_status: paidLeg.gateway_status || item.gateway_status }
            : item);
          const updatedInvoice = { ...currentInvoice, split_legs: workingSplitLegs };
          setCurrentInvoice(updatedInvoice);
          rememberPendingInvoice(updatedInvoice, activeQuery, normalizeTierForCache(updatedInvoice.tier), updatedInvoice.provider_id || selectedProviderId, wallet);
          saveLocalAction("x402_split_leg", String(paidLeg.amount_usdc || leg.amount_usdc || currentInvoice.amount), legSettlementId);
        });
        if (failedLegs.length) {
          // Reconcile before retrying. A timeout can mean Circle settled and
          // the response was lost; signing a new authorization would risk a
          // second payment. The cached invoice is already persisted, so this
          // status request is safe and can recover any leg recorded by QMA.
          const reconciled = await refreshPendingInvoice(activeQuery, normalizeTierForCache(currentInvoice.tier), currentInvoice.provider_id || selectedProviderId, wallet);
          const reconciledLegs = Array.isArray(reconciled?.split_legs) ? reconciled.split_legs : [];
          for (const reconciledLeg of reconciledLegs) {
            if (reconciledLeg.status !== "paid" || !reconciledLeg.settlement_id || !reconciledLeg.sidecar_receipt) continue;
            const alreadyIncluded = splitSettlements.some((item) => item.leg_id === reconciledLeg.leg_id);
            if (!alreadyIncluded) {
              splitSettlements.push({
                leg_id: reconciledLeg.leg_id,
                settlement_id: reconciledLeg.settlement_id,
                pay_to: reconciledLeg.pay_to,
                amount_raw: String(reconciledLeg.amount_raw),
                payer_address: reconciledLeg.payer_address,
                gateway_status: reconciledLeg.gateway_status,
                sidecar_receipt: reconciledLeg.sidecar_receipt,
              });
            }
          }
          workingSplitLegs = workingSplitLegs.map((item: any) => reconciledLegs.find((candidate: any) => candidate.leg_id === item.leg_id) || item);
          const updatedInvoice = { ...(reconciled || currentInvoice), split_legs: workingSplitLegs };
          setCurrentInvoice(updatedInvoice);
          rememberPendingInvoice(updatedInvoice, activeQuery, normalizeTierForCache(updatedInvoice.tier), updatedInvoice.provider_id || selectedProviderId, wallet);
          const unresolved = failedLegs.filter(({ leg }) => {
            const reconciledLeg = workingSplitLegs.find((item: any) => item.leg_id === leg.leg_id);
            return !(reconciledLeg?.status === "paid" && reconciledLeg.settlement_id && reconciledLeg.sidecar_receipt);
          });
          if (unresolved.length) {
            const uncertain = failedLegs.some(({ reason }) => reason instanceof X402PaymentError && reason.outcomeUncertain);
            throw new Error(uncertain
              ? "Settlement outcome is uncertain. Payment state was checked; retry only after the invoice status is known."
              : `Could not settle ${unresolved.map(({ leg }) => leg.role || leg.leg_id).join(", ")} split leg. Retry the remaining leg.`);
          }
        }
      } else {
        const paidData = await payX402Resource(currentInvoice.arc_gateway_url, wallet);
        settlementId = paidData.settlement_id || paidData.settlementId;
        paidAmountUsdc = Number(paidData.amount_usdc || currentInvoice.amount);
        if (!settlementId) throw new Error("Arc Gateway did not return a settlement id.");
        saveLocalAction("x402_settlement", String(paidAmountUsdc || currentInvoice.amount), settlementId);
      }

      setPaymentStep("report");
      setPaymentStepStatus((prev) => ({ ...prev, settlement: { status: "completed", label: "Settled" }, report: { status: "active", label: "Verifying" } }));
      setPayStatusText("Settlement accepted. Verifying tokens...");
      const verifyResp = await fetch(`${API_BASE_URL}/api/v1/payment/verify?invoice_id=${encodeURIComponent(currentInvoice.invoice_id)}`, {
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
      if (!verifyData.access_token) throw new Error("QMA verification did not return an access token.");

      setPaymentStepStatus((prev) => ({ ...prev, report: { status: "completed", label: "Unlocked" } }));
      setPaymentDetails((prev) => ({
        ...prev,
        settlementId: verifyData.settlement_id || settlementId || splitSettlements.map((item) => item.settlement_id).join(", "),
        sellerAvailable: verifyData.seller_gateway_available_usdc != null ? `${Number(verifyData.seller_gateway_available_usdc).toFixed(6)} USDC` : prev.sellerAvailable,
        sellerPending: verifyData.seller_gateway_pending_batch_usdc != null ? `${Number(verifyData.seller_gateway_pending_batch_usdc).toFixed(6)} USDC` : prev.sellerPending,
        txHash: verifyData.transaction_hash || prev.txHash,
        explorerUrl: verifyData.explorer_url || prev.explorerUrl,
      }));
      setPayStatusText("Report unlocked successfully.");
      setPaymentSuccess(true);
      sessionStorage.setItem(`qma_accessToken_${currentInvoice.invoice_id}`, verifyData.access_token);
      await fetchReportContent(currentInvoice.invoice_id, verifyData.access_token, currentInvoice);
      clearPendingInvoice(activeQuery, normalizeTierForCache(currentInvoice.tier), currentInvoice.provider_id || selectedProviderId, wallet);
    } catch (err: any) {
      setPayErrorText(err.message || "Settlement signature cancelled or failed.");
      setPaymentStepStatus((prev) => ({ ...prev, settlement: { status: "failed", label: "Failed" } }));
    } finally {
      setPaySubmitting(false);
    }
  };

  const fetchReportContent = async (
    invoiceId: string,
    accessToken: string,
    invoiceOverride?: any,
    queryOverride?: Signal,
    providerOverride?: string,
  ) => {
    try {
      const invoiceForReport = invoiceOverride || currentInvoice;
      const reportQuery = queryOverride || activeQuery;
      const providerForReport = invoiceForReport?.provider_id || providerOverride || selectedProviderId;
      const endpoint = invoiceForReport?.tier === "preview"
        ? `/api/v1/providers/${encodeURIComponent(providerForReport)}/preview`
        : `/api/v1/providers/${encodeURIComponent(providerForReport)}/full-report`;
      const resp = await fetch(`${API_BASE_URL}${endpoint}?invoice_id=${encodeURIComponent(invoiceId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-QMA-Access-Token": accessToken },
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
      const key = signalCacheKey(normalizedReportQuery, reportTier, providerForReport);
      localStorage.setItem(key, JSON.stringify({
        saved_at: Date.now(),
        signal: normalizedReportQuery,
        tier: reportTier,
        provider_id: providerForReport,
        payer_address: wallet,
        invoice: invoiceForReport,
        report: cachedReportData,
      }));
      setCacheRevision((value) => value + 1);
    } catch (err: any) {
      showToast("Failed to load report contents: " + err.message, "error");
    }
  };

  const handleOpenUnlockedReport = () => {
    setPaywallOpen(false);
    setReportCollapsed(false);
  };

  return {
    paywallOpen,
    setPaywallOpen,
    currentInvoice,
    setCurrentInvoice,
    paymentStep,
    paymentStepStatus,
    payStatusText,
    payErrorText,
    paymentSuccess,
    paySubmitting,
    paymentDetails,
    reportDetailsOpen,
    setReportDetailsOpen,
    showDepositModal,
    setShowDepositModal,
    depositAmountInput,
    setDepositAmountInput,
    unlockedReport,
    setUnlockedReport,
    reportCollapsed,
    setReportCollapsed,
    openPaywall,
    signAndSettleX402,
    handleDepositToGateway,
    waitForTxReceipt,
    fetchReportContent,
    handleOpenUnlockedReport,
    recommendationTierPrice,
    recommendationTier,
    saveLocalAction,
  };
}
