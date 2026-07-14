import { Loader } from "../ui/Loader";

interface ReportWorkspaceProps {
  activeQuery: any;
  unlockedReport: any;
  reportCollapsed: any;
  reportDetailsOpen: any;
  setReportDetailsOpen: any;
  reportAnalogs: any;
  isPreviewReport: any;
  formatCompactMoney: any;
  formatDateTime: any;
  formatRawPercent: any;
  shortAddress: any;
  paymentDetails: any;
  refreshPlatformTables: any;
  platformTablesError: any;
  platformSummary: any;
  sellerAddress: any;
  platformPaymentsTotal: any;
  platformTablesLoading: any;
  platformPayments: any;
  gatewayStatusBadge: any;
  renderSettlementRef: any;
  platformPaymentsPage: any;
  platformPaymentsTotalPages: any;
  changePlatformPaymentsPage: any;
  tierLabel: any;
  formatUsdc: any;
  platformPayers: any;
  platformPayersPage: any;
  platformPayersTotalPages: any;
  platformPayersTotal: any;
  changePlatformPayersPage: any;
  reportWinRateValue: any;
  reportWinRateCiLabel: any;
  reportAvgProfitLabel: any;
  reportAvgProfitCiLabel: any;
  reportPercentileRows: any;
}

export function ReportWorkspace(props: ReportWorkspaceProps) {
  const { activeQuery, unlockedReport, reportCollapsed, reportDetailsOpen, setReportDetailsOpen, reportAnalogs, isPreviewReport, formatCompactMoney, formatDateTime, formatRawPercent, shortAddress, paymentDetails, refreshPlatformTables, platformTablesError, platformSummary, sellerAddress, platformPaymentsTotal, platformTablesLoading, platformPayments, gatewayStatusBadge, renderSettlementRef, platformPaymentsPage, platformPaymentsTotalPages, changePlatformPaymentsPage, tierLabel, formatUsdc, platformPayers, platformPayersPage, platformPayersTotalPages, platformPayersTotal, changePlatformPayersPage, reportWinRateValue, reportWinRateCiLabel, reportAvgProfitLabel, reportAvgProfitCiLabel, reportPercentileRows } = props;
  return (
    <>
      {/* REPORT VIEW */}
      {unlockedReport && !reportCollapsed ? (
        <div className="report-container" id="report-view-element">
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
              {unlockedReport.matched_k || reportAnalogs(unlockedReport).length || 0} similar historical events in a{" "}
              {unlockedReport.regime_cluster || "regime cluster"} context. In those past cases, outcomes were{" "}
              {reportWinRateValue(unlockedReport) >= 60
                ? "mostly positive"
                : "mixed"}{" "}
              with a {reportWinRateValue(unlockedReport).toFixed(1)}% win
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
                  {(unlockedReport.matched_k ?? reportAnalogs(unlockedReport).length) ?? 0}
                </strong>
                <small className="summary-card-desc">Historical matches in QMA's dataset</small>
              </div>
              <div className="summary-card">
                <span className="summary-card-label">Win rate</span>
                <strong className="summary-card-value">
                  {reportWinRateValue(unlockedReport).toFixed(1)}%
                </strong>
                <small className="summary-card-desc">How often similar cases finished positive</small>
              </div>
              <div className="summary-card">
                <span className="summary-card-label">Typical outcome</span>
                <strong className="summary-card-value">
                  {isPreviewReport(unlockedReport)
                    ? "Full"
                    : unlockedReport.percentiles?.P50_median
                      ? `${unlockedReport.percentiles.P50_median.toFixed(2)}%`
                      : "n/a"}
                </strong>
                <small className="summary-card-desc">Median peak result in past analogs</small>
              </div>
            </div>
            <p className="plain-summary-disclaimer">
              Past performance does not guarantee future results. This is historical context, not trading advice.
            </p>
          </div>

          {/* Weighted outcome KPI */}
          <div className="report-section section-span-2 advanced-control">
            <div className="section-header">Historical Analog Outcome (Weighted)</div>
            <div className="kpi-grid">
              <div className="kpi-card">
                <span className="kpi-title">Analog Win Rate</span>
                <div className="kpi-value text-green">
                  {reportWinRateValue(unlockedReport).toFixed(1)}%
                </div>
                <span className="kpi-sub">{reportWinRateCiLabel(unlockedReport)}</span>
              </div>
              <div className="kpi-card">
                <span className="kpi-title">Avg Historical Peak PnL</span>
                <div className="kpi-value text-green">
                  {reportAvgProfitLabel(unlockedReport)}
                </div>
                <span className="kpi-sub">{reportAvgProfitCiLabel(unlockedReport)}</span>
              </div>
            </div>
          </div>

          {/* Regime details */}
          <div className="report-section advanced-control">
            <div className="section-header">Similar Historical Regime</div>
            <div className="info-list">
              <div className="info-item">
                <span className="info-label info-label-emphasis">
                  {unlockedReport.regime_cluster || "n/a"}
                </span>
              </div>
              <div className="info-desc info-desc-compact">
                {unlockedReport.regime_description || "Regime details loaded from matching catalogs."}
              </div>
              <div className="info-divider">
                <div className="info-item">
                  <span className="info-label">OOD Status</span>
                  <span className="pnl-badge pnl-badge-compact">
                    {unlockedReport.is_ood ? "Out-of-Distribution" : "In-Distribution"}
                  </span>
                </div>
                <div className="info-item mt-6">
                  <span className="info-label">Chi2 p-value</span>
                  <span className="mono-td info-value">
                    {(unlockedReport.ood_chi2_p || 1.0).toFixed(5)}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Advanced details toggler */}
          <div className="advanced-only section-span-all advanced-dropdown-wrapper mt-12">
            <button
              type="button"
              className={`advanced-dropdown-trigger ${reportDetailsOpen ? "expanded" : ""}`}
              onClick={() => setReportDetailsOpen((open: boolean) => !open)}
            >
              <span className="trigger-label">
                {reportDetailsOpen ? "Hide" : "Show"} Detailed Quant Diagnostics & Analogs
              </span>
              <svg className="trigger-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="6 9 12 15 18 9"></polyline>
              </svg>
            </button>
            <div className="advanced-dropdown-content" style={{ display: reportDetailsOpen ? "grid" : "none" }}>
              <div className="report-section">
                <div className="section-header">Historical Outcome Percentiles</div>
                <div className="dist-chart">
                  {reportPercentileRows(unlockedReport).map((percentile: any) => {
                    return (
                      <div className="dist-row" key={percentile.key}>
                        <span className="dist-label">{percentile.label}</span>
                        <div className="dist-bar-bg">
                          <div className="dist-bar-fill" style={{ width: `${percentile.width}%` }}></div>
                        </div>
                        <span className="dist-val">{percentile.text}</span>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="report-section section-span-2">
                <div className="section-header">Closest Historical Funding Events</div>
                <div className="table-wrap">
                  <table className="analogs-table">
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
                      {reportAnalogs(unlockedReport).map((analog: any, analogIdx: number) => (
                        <tr key={analogIdx}>
                          <td className="mono-td">{analog.symbol || "n/a"}</td>
                          <td className="mono-td">{analog.fundingRate != null ? `${(Number(analog.fundingRate) * 100).toFixed(3)}%` : "n/a"}</td>
                          <td className="mono-td">{isPreviewReport(unlockedReport) ? "Preview" : analog.marketCap != null ? formatCompactMoney(Number(analog.marketCap)) : "n/a"}</td>
                          <td className="mono-td">{isPreviewReport(unlockedReport) ? "Preview" : analog.age_days != null ? `${Math.round(Number(analog.age_days))}d ago` : formatDateTime(analog.timestamp || analog.time)}</td>
                          <td className="mono-td">{isPreviewReport(unlockedReport) ? "Preview" : analog.decay_weight != null ? Number(analog.decay_weight).toFixed(3) : "n/a"}</td>
                          <td className="mono-td">{analog.similarity != null ? `${(Number(analog.similarity) * 100).toFixed(2)}%` : "n/a"}</td>
                          <td>
                            <span className={`pnl-badge ${Number(analog.profit_pct ?? analog.peak_pnl ?? analog.pnl ?? 0) >= 0 ? "win" : "loss"}`}>
                              {formatRawPercent(analog.profit_pct ?? analog.peak_pnl ?? analog.pnl)}
                            </span>
                          </td>
                        </tr>
                      ))}
                      {!reportAnalogs(unlockedReport).length ? (
                        <tr>
                          <td className="mono-td" colSpan={7}>No historical analog rows returned for this report.</td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="report-section section-span-all">
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
                      <span className="text-green">Arcscan batch tx confirmed:</span>{" "}
                      <a className="tx-link" href={unlockedReport.invoice.explorer_url} target="_blank" rel="noreferrer">
                        {shortAddress(unlockedReport.invoice.transaction_hash)}
                      </a>
                    </div>
                  ) : unlockedReport.invoice?.settlement_id ? (
                    <div className="risk-item">
                      <span className="text-amber">Circle accepted payment.</span> Arcscan batch tx is pending. Settlement ID:{" "}
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
          </div>

          <details
            className="report-section section-span-all platform-stats-section platform-stats-section-compact"
            onToggle={(event) => {
              if ((event.currentTarget as HTMLDetailsElement).open) {
                refreshPlatformTables(1, 1);
              }
            }}
          >
            <summary className="section-header platform-stats-summary">
              Platform Analytics & Payment Activity <span className="platform-stats-hint">(Click to view)</span>
            </summary>
            {platformTablesError ? (
              <div className="risk-item platform-tables-error">{platformTablesError}</div>
            ) : null}
            <div className="seller-balance-grid mt-16">
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
                  {platformPaymentsTotal ? <span className="table-count">({platformPaymentsTotal})</span> : null}
                </div>
                <div className="table-scroll-x">
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
                        <tr><td colSpan={6}><Loader label="Loading payments..." compact size="sm" className="table-loader" /></td></tr>
                      ) : platformPayments.length ? (
                        platformPayments.map((event: any, idx: number) => (
                          <tr key={event.event_id || event.settlement_id || event.invoice_id || idx}>
                            <td className="mono-td">
                              {event.symbol || "n/a"}
                              <div className="table-meta table-meta-spaced">{formatDateTime(event.paid_at)}</div>
                            </td>
                            <td><span className="provider-badge">{event.provider_id || "funding_memory"}</span></td>
                            <td title={event.payer_address || ""}>{event.payer_address ? shortAddress(event.payer_address) : "n/a"}</td>
                            <td>
                              {formatUsdc(event.amount_usdc)}
                              <div className="table-meta">{tierLabel(event.tier_category || event.tier)}</div>
                            </td>
                            <td>{gatewayStatusBadge(event.gateway_status)}</td>
                            <td className="mono-td">{renderSettlementRef(event)}</td>
                          </tr>
                        ))
                      ) : (
                        <tr><td colSpan={6} className="table-empty-cell">No payments yet.</td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
                <div className="table-pager profile-pager">
                  <button type="button" className="refresh-btn" disabled={platformPaymentsPage <= 1 || platformTablesLoading} onClick={() => changePlatformPaymentsPage(Math.max(1, platformPaymentsPage - 1))}>
                    Prev
                  </button>
                  <span className="table-page-label">Page {platformPaymentsPage} / {platformPaymentsTotalPages}</span>
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
                        <tr><td colSpan={4}><Loader label="Loading wallets..." compact size="sm" className="table-loader" /></td></tr>
                      ) : platformPayers.length ? (
                        platformPayers.map((payer: any, idx: number) => {
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
    </>
  );
}
