export function PaywallPanel() {
  return (
    <aside className="panel paywall-panel">
      <h2>Invoice / Paywall</h2>
      <p>Create invoice, pay x402 split legs, verify, then unlock the exact query-bound report.</p>
      <div className="checklist">
        <span>POST /api/v1/payment/invoice</span>
        <span>Arc Gateway x402 challenge</span>
        <span>POST /api/v1/payment/verify</span>
        <span>POST /api/v1/providers/:id/preview | full-report</span>
      </div>
    </aside>
  );
}
