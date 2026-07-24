import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { requestJson } from "../../services/api";

interface AutonomousAgentModalProps {
  open: boolean;
  onClose: () => void;
  wallet: string; // The user's wallet address (simulated deposit source)
}

type AgentAction = {
  action: string;
  symbol?: string;
  provider?: string;
  tier?: string;
  at: string;
  amount_usdc?: number;
};

type ChatMessage = {
  id: string;
  role: "user" | "agent";
  content: ReactNode;
};

const STAGE_LABELS = ["Queued", "Research", "Buying", "Finished"];

function stageIndex(status: string, purchases: number): number {
  switch (status) {
    case "queued": return 0;
    case "running": return purchases > 0 ? 2 : 1;
    case "stopped": return purchases > 0 ? 2 : 1;
    case "error": return purchases > 0 ? 2 : 1;
    case "completed": return 3;
    default: return 0;
  }
}

export function AutonomousAgentModal({ open, onClose, wallet }: AutonomousAgentModalProps) {
  const [prompt, setPrompt] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [status, setStatus] = useState<"idle" | "creating" | "queued" | "running" | "completed" | "error" | "stopped">("idle");
  const [budget, setBudget] = useState<number>(0);
  const [spent, setSpent] = useState<number>(0);
  const [purchases, setPurchases] = useState<number>(0);
  const [purchasedItems, setPurchasedItems] = useState<any[]>([]);

  // Real UI state
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Real Platform Gateway Balance (fetched from API)
  const [globalBalance, setGlobalBalance] = useState<number>(0);
  const autoFetchedRef = useRef(false);

  // Fetch gateway balance on mount
  useEffect(() => {
    if (wallet && open) {
      fetch(`/api/balance/${wallet}`)
        .then(r => r.json())
        .then(d => {
          if (d.balances && Array.isArray(d.balances)) {
            const sum = d.balances.reduce((acc: number, b: any) => acc + Number(b.balance || 0), 0);
            setGlobalBalance(sum);
          }
        })
        .catch(err => console.error("Failed to fetch balance", err));
    }
  }, [wallet, open]);

  // Auto-scroll messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, status]);

  // Handle session polling
  useEffect(() => {
    // 1. On mount, try to find an active session if we don't have one
    if (!sessionId && open && !autoFetchedRef.current && wallet) {
      autoFetchedRef.current = true;
      requestJson<any[]>(`/api/v1/sessions?owner_wallet=${wallet}`).then(sessions => {
        const active = sessions.find(s => s.status === "running" || s.status === "queued" || s.status === "stopped");
        if (active) {
          setSessionId(active.id);
          setStatus(active.status);
          setBudget(active.budget_usdc || 0);

          setMessages([
            { id: "sys-0", role: "agent", content: `Resumed session ${active.id.split("-")[0]}. Currently ${active.status}.` }
          ]);
        } else {
          setMessages([
            { id: "sys-start", role: "agent", content: "Hi! I'm your Autonomous Background Runner. Tell me what reports you'd like me to purchase, and specify a budget (e.g. 'Buy 3 trending reports under $1.50 USDC')." }
          ]);
        }
      }).catch(err => console.error("Failed to fetch sessions on mount", err));
    }

    let interval: ReturnType<typeof setInterval>;

    if (sessionId && (status === "queued" || status === "running")) {
      interval = setInterval(async () => {
        try {
          const data = await requestJson<any>(`/api/v1/sessions/${sessionId}`);

          if (data.status !== status) {
            setStatus(data.status);
          }

          if (data.runtime_state) {
            const currentSpent = data.runtime_state.spentUsdc ??
              (data.runtime_state.initialBudgetUsdc !== undefined ? data.runtime_state.initialBudgetUsdc - data.runtime_state.remainingBudgetUsdc : 0);

            setSpent(currentSpent);
            setPurchases(data.runtime_state.purchaseCount || 0);
            if (data.runtime_state.purchasedEntitlements) {
              setPurchasedItems(data.runtime_state.purchasedEntitlements);
            }

            // Format logs from actions as new chat messages
            const actions: AgentAction[] = data.runtime_state.actions || [];

            setMessages(prev => {
              const newMessages = [...prev];

              // Only add messages that we haven't added yet based on a simple unique ID
              const addIfUnique = (id: string, content: ReactNode) => {
                if (!newMessages.some(m => m.id === id)) {
                  newMessages.push({ id, role: "agent", content });
                }
              };

              if (data.status === "queued") addIfUnique(`status-queued-${data.id}`, "Session queued. Awaiting available worker...");
              if (data.status === "running") addIfUnique(`status-running-${data.id}`, "Worker started. I am analyzing your request...");

              actions.forEach((a, index) => {
                if (a.action === "purchase" || a.action === "upgrade") {
                  let tier = a.tier;
                  let provider = a.provider;

                  if (!tier || !provider) {
                    const match = (data.runtime_state.purchasedEntitlements || []).find((e: any) => e.symbol === a.symbol);
                    if (match) {
                      tier = tier || match.tier;
                      provider = provider || match.provider_id;
                    }
                  }

                  const tierStr = tier ? ` ${tier.toUpperCase()}` : "";
                  const provStr = provider ? ` from ${provider}` : "";

                  // If amount is missing, estimate it based on tier
                  const estimatedPrice = tier === "full" ? 0.0050 : 0.0010;
                  const costStr = a.amount_usdc !== undefined
                    ? ` for $${Number(a.amount_usdc).toFixed(4)} USDC`
                    : ` for $${estimatedPrice.toFixed(4)} USDC`;

                  const timeStr = new Date(a.at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });

                  addIfUnique(
                    `action-${data.id}-${index}`,
                    <div>
                      ✅ Purchased{tierStr} report on <span className="agent-runner-purchase-symbol">{a.symbol}</span>{provStr}{costStr}
                      <div className="agent-runner-purchase-time">{timeStr}</div>
                    </div>
                  );
                }
              });

              if (data.status === "stopped") addIfUnique(`status-stopped-${data.id}`, "⚠️ Session has been stopped.");

              if (data.status === "completed") {
                const startedAt = data.runtime_state.startedAt ? new Date(data.runtime_state.startedAt).getTime() : 0;
                const endedAt = data.runtime_state.endedAt ? new Date(data.runtime_state.endedAt).getTime() : (data.runtime_state.actions && data.runtime_state.actions.length > 0 ? new Date(data.runtime_state.actions[data.runtime_state.actions.length - 1].at).getTime() : Date.now());
                let durationStr = "0s";
                if (startedAt && endedAt) {
                  const ms = Math.max(0, endedAt - startedAt);
                  const s = Math.floor(ms / 1000) % 60;
                  const m = Math.floor(ms / (1000 * 60)) % 60;
                  const h = Math.floor(ms / (1000 * 60 * 60));
                  durationStr = `${h > 0 ? h + 'h ' : ''}${m > 0 ? m + 'm ' : ''}${s}s`;
                }

                addIfUnique(`status-completed-${data.id}`, (
                  <div className="agent-runner-complete-card">
                    <h3>🎉 Session Completed!</h3>
                    <p style={{ color: "var(--t2)" }}>I've finished researching and executing purchases based on your prompt.</p>
                    
                    <div className="agent-runner-complete-stats" style={{ gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                      <div style={{ display: 'flex', flexDirection: 'column' }}>
                        <span style={{ fontSize: '11px', color: 'var(--t3)', textTransform: 'uppercase' }}>Target Budget</span>
                        <strong style={{ color: '#fff' }}>${Number(data.budget_usdc || 0).toFixed(4)} USDC</strong>
                      </div>
                      
                      <div style={{ display: 'flex', flexDirection: 'column' }}>
                        <span style={{ fontSize: '11px', color: 'var(--t3)', textTransform: 'uppercase' }}>Actually Spent</span>
                        <strong style={{ color: 'var(--accent)' }}>${currentSpent.toFixed(4)} USDC</strong>
                      </div>

                      <div style={{ display: 'flex', flexDirection: 'column' }}>
                        <span style={{ fontSize: '11px', color: 'var(--t3)', textTransform: 'uppercase' }}>Purchased Reports</span>
                        <strong style={{ color: '#fff' }}>{data.runtime_state.purchaseCount || 0}</strong>
                      </div>
                      
                      <div style={{ display: 'flex', flexDirection: 'column' }}>
                        <span style={{ fontSize: '11px', color: 'var(--t3)', textTransform: 'uppercase' }}>Duration</span>
                        <strong style={{ color: '#fff' }}>{durationStr}</strong>
                      </div>
                      
                      {data.runtime_state.candidatesEvaluated > 0 && (
                        <div style={{ gridColumn: 'span 2', display: 'flex', flexDirection: 'column', marginTop: '4px', paddingTop: '8px', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
                          <span style={{ fontSize: '11px', color: 'var(--t3)', textTransform: 'uppercase' }}>Evaluated Candidates</span>
                          <span style={{ fontSize: '12px', color: 'var(--t2)' }}>Analyzed {data.runtime_state.candidatesEvaluated} reports before making decisions.</span>
                        </div>
                      )}
                    </div>
                  </div>
                ));
              }
              if (data.status === "error") addIfUnique(`status-error-${data.id}`, "❌ Session Failed!");

              return newMessages;
            });
          }
        } catch (err) {
          console.error("Polling error", err);
        }
      }, 5000);
    }

    return () => clearInterval(interval);
  }, [sessionId, status]);

  if (!open) return null;

  const handleStart = async (e: FormEvent) => {
    e.preventDefault();
    if (!prompt.trim()) return;

    const userText = prompt.trim();
    setPrompt("");

    // Add user message immediately
    setMessages(prev => [...prev, { id: `user-${Date.now()}`, role: "user", content: userText }]);

    // If session is active or stopped, PATCH it instead of creating a new one
    if (sessionId && (status === "queued" || status === "running" || status === "stopped")) {
      let newBudget: number | null = null;
      const budgetMatch = userText.toLowerCase().match(/(?:budget|under|dưới|tối đa|limit|max|price|of|xuống còn|lên)\s*(?:[\$]?)\s*([0-9\.]+)/i);
      const usdcMatch = userText.toLowerCase().match(/([0-9\.]+)\s*(?:usdc|usd)/i);
      const dollarMatch = userText.toLowerCase().match(/\$\s*([0-9\.]+)/i);

      if (budgetMatch) newBudget = parseFloat(budgetMatch[1]);
      else if (usdcMatch) newBudget = parseFloat(usdcMatch[1]);
      else if (dollarMatch) newBudget = parseFloat(dollarMatch[1]);

      const updatePayload: any = { task: userText };
      if (newBudget !== null) {
        updatePayload.budget_usdc = newBudget;
        setBudget(newBudget);
      }

      try {
        await requestJson(`/api/v1/sessions/${sessionId}`, {
          method: "PATCH",
          body: JSON.stringify(updatePayload)
        });
        setMessages(prev => [...prev, {
          id: `sys-${Date.now()}`,
          role: "agent",
          content: `Got it! I've updated your instructions${newBudget !== null ? ` and set the budget to $${newBudget} USDC` : ''}.`
        }]);
      } catch (err: any) {
        setMessages(prev => [...prev, { id: `err-${Date.now()}`, role: "agent", content: `❌ Failed to update session: ${err.message}` }]);
      }
      return;
    }

    // ----------------------------------------------------
    // Create new session logic
    // ----------------------------------------------------
    setSessionId(null);
    setSpent(0);
    setPurchases(0);
    setPurchasedItems([]);

    // Parse budget
    let parsedBudget = 10.0;
    const kwMatch = userText.toLowerCase().match(/(?:budget|under|dưới|tối đa|limit|max|price|of|còn)\s*(?:[\$]?)\s*([0-9\.]+)/i);
    const usdcMatch = userText.toLowerCase().match(/([0-9\.]+)\s*(?:usdc|usd)/i);
    const dollarMatch = userText.toLowerCase().match(/\$\s*([0-9\.]+)/i);

    if (kwMatch) parsedBudget = parseFloat(kwMatch[1]);
    else if (usdcMatch) parsedBudget = parseFloat(usdcMatch[1]);
    else if (dollarMatch) parsedBudget = parseFloat(dollarMatch[1]);

    // Ensure they have enough in gateway balance
    if (parsedBudget > globalBalance) {
      setMessages(prev => [...prev, {
        id: `err-bal-${Date.now()}`,
        role: "agent",
        content: `❌ You only have $${globalBalance.toFixed(2)} USDC in your Platform Wallet, which is less than your requested budget of $${parsedBudget}. Please deposit more funds via Circle Gateway.`
      }]);
      return;
    }

    setBudget(parsedBudget);

    try {
      setStatus("creating");
      
      // 1. Check for Web3 Wallet
      if (!(window as any).ethereum) {
        setMessages(prev => [...prev, { id: `err-wallet-${Date.now()}`, role: "agent", content: `❌ Please install MetaMask or a Web3 wallet to authorize Gateway transfers.` }]);
        setStatus("error");
        return;
      }
      // Parse quantity
      let parsedQty: number | null = null;
      const qtyMatch = userText.toLowerCase().match(/(?:buy|purchase|get)\s+(\d+)/i);
      if (qtyMatch) {
        parsedQty = parseInt(qtyMatch[1], 10);
      }

      // We have removed the mock EIP-712 TransferWithAuthorization signing logic.
      // In the new architecture, this step will either generate a Session Key for a Circle MSCA,
      // or sign an EIP-2612 Permit allowance.
      
      setMessages(prev => [...prev, {
        id: `sys-started-${Date.now()}`,
        role: "agent",
        content: `✅ Submitting to backend...`
      }]);

      const sessionData = await requestJson<any>(`/api/v1/sessions`, {
        method: "POST",
        body: JSON.stringify({
          title: "Autonomous Web UI Session",
          task: userText,
          budget_usdc: parsedBudget,
          owner_wallet: wallet
        })
      });
      const newId = sessionData.id;
      setSessionId(newId);

      await requestJson<any>(`/api/v1/sessions/${newId}/start`, { method: "POST" });
      setStatus("queued");

    } catch (err: any) {
      setStatus("error");
      setMessages(prev => [...prev, { id: `err-${Date.now()}`, role: "agent", content: `❌ Error: ${err.message}` }]);
    }
  };

  const handleStop = async () => {
    if (!sessionId) return;
    try {
      await requestJson<any>(`/api/v1/sessions/${sessionId}/stop`, { method: "POST" });
      setStatus("stopped");
    } catch (err: any) {
      console.error(err);
    }
  };

  const handleResume = async () => {
    if (!sessionId) return;
    try {
      await requestJson<any>(`/api/v1/sessions/${sessionId}/resume`, { method: "POST" });
      setStatus("queued");
    } catch (err: any) {
      console.error(err);
    }
  };

  const currentWalletBalance = Math.max(0, globalBalance - spent);
  const remainingBudget = Math.max(0, budget - spent);
  const shortWallet = wallet ? `${wallet.slice(0, 6)}…${wallet.slice(-4)}` : "—";
  
  let statusText = "Active";
  let statusClass = "ready";
  
  if (currentWalletBalance <= 0) {
    statusText = "Gateway Empty";
    statusClass = "failed";
  } else if (remainingBudget <= 0) {
    statusText = "Budget Exhausted";
    statusClass = "failed";
  } else if (status === "stopped") {
    statusText = "User Paused";
    statusClass = "failed";
  } else if (status === "error") {
    statusText = "Error";
    statusClass = "failed";
  } else if (status === "completed") {
    statusText = "Completed";
    statusClass = "ready";
  }

  const curStage = stageIndex(status, purchases);
  const stageFailed = status === "error" || status === "stopped";
  const stageProgressPct = (curStage / (STAGE_LABELS.length - 1)) * 100;

  const renderMessage = (msg: ChatMessage) => {
    const speaker = msg.role === "user" ? "You" : "Agent";
    const tone = msg.role === "user" ? "t-val" : "t-dim";
    return (
      <div key={msg.id} className={`agent-chat-message ${tone}`}>
        <span className="agent-message-speaker">{speaker}</span>
        <div>{msg.content}</div>
      </div>
    );
  };

  return (
    <div className="modal-backdrop open agent-buyer-backdrop">
      <div className="agent-buyer-modal" role="dialog">

        {/* Header */}
        <div className="agent-buyer-header">
          <div>
            <div className="agent-buyer-eyebrow">Autonomous Background Runner</div>
            <div className="agent-buyer-title">Autonomous Agent</div>
            <div className="agent-buyer-subtitle">
              Session {sessionId ? sessionId.split("-")[0] : "None"} · give it a task and a budget, it works while you're away.
            </div>
          </div>
          <div className="agent-header-right">
            <div className="agent-timing-strip">
              <div className="agent-timing-item">
                <span className="agent-timing-label">Gateway</span>
                <span className="agent-timing-val">${currentWalletBalance.toFixed(2)}</span>
              </div>
              <div className="agent-timing-item">
                <span className="agent-timing-label">Spent</span>
                <span className="agent-timing-val">${spent.toFixed(4)}</span>
              </div>
              <div className="agent-timing-item">
                <span className="agent-timing-label">Budget</span>
                <span className="agent-timing-val">${budget.toFixed(2)}</span>
              </div>
            </div>
            <button className="icon-button" onClick={onClose} title="Close">
              <i className="ti ti-x" />
            </button>
          </div>
        </div>

        {/* Session stage strip */}
        <div className="agent-session-stage stage-count-4">
          <div className="agent-stage-progress-bar" style={{ left: "12.5%", width: "75%" }}>
            <div
              className={`agent-stage-progress-fill${stageFailed ? " is-failed" : ""}`}
              style={{ width: `${stageProgressPct}%` }}
            />
          </div>
          {STAGE_LABELS.map((label, i) => {
            let cls = "";
            if (stageFailed && i === curStage) cls = "failed";
            else if (i < curStage) cls = "done";
            else if (i === curStage) cls = status === "completed" ? "done" : "active";
            return (
              <div key={label} className={`agent-stage-dot ${cls}`}>
                <span />
                {label}
              </div>
            );
          })}
        </div>

        <div className="agent-buyer-grid">
          {/* Chat log */}
          <div className="agent-chat-panel">
            <div className="agent-chat-topline">
              <span className={`agent-live-pill${status === "running" ? " active" : ""}${status === "error" ? " error" : ""}`}>
                {status}
              </span>
              <span className="agent-chat-wallet">{shortWallet}</span>
            </div>

            <div className="agent-chat-log">
              {messages.map(renderMessage)}
              {status === "running" && (
                <div className="agent-chat-message t-dim">
                  <span className="agent-message-speaker">Agent</span>
                  <i className="ti ti-dots agent-runner-typing-dots" />
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            <form onSubmit={handleStart} className="agent-chat-composer">
              <span className="agent-chat-caret">$</span>
              <input
                className="agent-bar-input"
                type="text"
                placeholder={status === "queued" || status === "running" || status === "creating" ? "Modify your request (e.g. 'đổi budget xuống còn 0.5$')" : "Buy 3 trending reports under $15..."}
                value={prompt}
                onChange={e => setPrompt(e.target.value)}
                disabled={status === "creating"}
              />
              <button type="submit" className="submit-btn" disabled={!prompt.trim() || status === "creating"} title="Send">
                <i className="ti ti-send" />
              </button>
            </form>
          </div>

          {/* Decision / control panel */}
          <div className="agent-decision-panel">
            <div className="agent-dp-block">
              <div className="agent-dp-block-label">Funding</div>
              <div className="agent-funding-bar">
                <div className="agent-funding-row">
                  <span className="agent-funding-label">Gateway Balance</span>
                  <span className="agent-funding-val">${currentWalletBalance.toFixed(4)}</span>
                </div>
                <div className="agent-funding-row">
                  <span className="agent-funding-label">Session Budget</span>
                  <span className="agent-funding-val">${spent.toFixed(4)} / ${budget.toFixed(2)}</span>
                </div>
                <div className="agent-funding-row">
                  <span className="agent-funding-label">Status</span>
                  <span className={`agent-funding-status ${statusClass}`}>
                    {statusText}
                  </span>
                </div>
              </div>
            </div>

            <div className="agent-dp-block" style={{ flex: 1, minHeight: 0 }}>
              <div className="agent-dp-block-label">Purchases ({purchases})</div>
              {purchasedItems.length === 0 ? (
                <div className="agent-empty-card">No purchases yet — the agent will list each report here as it buys.</div>
              ) : (
                <div className="agent-runner-purchases-list">
                  {purchasedItems.map((item, i) => (
                    <div key={i} className="agent-invoice-row">
                      <span>{item.symbol}{item.tier ? ` · ${String(item.tier).toUpperCase()}` : ""}</span>
                      <span>{item.provider_id || ""}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {(status === "queued" || status === "running" || status === "stopped" || status === "error" || status === "completed") && (
              <div className="agent-modal-actions">
                {status === "queued" || status === "running" ? (
                  <button className="agent-modal-cancel" onClick={handleStop}>
                    Pause Agent
                  </button>
                ) : (
                  <div style={{ display: "flex", gap: "10px", width: "100%" }}>
                    {status === "stopped" && (
                      <button className="agent-modal-primary" style={{ flex: 1 }} onClick={handleResume}>
                        Resume Agent
                      </button>
                    )}
                    <button 
                      className="agent-modal-cancel" 
                      style={{ flex: 1 }}
                      onClick={() => {
                        setSessionId(null);
                        setStatus("idle");
                        setMessages([{ id: "sys-start", role: "agent", content: "Hi! I'm your Autonomous Background Runner. Tell me what reports you'd like me to purchase, and specify a budget (e.g. 'Buy 3 trending reports under $1.50 USDC')." }]);
                        setSpent(0);
                        setPurchases(0);
                        setPurchasedItems([]);
                        setPrompt("");
                      }}
                    >
                      New Session
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}