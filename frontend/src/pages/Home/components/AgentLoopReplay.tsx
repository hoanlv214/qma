import { useState, useEffect, useRef } from "react";
import { Play, Pause, Check, ShieldX, ExternalLink, Bot } from "lucide-react";
import { ARC_CHAIN } from "@/config/network";

export type DecisionOutcome = "paid" | "refused";

interface LiveMetrics {
  current_paid_count: number;
  current_revenue_usdc: number;
  unique_payers: number;
}

interface LiveLedgerBlock {
  action: string;
  hash: string;
  timestamp: string;
}

export function AgentLoopReplay() {
  const [activeTab, setActiveTab] = useState<DecisionOutcome>("paid");
  const [isPlaying, setIsPlaying] = useState(true);
  const [metrics, setMetrics] = useState<LiveMetrics | null>(null);
  const [ledgerHead, setLedgerHead] = useState<LiveLedgerBlock[]>([]);
  const timerRef = useRef<number | null>(null);

  // Live production metrics and ledger head
  useEffect(() => {
    let disposed = false;
    const load = async () => {
      try {
        const metricsRes = await fetch("/api/v1/metrics");
        if (metricsRes.ok && !disposed) {
          const data = await metricsRes.json();
          setMetrics({
            current_paid_count: Number(data.current_paid_count || 0),
            current_revenue_usdc: Number(data.current_revenue_usdc || 0),
            unique_payers: Number(data.current_unique_payers || data.unique_payers || 0),
          });
        }
      } catch {
        /* offline fallback */
      }
      try {
        const ledgerRes = await fetch("/api/v1/treasury/audit/euthyna?limit=3");
        if (ledgerRes.ok && !disposed) {
          const records = await ledgerRes.json();
          if (Array.isArray(records)) {
            setLedgerHead(
              records.slice(0, 3).map((record: { action: string; integrity_hash: string; timestamp: string }) => ({
                action: String(record.action || ""),
                hash: String(record.integrity_hash || ""),
                timestamp: String(record.timestamp || ""),
              })),
            );
          }
        }
      } catch {
        /* offline fallback */
      }
    };
    load();
    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    if (!isPlaying) return;
    timerRef.current = window.setTimeout(() => {
      setActiveTab((curr) => (curr === "paid" ? "refused" : "paid"));
    }, 7000);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [activeTab, isPlaying]);

  const avgPrice =
    metrics && metrics.current_paid_count > 0
      ? (metrics.current_revenue_usdc / metrics.current_paid_count).toFixed(4)
      : "0.0050";

  const shortHash = (value: string) =>
    value && value.length >= 16 ? `${value.slice(0, 4)}...${value.slice(-4)}` : value || "····";

  const isPaid = activeTab === "paid";

  return (
    <div className="invoice-replay-wrapper" role="region" aria-label="Autonomous Decision Invoice Preview">
      {/* Controls Bar */}
      <div className="invoice-controls-bar">
        <div className="invoice-pill-toggle">
          <button
            type="button"
            className={`pill-btn ${isPaid ? "active-paid" : ""}`}
            onClick={() => {
              setActiveTab("paid");
              setIsPlaying(false);
            }}
          >
            Paid on Arc
          </button>
          <button
            type="button"
            className={`pill-btn ${!isPaid ? "active-refused" : ""}`}
            onClick={() => {
              setActiveTab("refused");
              setIsPlaying(false);
            }}
          >
            Blocked by Code
          </button>
        </div>

        <button
          type="button"
          className="evidence-playback-btn"
          onClick={() => setIsPlaying((p) => !p)}
          title={isPlaying ? "Pause auto-replay" : "Resume auto-replay"}
          aria-label={isPlaying ? "Pause replay" : "Play replay"}
        >
          {isPlaying ? (
            <Pause size={13} className="fill-current" />
          ) : (
            <Play size={13} className="fill-current ml-0.5" />
          )}
        </button>
      </div>

      {/* Stacked Invoice Cards */}
      <div className="invoice-stacked-container">
        {/* Primary Active Card */}
        <article className={`invoice-primary-card ${isPaid ? "invoice-card--paid" : "invoice-card--refused"}`}>
          {/* Header Bar */}
          <div className="invoice-card-header">
            <span className="invoice-eyebrow">Market Intelligence Invoice</span>
            <span className={`invoice-header-badge ${isPaid ? "badge-paid" : "badge-refused"}`}>
              {isPaid ? "Live Arc Settlement" : "Guardrail Intercepted"}
            </span>
          </div>

          {/* Payee / Title Row */}
          <div className="invoice-payee-row">
            <div className="invoice-payee-meta">
              <div className="invoice-avatar-box">
                <Bot size={18} className={isPaid ? "text-emerald-400" : "text-rose-400"} />
              </div>
              <div className="min-w-0">
                <h4 className="invoice-payee-title">
                  {isPaid ? "Funding Dislocation Alpha" : "Whale Order Flow Alpha"}
                </h4>
                <p className="invoice-payee-subtitle">
                  {isPaid
                    ? `Invoice #0412 · Negative funding analog on MEXC (${ARC_CHAIN.name})`
                    : "Invoice #0931 · Cross-venue liquidation orderbook sweep"}
                </p>
              </div>
            </div>

            <div className="invoice-price-box">
              {isPaid ? (
                <div className="invoice-amount-display">
                  <span className="amount-num">{avgPrice}</span>
                  <span className="amount-unit">USDC</span>
                </div>
              ) : (
                <div className="invoice-amount-display">
                  <span className="amount-num amount-struck">0.0500</span>
                  <span className="amount-num text-rose-400 ml-1.5">0.0500</span>
                  <span className="amount-unit">USDC</span>
                </div>
              )}
            </div>
          </div>

          {/* Decision Status Badges */}
          <div className="invoice-badges-strip">
            {isPaid ? (
              <>
                <span className="status-chip chip-success">Agent: purchase</span>
                <span className="status-chip chip-cyan">
                  <span className="pulse-dot-emerald" />
                  Settled on {ARC_CHAIN.name}
                </span>
              </>
            ) : (
              <>
                <span className="status-chip chip-amber">Model: proposed purchase</span>
                <span className="status-chip chip-danger">
                  <span className="pulse-dot-rose" />
                  Held by Guardrail
                </span>
              </>
            )}
          </div>

          {/* Agent's Reasoning */}
          <div className="invoice-reasoning-section">
            <span className="reasoning-label">Agent&apos;s reasoning</span>
            <p className="reasoning-body">
              {isPaid
                ? "Negative funding dislocation (-0.38%) on MEXC BTC/USDT matches historical October 2024 reversal regime. Unlocks full statistical backtest."
                : "Requested real-time orderbook depth across 4 derivative exchanges. Purchase intent approved by autonomous planner."}
            </p>
          </div>

          {/* Verification Checks or Guardrail Band */}
          {isPaid ? (
            <div className="invoice-checks-grid">
              <div className="check-item">
                <Check size={14} className="check-icon text-emerald-400" strokeWidth={3} />
                <span>Within agent spending limit ({avgPrice} USDC)</span>
              </div>
              <div className="check-item">
                <Check size={14} className="check-icon text-emerald-400" strokeWidth={3} />
                <span>GenLayer SLA consensus verdict valid</span>
              </div>
              <div className="check-item">
                <Check size={14} className="check-icon text-emerald-400" strokeWidth={3} />
                <span>Circle Gateway x402 settled on Arc</span>
              </div>
              <div className="check-item">
                <Check size={14} className="check-icon text-emerald-400" strokeWidth={3} />
                <span>SHA-256 Euthyna audit chain linked</span>
              </div>
            </div>
          ) : (
            <div className="guardrail-callout-band">
              <div className="guardrail-callout-header">
                <ShieldX size={16} className="guardrail-icon" />
                <span className="guardrail-title">Blocked by code, not by the model.</span>
              </div>
              <p className="guardrail-lead">
                The agent decided to purchase. The deterministic spend guard refused it before anything was signed or sent.
              </p>
              <dl className="guardrail-grid-facts">
                <dt>Rule</dt>
                <dd>spend_guard.spend_limit</dd>
                <dt>Attempted</dt>
                <dd className="font-mono text-rose-300">0.0500 USDC</dd>
                <dt>Allowed</dt>
                <dd className="font-mono text-emerald-300">0.0100 USDC (daily cap)</dd>
                <dt>Why</dt>
                <dd>It is above the payer&apos;s configured payment limit.</dd>
              </dl>
            </div>
          )}

          {/* Interactive Action Prompt */}
          <div className="invoice-action-bar">
            <span className="action-prompt-text">Do you agree with the agent?</span>
            <div className="action-buttons-group">
              <span className="drawn-btn drawn-btn--primary">
                {isPaid ? "Agree & purchase" : "Override in Approvals"}
              </span>
              <span className="drawn-btn drawn-btn--secondary">Review Query</span>
            </div>
          </div>
        </article>

        {/* Stacked Secondary Card (Tucked Underneath) */}
        <div
          className="invoice-stacked-secondary"
          onClick={() => {
            setActiveTab(isPaid ? "refused" : "paid");
            setIsPlaying(false);
          }}
          role="button"
          tabIndex={0}
          title="Click to inspect this alternate scenario"
        >
          <div className="secondary-row">
            <div className="secondary-left">
              <span className="secondary-name">
                {isPaid ? "Whale Order Flow Alpha" : "Funding Dislocation Alpha"}
              </span>
              <span className="secondary-ref">
                {isPaid ? "· invoice 0931" : "· invoice 0412"}
              </span>
            </div>
            <div className="secondary-right">
              <span className="font-mono text-xs font-semibold">
                {isPaid ? "0.0500 USDC" : `${avgPrice} USDC`}
              </span>
            </div>
          </div>

          <div className="secondary-status-row">
            <span className={`secondary-badge ${isPaid ? "badge-held" : "badge-settled"}`}>
              {isPaid ? "Held by Guardrail" : "Paid on Arc"}
            </span>
            <p className="secondary-snippet">
              {isPaid ? (
                <>
                  <ShieldX size={12} className="inline text-rose-400 mr-1 shrink-0" />
                  <span>Blocked by code, not by the model. It is above the payer&apos;s payment limit.</span>
                </>
              ) : (
                <>
                  <Check size={12} className="inline text-emerald-400 mr-1 shrink-0" />
                  <span>Verified by GenLayer SLA &amp; settled via Circle Gateway on Arc.</span>
                </>
              )}
            </p>
          </div>
        </div>
      </div>

      {/* Live Ledger Head Connector */}
      <div className="ledger-head-connector">
        <span className="connector-dashed-line" />
        <div className="ledger-head-badge">
          <span className="ledger-pulse-dot" />
          <span className="ledger-head-label">LIVE LEDGER HEAD</span>
        </div>

        <div className="ledger-blocks-chain">
          {(ledgerHead.length > 0
            ? ledgerHead
            : [{ action: "awaiting records", hash: "", timestamp: "" }]
          ).map((block, index) => (
            <div key={`${block.timestamp}-${index}`} className={`ledger-block-item${index > 0 ? " ledger-block-dim" : ""}`}>
              <span className="block-seq">{block.timestamp ? block.timestamp.slice(11, 19) : "····"}</span>
              <span className="block-desc">{block.action || "system · idle"}</span>
              <span className="block-hash">{shortHash(block.hash)}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Footnote */}
      <p className="evidence-footnote">
        Wired to the live production ledger
        {metrics
          ? `: ${metrics.current_paid_count} reports settled for ${metrics.current_revenue_usdc.toFixed(2)} USDC across ${metrics.unique_payers} payers`
          : ""}
        . Hard limits are enforced in deterministic Python Decimal code before wallet signing.
      </p>
    </div>
  );
}

export default AgentLoopReplay;
