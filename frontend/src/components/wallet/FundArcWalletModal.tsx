export function FundArcWalletModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null;
  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <section className="modal-panel" role="dialog" aria-modal="true" aria-labelledby="fund-arc-title" onClick={(event) => event.stopPropagation()}>
        <header className="modal-header">
          <h2 id="fund-arc-title">Fund Arc Wallet</h2>
          <button type="button" onClick={onClose}>x</button>
        </header>
        <div className="placeholder-panel">
          Port `fund-arc-modal` logic from `public/app.js`: chain readiness, on-chain USDC, Gateway balance, deposit and approve actions.
        </div>
      </section>
    </div>
  );
}
