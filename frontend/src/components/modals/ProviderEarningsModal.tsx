import type { ReactNode } from "react";

interface ProviderEarningsModalProps {
  open: boolean;
  title?: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
}

export function ProviderEarningsModal({
  open,
  title = "Creator Earnings",
  subtitle = "Provider-owner revenue, direct Gateway split balances, and claimable QMA ledger earnings.",
  onClose,
  children,
}: ProviderEarningsModalProps) {
  if (!open) return null;

  return (
    <div className="modal-backdrop open" style={{ display: "flex" }}>
      <div
        className="wallet-profile-modal withdraw-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="creator-earnings-title"
        style={{ display: "block", maxWidth: 720 }}
      >
        <div className="modal-header">
          <div>
            <div className="modal-title" id="creator-earnings-title">{title}</div>
            <div className="modal-subtitle">{subtitle}</div>
          </div>
          <button className="icon-button" type="button" title="Close" onClick={onClose}>x</button>
        </div>
        {children}
      </div>
    </div>
  );
}
