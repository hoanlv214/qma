import React, { useState, useRef, useEffect } from "react";
import { shortAddress } from "../../services/wallet";
import type { QmaRoute } from "../../app/routes";

interface GlobalHeaderProps {
  activePage: QmaRoute;
  onNavigate: (route: QmaRoute) => void;
  walletAddress: string;
  onConnect: () => void;
  onDisconnect: () => void;
  userRole?: string;
  onOpenDeposit?: () => void;
  onOpenEarnings?: () => void;
  rightControls?: React.ReactNode;
}

export function GlobalHeader({
  activePage,
  onNavigate,
  walletAddress,
  onConnect,
  onDisconnect,
  userRole,
  onOpenDeposit,
  onOpenEarnings,
  rightControls
}: GlobalHeaderProps) {
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const [copySuccess, setCopySuccess] = useState(false);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (walletAddress) {
      navigator.clipboard.writeText(walletAddress);
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    }
  };

  const navLinks = [
    {
      id: "app",
      label: "App",
      icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" width="18" height="18"><line x1="18" y1="20" x2="18" y2="10"></line><line x1="12" y1="20" x2="12" y2="4"></line><line x1="6" y1="20" x2="6" y2="14"></line></svg>
    },
    {
      id: "traction",
      label: "Traction",
      icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" width="18" height="18"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"></polyline><polyline points="17 6 23 6 23 12"></polyline></svg>
    },
    {
      id: "marketplace",
      label: "Marketplace",
      icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" width="18" height="18"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"></path><line x1="3" y1="6" x2="21" y2="6"></line><path d="M16 10a4 4 0 0 1-8 0"></path></svg>
    }
  ];

  return (
    <header className="global-header">
      {/* 1. Left - Brand */}
      <a href="/" className="logo-item qma-logo-item" title="QMA" onClick={(e) => { e.preventDefault(); onNavigate("landing"); }}>
        <div className="logo-icon">QM</div>
        <div className="logo-text">QMA</div>
      </a>

      {/* 2. Center - Navigation */}
      <nav className="global-nav-center">
        {navLinks.map(link => (
          <button
            key={link.id}
            type="button"
            className={`global-nav-link ${activePage === link.id ? "active" : ""}`}
            onClick={() => onNavigate(link.id as QmaRoute)}
            title={link.label}
          >
            <div className="nav-icon-wrapper">
              {link.icon}
            </div>
            <span className="nav-label">
              {link.label}
            </span>
          </button>
        ))}
      </nav>

      {/* 3. Right - Context Controls & Wallet */}
      <div className="global-nav-right">
        {rightControls && <div className="global-nav-context">{rightControls}</div>}

        {!walletAddress ? (
          <button type="button" className="connect-btn-primary" onClick={onConnect}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="16" height="16" style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }}>
              <path d="M20 12V8H6a2 2 0 0 1-2-2c0-1.1.9-2 2-2h12v4"></path>
              <path d="M4 6v12c0 1.1.9 2 2 2h14v-4H6a2 2 0 0 1-2-2"></path>
              <path d="M18 12a2 2 0 1 1 0 4 2 2 0 0 1 0-4Z"></path>
            </svg>
            Connect Wallet
          </button>
        ) : (
          <div className="wallet-dropdown-container" ref={dropdownRef}>
            <button
              type="button"
              className={`wallet-dropdown-btn ${dropdownOpen ? "active" : ""}`}
              onClick={() => setDropdownOpen(!dropdownOpen)}
            >
              <div className="wallet-avatar">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="16" height="16">
                  <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"></path>
                  <circle cx="12" cy="7" r="4"></circle>
                </svg>
              </div>
              <div className="wallet-address-info">
                <span className="wallet-short-address">{shortAddress(walletAddress)}</span>
              </div>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={`chevron ${dropdownOpen ? "up" : "down"}`} width="14" height="14">
                <polyline points="6 9 12 15 18 9"></polyline>
              </svg>
            </button>

            {dropdownOpen && (
              <div className="wallet-dropdown-menu">
                <div className="dropdown-header">
                  <div className="dropdown-address-row">
                    <span className="mono-address">{shortAddress(walletAddress)}</span>
                    <button className="copy-btn" onClick={handleCopy} title="Copy address">
                      {copySuccess ? (
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="14" height="14"><polyline points="20 6 9 17 4 12"></polyline></svg>
                      ) : (
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="14" height="14"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                      )}
                    </button>
                  </div>
                  {userRole && userRole !== "none" && (
                    <div style={{ marginTop: 6 }}>
                      <span className={`wallet-role-badge role-${userRole}`}>Role: {userRole}</span>
                    </div>
                  )}
                </div>


                <div className="dropdown-actions">
                  <button className="dropdown-action-btn" onClick={() => { onNavigate("profile"); setDropdownOpen(false); }}>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="16" height="16"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>
                    Profile & History
                  </button>

                  {onOpenDeposit && (
                    <button className="dropdown-action-btn" onClick={() => { onOpenDeposit(); setDropdownOpen(false); }}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="16" height="16"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
                      Deposit Funds
                    </button>
                  )}

                  {(userRole?.toLowerCase() === "creator" || userRole?.toLowerCase() === "provider") && onOpenEarnings && (
                    <button className="dropdown-action-btn" onClick={() => { onOpenEarnings(); setDropdownOpen(false); }}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="16" height="16"><line x1="12" y1="1" x2="12" y2="23"></line><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>
                      Provider Earnings
                    </button>
                  )}
                </div>

                <div className="dropdown-footer">
                  <button className="dropdown-action-btn text-danger" onClick={() => { onDisconnect(); setDropdownOpen(false); }}>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="16" height="16"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>
                    Disconnect
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </header>
  );
}
