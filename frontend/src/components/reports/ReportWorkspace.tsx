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
  reportWinRateValue: any;
  reportWinRateCiLabel: any;
  reportAvgProfitLabel: any;
  reportAvgProfitCiLabel: any;
  reportPercentileRows: any;
}

export function ReportWorkspace(props: ReportWorkspaceProps) {
  const { activeQuery, unlockedReport, reportCollapsed, reportDetailsOpen, setReportDetailsOpen, reportAnalogs, isPreviewReport, formatCompactMoney, formatDateTime, formatRawPercent, shortAddress, reportWinRateValue, reportWinRateCiLabel, reportAvgProfitLabel, reportAvgProfitCiLabel, reportPercentileRows } = props;
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

        </div>
      ) : (
        <div className="empty-state" style={{ textAlign: "center", color: "var(--t3)", marginTop: 80 }}>
          No signal selected yet or payment pending.
        </div>
      )}
    </>
  );
}
