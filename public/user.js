const API_BASE_URL = String(window.QMA_API_BASE_URL || '').replace(/\/$/, '');
const PAGE_SIZE = 10;

let currentWallet = new URLSearchParams(window.location.search).get('wallet') || localStorage.getItem('qma_connected_wallet') || '';
let currentPage = 1;
let totalPages = 1;
let arcGatewayBaseUrl = '';
let expandedPaymentId = '';
let paymentRowsById = {};

const connectBtn = document.getElementById('profile-connect-btn');
const chainBalanceEl = document.getElementById('user-chain-balance');
const gatewayBalanceEl = document.getElementById('user-gateway-balance');
const paymentCountEl = document.getElementById('user-payment-count');
const spentEl = document.getElementById('user-spent');
const tokenListEl = document.getElementById('user-token-list');
const paymentsBody = document.getElementById('user-payments-body');
const eventsBody = document.getElementById('user-events-body');
const prevBtn = document.getElementById('user-payments-prev');
const nextBtn = document.getElementById('user-payments-next');
const pageLabel = document.getElementById('user-payments-page');

function apiUrl(path) {
    return `${API_BASE_URL}${path}`;
}

function gatewayApiUrl(path) {
    if (!arcGatewayBaseUrl) return '';
    return `${arcGatewayBaseUrl.replace(/\/$/, '')}${path}`;
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function shortAddress(value) {
    if (!value) return 'n/a';
    return `${value.slice(0, 6)}...${value.slice(-4)}`;
}

function formatDateTime(timestamp) {
    if (!timestamp) return 'n/a';
    const ms = timestamp > 10_000_000_000 ? timestamp : timestamp * 1000;
    return new Date(ms).toLocaleString();
}

function formatCompact(num) {
    const n = Number(num);
    if (!Number.isFinite(n)) return 'n/a';
    return new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(n);
}

function formatMoney(num) {
    const n = Number(num);
    if (!Number.isFinite(n)) return 'n/a';
    return `$${formatCompact(n)}`;
}

function formatFunding(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return 'n/a';
    return `${n >= 0 ? '+' : ''}${(n * 100).toFixed(3)}%`;
}

function formatReportPercent(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return 'n/a';
    return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
}

function tierLabel(tier) {
    const normalized = String(tier || 'legacy').toLowerCase();
    if (normalized === 'preview') return 'Preview';
    if (normalized === 'full') return 'Full';
    return 'Legacy';
}

function gatewayStatusBadge(status) {
    if (!status) return '<span class="badge badge-muted">n/a</span>';
    const s = String(status).toLowerCase();
    if (s === 'completed' || s === 'confirmed') {
        return '<span class="badge badge-confirmed">confirmed</span>';
    }
    if (s === 'received' || s === 'batched') {
        return '<span class="badge badge-pending">pending batch</span>';
    }
    return `<span class="badge badge-muted">${escapeHtml(status)}</span>`;
}

function entitlementId(entry = {}) {
    return entry.entitlement_id || entry.query_hash || entry.settlement_id || `${entry.symbol || 'report'}-${entry.paid_at || entry.saved_at || ''}`;
}

function normalizeTier(value) {
    const tier = String(value || 'full').toLowerCase();
    return tier === 'preview' ? 'preview' : tier === 'full' ? 'full' : 'full';
}

function findEntitlementForPayment(payment = {}, entitlements = []) {
    if (!payment || !Array.isArray(entitlements)) return null;
    if (payment.settlement_id) {
        const match = entitlements.find(entry => entry.settlement_id === payment.settlement_id);
        if (match) return match;
    }
    if (payment.invoice_id) {
        const match = entitlements.find(entry => entry.report?.invoice?.invoice_id === payment.invoice_id);
        if (match) return match;
    }
    if (payment.query_hash) {
        const match = entitlements.find(entry => entry.query_hash === payment.query_hash);
        if (match) return match;
    }
    const symbol = String(payment.symbol || '').toUpperCase();
    const tier = normalizeTier(payment.tier_category || payment.tier);
    return entitlements.find((entry) => (
        String(entry.symbol || entry.query?.symbol || '').toUpperCase() === symbol
        && normalizeTier(entry.tier || entry.report?.tier) === tier
        && Math.abs(Number(entry.paid_at || 0) - Number(payment.paid_at || 0)) < 10
    )) || null;
}

function normalizeEntitlementReport(entry = {}) {
    entry = entry || {};
    if (!entry.report) return null;
    return {
        ...entry.report,
        tier: entry.tier || entry.report.tier || entry.report.invoice?.tier || 'full',
        provider_id: entry.provider_id || entry.report.provider_id || entry.report.invoice?.provider_id || 'funding_memory',
        query: entry.query || entry.report.query,
        paid_at: entry.paid_at || entry.report.paid_at,
        invoice: {
            ...(entry.report.invoice || {}),
            amount_usdc: entry.amount_usdc ?? entry.report.invoice?.amount_usdc,
            settlement_id: entry.settlement_id || entry.report.invoice?.settlement_id,
            transaction_hash: entry.transaction_hash || entry.report.invoice?.transaction_hash,
            explorer_url: entry.explorer_url || entry.report.invoice?.explorer_url,
            gateway_status: entry.gateway_status || entry.report.invoice?.gateway_status,
            payer_address: entry.payer_address || entry.report.invoice?.payer_address,
        }
    };
}

function normalizeEntitlementsList(value) {
    if (Array.isArray(value)) return value;
    if (Array.isArray(value?.items)) return value.items;
    if (Array.isArray(value?.data)) return value.data;
    if (Array.isArray(value?.entitlements)) return value.entitlements;
    return [];
}

function paymentsFromEntitlements(entitlements = []) {
    return normalizeEntitlementsList(entitlements)
        .map((entry) => {
            const report = normalizeEntitlementReport(entry);
            const invoice = report?.invoice || entry.report?.invoice || {};
            return {
                symbol: entry.symbol || entry.query?.symbol || report?.query?.symbol,
                paid_at: entry.paid_at || report?.paid_at,
                amount_usdc: entry.amount_usdc ?? invoice.amount_usdc,
                tier: entry.tier || report?.tier,
                provider_id: entry.provider_id || report?.provider_id,
                buyer_type: entry.buyer_type || invoice.buyer_type,
                gateway_status: entry.gateway_status || invoice.gateway_status,
                settlement_id: entry.settlement_id || invoice.settlement_id,
                transaction_hash: entry.transaction_hash || invoice.transaction_hash,
                explorer_url: entry.explorer_url || invoice.explorer_url,
                payer_address: entry.payer_address || invoice.payer_address,
                invoice_id: invoice.invoice_id,
                query_hash: entry.query_hash,
                query: entry.query || report?.query,
            };
        })
        .filter((event) => event.symbol || event.settlement_id || event.invoice_id);
}

function paymentRowId(event = {}, index = 0) {
    return String(event.settlement_id || event.transaction_hash || `${event.symbol || 'payment'}-${event.paid_at || index}`)
        .replace(/[^a-zA-Z0-9_-]/g, '_');
}

function renderDefinitionRows(items) {
    return items.map(([label, value, className = '']) => `
        <div class="receipt-kv ${className}">
            <span>${escapeHtml(label)}</span>
            <strong title="${escapeHtml(value)}">${escapeHtml(value)}</strong>
        </div>
    `).join('');
}

function reportMetric(report = {}, key, fallback = 'n/a') {
    const value = report?.[key];
    return value === undefined || value === null || value === '' ? fallback : value;
}

function firstDefined(...values) {
    return values.find(value => value !== undefined && value !== null && value !== '');
}

function renderPaymentDetail(event = {}, entitlement = {}, rowId = '') {
    entitlement = entitlement || {};
    const report = normalizeEntitlementReport(entitlement);
    if (!report) {
        return `
            <tr class="payment-detail-row" id="receipt-detail-${escapeHtml(rowId)}" hidden>
                <td colspan="8">
                    <div class="receipt-detail-card">
                        <div class="receipt-detail-empty">This payment was verified, but no saved report snapshot was returned for this receipt.</div>
                    </div>
                </td>
            </tr>
        `;
    }
    const query = report.query || entitlement.query || event.query || {};
    const invoice = report.invoice || {};
    const txValue = invoice.transaction_hash || event.transaction_hash || 'n/a';
    const settlementValue = invoice.settlement_id || event.settlement_id || 'n/a';
    const winRate = report.weighted_win_rate ?? report.rough_win_rate;
    const avgPnl = report.weighted_avg_profit;
    const medianPnl = report.percentiles?.P50_median;
    const analogCount = report.matched_k || (Array.isArray(report.analogs) ? report.analogs.length : Array.isArray(report.top_analogs) ? report.top_analogs.length : 'n/a');
    const paymentItems = [
        ['Paid at', formatDateTime(event.paid_at || entitlement.paid_at || report.paid_at)],
        ['Amount', `${Number(event.amount_usdc || invoice.amount_usdc || 0).toFixed(3)} USDC`],
        ['Buyer', shortAddress(event.payer_address || invoice.payer_address || currentWallet)],
        ['Settlement', settlementValue, 'mono-value'],
        ['Arcscan tx', txValue, 'mono-value'],
    ];
    const snapshotItems = [
        ['Symbol', query.symbol || entitlement.symbol || event.symbol || 'n/a'],
        ['Funding', formatFunding(query.fundingRate)],
        ['Market cap', formatMoney(query.marketCap)],
        ['FDV', formatMoney(firstDefined(query.FDV, query.fdv, query.fullyDilutedValuation))],
        ['Circ ratio', firstDefined(query.circRatio, query.circ_ratio, query.circulatingSupplyRatio, 'n/a')],
        ['ATH distance', Number.isFinite(Number(firstDefined(query.fromATH, query.fromATHPercent, query.athDistancePercent))) ? `${Number(firstDefined(query.fromATH, query.fromATHPercent, query.athDistancePercent)).toFixed(2)}%` : 'n/a'],
        ['24h volume', formatMoney(query.volume24h)],
    ];
    const summaryItems = [
        ['Win rate', Number.isFinite(Number(winRate)) ? `${Number(winRate).toFixed(1)}%` : 'n/a'],
        ['Avg PnL', formatReportPercent(avgPnl)],
        ['Median PnL', formatReportPercent(medianPnl)],
        ['Regime', reportMetric(report, 'regime_cluster')],
        ['OOD', report.is_ood === undefined ? 'n/a' : report.is_ood ? 'Out of distribution' : 'In distribution'],
        ['Analogs', String(analogCount)],
    ];
    const explorer = invoice.explorer_url || event.explorer_url;
    return `
        <tr class="payment-detail-row" id="receipt-detail-${escapeHtml(rowId)}" hidden>
            <td colspan="8">
                <div class="receipt-detail-card">
                    <div class="receipt-detail-header">
                        <div>
                            <div class="receipt-detail-title">${escapeHtml(query.symbol || event.symbol || 'Report')} paid snapshot</div>
                            <div class="receipt-detail-subtitle">This is the exact report data saved when the receipt was bought.</div>
                        </div>
                        <button type="button" class="receipt-detail-close" data-row-id="${escapeHtml(rowId)}">Close</button>
                    </div>
                    <div class="receipt-detail-grid">
                    <section class="receipt-detail-panel">
                    <h3>Paid snapshot</h3>
                    ${renderDefinitionRows(snapshotItems)}
                    </section>
                    <section class="receipt-detail-panel">
                    <h3>Report summary</h3>
                    ${renderDefinitionRows(summaryItems)}
                    </section>
                    <section class="receipt-detail-panel">
                        <h3>Payment receipt</h3>
                        ${renderDefinitionRows(paymentItems)}
                        ${explorer ? `<a class="receipt-detail-link" href="${escapeHtml(explorer)}" target="_blank" rel="noreferrer">Open Arcscan reference</a>` : ''}
                    </section>
                    </div>
                </div>
            </td>
        </tr>
    `;
}

function renderLazyPaymentDetail(rowId = '', hasReport = false) {
    return `
        <tr class="payment-detail-row ${hasReport ? 'needs-report-load' : ''}" id="receipt-detail-${escapeHtml(rowId)}" hidden>
            <td colspan="8">
                <div class="receipt-detail-card">
                    <div class="receipt-detail-empty">${hasReport ? 'Loading paid report snapshot...' : 'This payment was verified, but no saved report snapshot was returned for this receipt.'}</div>
                </div>
            </td>
        </tr>
    `;
}

async function loadPaymentDetail(rowId, entitlementId) {
    if (!rowId || !entitlementId || !currentWallet) return;
    const detail = document.getElementById(`receipt-detail-${rowId}`);
    const event = paymentRowsById[rowId] || {};
    if (!detail || !detail.classList.contains('needs-report-load')) return;
    try {
        const resp = await fetch(apiUrl(`/api/v1/wallets/${currentWallet}/reports/${encodeURIComponent(entitlementId)}`));
        if (!resp.ok) throw new Error(`Report endpoint returned ${resp.status}`);
        const data = await resp.json();
        const wrapper = document.createElement('tbody');
        wrapper.innerHTML = renderPaymentDetail(event, data.entitlement || {}, rowId).trim();
        const nextRow = wrapper.firstElementChild;
        if (!nextRow) return;
        nextRow.hidden = false;
        detail.replaceWith(nextRow);
        nextRow.querySelector('.receipt-detail-close')?.addEventListener('click', (clickEvent) => {
            clickEvent.stopPropagation();
            togglePaymentDetail(rowId, false);
        });
    } catch (err) {
        console.warn('Could not load paid report detail', err);
        detail.innerHTML = `
            <td colspan="8">
                <div class="receipt-detail-card">
                    <div class="receipt-detail-empty">Could not load this paid report snapshot.</div>
                </div>
            </td>
        `;
    }
}

function getWalletEvents(account) {
    try {
        const normalized = String(account || '').toLowerCase();
        const key = `qma_wallet_events_${normalized}`;
        let raw = localStorage.getItem(key);
        if (!raw) {
            for (let i = 0; i < localStorage.length; i += 1) {
                const candidateKey = localStorage.key(i) || '';
                if (candidateKey.toLowerCase() === key) {
                    raw = localStorage.getItem(candidateKey);
                    break;
                }
            }
        }
        const events = raw ? JSON.parse(raw) : [];
        return Array.isArray(events) ? events : [];
    } catch {
        return [];
    }
}

function walletActionKey(event = {}) {
    return [
        event.type || 'event',
        event.settlement_id || event.tx_hash || event.txHash || event.transaction_hash || '',
        event.symbol || '',
        event.amount_usdc || '',
    ].join(':').toLowerCase();
}

function paymentEventsToWalletActions(payments = []) {
    return payments.flatMap((payment) => {
        const base = {
            amount_usdc: payment.amount_usdc,
            settlement_id: payment.settlement_id,
            tx_hash: payment.transaction_hash,
            explorer_url: payment.explorer_url,
            symbol: payment.symbol,
            at: Number(payment.paid_at || 0) > 10_000_000_000
                ? Number(payment.paid_at)
                : Number(payment.paid_at || 0) * 1000,
            source: 'database',
        };
        return [
            { ...base, type: 'verified_payment' },
            { ...base, type: 'x402_settlement' },
        ];
    });
}

function mergeWalletActions(localEvents = [], paymentEvents = []) {
    const merged = [];
    const seen = new Set();
    [...localEvents, ...paymentEventsToWalletActions(paymentEvents)].forEach((event) => {
        const key = walletActionKey(event);
        if (seen.has(key)) return;
        seen.add(key);
        merged.push(event);
    });
    return merged
        .sort((a, b) => Number(b.at || 0) - Number(a.at || 0))
        .slice(0, 50);
}

function renderEvents(account, paymentEvents = []) {
    const events = mergeWalletActions(getWalletEvents(account), paymentEvents);
    if (!events.length) {
        eventsBody.innerHTML = '<tr class="empty-row"><td colspan="4">No local wallet actions recorded.</td></tr>';
        return;
    }
    eventsBody.innerHTML = events.map((event) => {
        const txHash = event.tx_hash || event.txHash || event.transaction_hash;
        const ref = event.explorer_url && txHash
            ? `<a class="tx-link" href="${event.explorer_url}" target="_blank" rel="noreferrer">${shortAddress(txHash)}</a>`
            : event.settlement_id
                ? `<span class="mono-td" title="${escapeHtml(event.settlement_id)}">${shortAddress(event.settlement_id)}</span>`
                : '<span class="muted-ref">n/a</span>';
        return `
            <tr title="${escapeHtml(formatDateTime(event.at))}">
                <td><span class="action-label">${escapeHtml(event.type || 'event')}</span></td>
                <td>${escapeHtml(event.amount_usdc || 'n/a')}${event.amount_usdc ? ' USDC' : ''}</td>
                <td class="mono-td">${escapeHtml(event.symbol || 'n/a')}</td>
                <td>${ref}</td>
            </tr>
        `;
    }).join('');
}

function renderPayments(events, entitlements = []) {
    entitlements = normalizeEntitlementsList(entitlements);
    paymentRowsById = {};
    if (!events.length) {
        paymentsBody.innerHTML = '<tr class="empty-row"><td colspan="8">No verified payments yet.</td></tr>';
        return;
    }
    paymentsBody.innerHTML = events.map((event, index) => {
        const entitlement = findEntitlementForPayment(event, entitlements);
        const query = entitlement?.query || entitlement?.report?.query || event.query || {};
        const rowId = paymentRowId(event, index);
        paymentRowsById[rowId] = event;
        const entitlementIdValue = event.entitlement_id || (entitlement?.report ? entitlementId(entitlement) : '');
        const hasReport = Boolean(entitlement?.report || event.has_report || entitlementIdValue);
        const tier = tierLabel(event.tier_category || event.tier || entitlement?.tier);
        const provider = event.provider_id || entitlement?.provider_id || entitlement?.report?.provider_id || 'funding_memory';
        const buyerType = event.buyer_type || 'human';
        const isFinalStatus = ['completed', 'confirmed'].includes(String(event.gateway_status || '').toLowerCase());
        const missingTxLabel = isFinalStatus ? 'Arcscan unavailable' : 'Arcscan pending';
        const ref = event.explorer_url && event.transaction_hash
            ? `<a class="tx-link" href="${event.explorer_url}" target="_blank" rel="noreferrer">${shortAddress(event.transaction_hash)}</a>`
            : event.settlement_id
                ? `<span class="mono-td" title="${escapeHtml(event.settlement_id)}">${shortAddress(event.settlement_id)}</span><div class="badge ${isFinalStatus ? 'badge-muted' : 'badge-pending'} tx-pending-badge">${escapeHtml(missingTxLabel)}</div>`
                : '<span class="badge badge-muted">n/a</span>';
        return `
            <tr class="${hasReport ? 'user-payment-row is-clickable' : 'user-payment-row'}" data-row-id="${escapeHtml(rowId)}" data-entitlement-id="${escapeHtml(entitlementIdValue)}" title="${escapeHtml(formatDateTime(event.paid_at))}">
                <td class="signal-cell">
                    <strong>${escapeHtml(event.symbol || query.symbol || 'n/a')}</strong>
                </td>
                <td class="time-cell">${escapeHtml(formatDateTime(event.paid_at))}</td>
                <td>
                    <span class="report-tier-pill">${escapeHtml(tier)}</span>
                </td>
                <td>    
                    <div class="row-subtitle">${escapeHtml(provider)}</div>
                </td>
                <td>
                    <strong class="provider-name">${escapeHtml(buyerType)}</strong>
                </td>
                <td>
                    <strong class="payment-amount">${Number(event.amount_usdc || 0).toFixed(3)} USDC</strong>
                </td>
                <td>${gatewayStatusBadge(event.gateway_status)}</td>
                <td>
                    <div class="reference-cell">${ref}</div>
                    ${hasReport ? '' : '<div class="row-subtitle">No saved report</div>'}
                </td>
            </tr>
            ${entitlement?.report ? renderPaymentDetail(event, entitlement, rowId) : renderLazyPaymentDetail(rowId, hasReport)}
        `;
    }).join('');
    paymentsBody.querySelectorAll('.user-payment-row.is-clickable').forEach((row) => {
        row.addEventListener('click', (event) => {
            if (event.target.closest('a, button')) return;
            togglePaymentDetail(row.dataset.rowId, null, row.dataset.entitlementId);
        });
    });
    paymentsBody.querySelectorAll('.receipt-detail-close').forEach((button) => {
        button.addEventListener('click', (event) => {
            event.stopPropagation();
            togglePaymentDetail(button.dataset.rowId, false);
        });
    });
}

function togglePaymentDetail(rowId, forceOpen = null, entitlementId = '') {
    if (!rowId) return;
    const detail = document.getElementById(`receipt-detail-${rowId}`);
    const row = paymentsBody.querySelector(`.user-payment-row[data-row-id="${rowId}"]`);
    if (!detail || !row) return;
    const shouldOpen = forceOpen === null ? detail.hidden : forceOpen;
    paymentsBody.querySelectorAll('.payment-detail-row').forEach((item) => {
        item.hidden = true;
    });
    paymentsBody.querySelectorAll('.user-payment-row').forEach((item) => {
        item.classList.remove('is-expanded');
    });
    expandedPaymentId = shouldOpen ? rowId : '';
    if (shouldOpen) {
        detail.hidden = false;
        row.classList.add('is-expanded');
        loadPaymentDetail(rowId, entitlementId);
    }
}

async function loadHealth() {
    const resp = await fetch(apiUrl('/api/v1/config'));
    if (!resp.ok) return;
    const data = await resp.json();
    arcGatewayBaseUrl = data.arc_gateway || '';
}

async function loadWalletStatus(account) {
    if (!arcGatewayBaseUrl) return null;
    try {
        const resp = await fetch(gatewayApiUrl(`/api/wallet-status/${account}`));
        return resp.ok ? await resp.json() : null;
    } catch {
        return null;
    }
}

function updatePage(meta) {
    currentPage = Number(meta?.page || currentPage || 1);
    totalPages = Number(meta?.total_pages || 1);
    const total = Number(meta?.total || 0);
    if (meta?.legacy && totalPages > 1) {
        currentPage = 1;
        pageLabel.textContent = `Page 1 / ${totalPages} (${total}) - API redeploy needed`;
        pageLabel.title = 'The API response does not include pagination metadata yet. Restart local backend or redeploy Render from the latest commit.';
    } else {
        pageLabel.textContent = total ? `Page ${currentPage} / ${totalPages} (${total})` : 'Page 1 / 1';
        pageLabel.title = '';
    }
    prevBtn.disabled = currentPage <= 1;
    nextBtn.disabled = meta?.legacy || currentPage >= totalPages;
}

function fallbackPageMeta(meta, pageSize, totalFallback, visibleCount) {
    if (meta && Number.isFinite(Number(meta.total_pages))) {
        return meta;
    }
    const total = Number(totalFallback || visibleCount || 0);
    return {
        page: 1,
        page_size: pageSize,
        total,
        total_pages: Math.max(1, Math.ceil(total / pageSize)),
        has_next: false,
        has_prev: false,
        legacy: total > visibleCount,
    };
}

async function loadProfile(account, page = 1) {
    if (!account) return;
    currentWallet = account;
    connectBtn.textContent = shortAddress(account);
    connectBtn.title = account;
    renderEvents(account);

    const params = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE)
    });
    const [summaryResp, paymentsResp, walletStatus] = await Promise.all([
        fetch(apiUrl(`/api/v1/wallets/${account}/summary`)),
        fetch(apiUrl(`/api/v1/wallets/${account}/payments?${params.toString()}`)),
        loadWalletStatus(account)
    ]);
    if (!summaryResp.ok || !paymentsResp.ok) {
        paymentsBody.innerHTML = '<tr class="empty-row"><td colspan="8">Could not load wallet history.</td></tr>';
        return;
    }
    const summary = await summaryResp.json();
    const payments = await paymentsResp.json();
    renderEvents(account, payments.recent_payments || []);
    renderProfileSummary({
        ...summary,
        recent_payments: payments.recent_payments || [],
        recent_payments_page: payments.recent_payments_page,
        entitlements: [],
    }, walletStatus);
}

function renderProfileSummary(metrics, walletStatus) {
    const gatewayBalance = metrics?.gateway_balance?.available_usdc;
    const chainBalance = walletStatus?.usdc?.formatted ?? walletStatus?.usdcBalance?.formatted ?? null;
    chainBalanceEl.textContent = chainBalance ? `${Number(chainBalance).toFixed(6)} USDC` : 'n/a';
    gatewayBalanceEl.textContent = gatewayBalance == null ? 'n/a' : `${Number(gatewayBalance).toFixed(6)} USDC`;
    const tierCounts = metrics.tier_counts || {};
    const legacyCount = Number(tierCounts.legacy || 0);
    paymentCountEl.textContent = `${metrics.current_payments ?? metrics.payments ?? 0} (P:${tierCounts.preview || 0} F:${tierCounts.full || 0}${legacyCount ? ` L:${legacyCount}` : ''})`;
    spentEl.textContent = `${Number(metrics.spent_usdc || 0).toFixed(3)} USDC`;
    const symbols = metrics.purchased_symbols || [];
    tokenListEl.innerHTML = symbols.length
        ? symbols.map((symbol) => `<span class="token-chip">${escapeHtml(symbol)}</span>`).join('')
        : '<span class="token-chip token-chip-muted">No signals purchased yet</span>';
    const entitlements = normalizeEntitlementsList(metrics.entitlements || []);
    const payments = (metrics.recent_payments || []).length
        ? metrics.recent_payments
        : paymentsFromEntitlements(entitlements);
    renderPayments(payments, entitlements);
    updatePage(fallbackPageMeta(
        metrics.recent_payments_page,
        PAGE_SIZE,
        metrics.payments,
        (metrics.recent_payments || []).length
    ));
}

async function connectWallet() {
    if (!window.ethereum?.request) {
        alert('MetaMask is required to connect a wallet.');
        return;
    }
    const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' });
    const account = accounts && accounts[0] ? accounts[0] : '';
    if (account) {
        const url = new URL(window.location.href);
        url.searchParams.set('wallet', account);
        window.history.replaceState({}, '', url.toString());
        await loadProfile(account, 1);
    }
}

connectBtn.addEventListener('click', connectWallet);
prevBtn.addEventListener('click', () => {
    if (currentPage > 1) loadProfile(currentWallet, currentPage - 1);
});
nextBtn.addEventListener('click', () => {
    if (currentPage < totalPages) loadProfile(currentWallet, currentPage + 1);
});

(async function init() {
    await loadHealth();
    if (currentWallet) {
        await loadProfile(currentWallet, 1);
    }
})();
