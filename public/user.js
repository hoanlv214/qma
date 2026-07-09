const API_BASE_URL = String(window.QMA_API_BASE_URL || '').replace(/\/$/, '');
const PAGE_SIZE = 10;

let isPublicProfile = window.location.pathname.replace(/\/$/, '').startsWith('/user');
const initialWalletParam = new URLSearchParams(window.location.search).get('wallet') || '';
let currentWallet = initialWalletParam || localStorage.getItem('qma_connected_wallet') || '';
let currentPage = 1;
let totalPages = 1;
let arcGatewayBaseUrl = '';
let expandedPaymentId = '';
let paymentRowsById = {};
let walletProfileToken = '';

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
const accessCard = document.getElementById('profile-access-card');
const accessIcon = document.getElementById('profile-access-icon');
const accessTitle = document.getElementById('profile-access-title');
const accessDesc = document.getElementById('profile-access-desc');
const accessPill = document.getElementById('profile-access-pill');
const unlockBtn = document.getElementById('profile-unlock-btn');

function refreshRouteMode() {
    isPublicProfile = window.location.pathname.replace(/\/$/, '').startsWith('/user');
}

function getWalletQueryParam() {
    return new URLSearchParams(window.location.search).get('wallet') || '';
}

function sameAddress(a, b) {
    return Boolean(a && b && String(a).toLowerCase() === String(b).toLowerCase());
}

function connectedWalletCache() {
    return localStorage.getItem('qma_connected_wallet') || '';
}

function profileUrl(account = currentWallet) {
    return account ? `/user?wallet=${encodeURIComponent(account)}` : '/user';
}

function syncUserWalletRoute(account = currentWallet) {
    if (!account || !isPublicProfile) return;
    const nextUrl = profileUrl(account);
    const currentUrl = `${window.location.pathname}${window.location.search}`;
    if (currentUrl !== nextUrl) {
        window.history.replaceState({}, '', nextUrl);
    }
}

function createToastContainer() {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    return container;
}

function showToast(message, type = 'info') {
    const container = createToastContainer();
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <span class="toast-message">${escapeHtml(message)}</span>
        <button class="toast-close" type="button" aria-label="Close">&times;</button>
    `;
    container.appendChild(toast);
    const close = () => {
        toast.classList.add('fade-out');
        setTimeout(() => toast.remove(), 250);
    };
    toast.querySelector('.toast-close')?.addEventListener('click', close);
    setTimeout(() => {
        if (toast.parentNode) close();
    }, 5000);
}

window.alert = function (message) {
    const text = String(message || '');
    const lower = text.toLowerCase();
    const type = lower.includes('error') || lower.includes('failed') || lower.includes('invalid')
        ? 'error'
        : lower.includes('success') || lower.includes('connected') || lower.includes('unlocked')
            ? 'success'
            : lower.includes('warn') || lower.includes('expired')
                ? 'warning'
                : 'info';
    showToast(text, type);
};

function apiUrl(path) {
    return `${API_BASE_URL}${path}`;
}

function gatewayApiUrl(path) {
    if (!arcGatewayBaseUrl) return '';
    return `${arcGatewayBaseUrl.replace(/\/$/, '')}${path}`;
}

function walletTokenCacheKey(account) {
    return `qma_wallet_profile_token_${String(account || '').toLowerCase()}`;
}

function clearWalletProfileSession(account) {
    if (!account) return;
    sessionStorage.removeItem(walletTokenCacheKey(account));
    walletProfileToken = '';
}

function getCachedWalletProfileSession(account) {
    if (!account) return null;
    const raw = sessionStorage.getItem(walletTokenCacheKey(account));
    if (!raw) return null;
    try {
        const cached = JSON.parse(raw);
        if (cached?.token && Number(cached.expiresAt || 0) > Date.now() + 15_000) {
            walletProfileToken = cached.token;
            return cached;
        }
    } catch {
        // Older test builds stored raw tokens. Drop them to avoid expired-token reload bugs.
    }
    clearWalletProfileSession(account);
    return null;
}

function getCachedWalletProfileToken(account) {
    return getCachedWalletProfileSession(account)?.token || '';
}

function getOwnerWalletProfileToken(account) {
    if (!sameAddress(connectedWalletCache(), account)) return '';
    return getCachedWalletProfileToken(account);
}

function hasOwnerProfileSession(account = currentWallet) {
    return Boolean(getOwnerWalletProfileToken(account));
}

function formatTokenTtl(account) {
    const cached = getCachedWalletProfileSession(account);
    if (!cached?.expiresAt) return '';
    const ms = Number(cached.expiresAt) - Date.now();
    if (ms <= 0) return '';
    const minutes = Math.max(1, Math.round(ms / 60000));
    return minutes >= 60
        ? `expires in ${Math.floor(minutes / 60)}h ${minutes % 60}m`
        : `expires in ${minutes} min`;
}

function setAccessCardState(state, title, desc, pill, actionLabel = 'Unlock private') {
    if (!accessCard) return;
    accessCard.classList.toggle('is-public', state === 'public');
    accessCard.classList.toggle('is-locked', state === 'locked');
    accessCard.classList.toggle('is-unlocked', state === 'unlocked');
    if (accessIcon) {
        if (state === 'unlocked') {
            accessIcon.innerHTML = `<i class="ti ti-lock-open" style="font-size: 20px; color: #5dcaa5;" aria-hidden="true"></i>`;
        } else if (state === 'locked') {
            accessIcon.innerHTML = `<i class="ti ti-lock" style="font-size: 20px; color: #f59e0b;" aria-hidden="true"></i>`;
        } else {
            accessIcon.innerHTML = `<i class="ti ti-lock" style="font-size: 20px;" aria-hidden="true"></i>`;
        }
    }
    if (accessTitle) accessTitle.textContent = title;
    if (accessDesc) accessDesc.textContent = desc;
    if (accessPill) accessPill.textContent = pill;
    if (unlockBtn) unlockBtn.textContent = actionLabel;
}

function updateAccessUi(account = currentWallet) {
    const cachedToken = getOwnerWalletProfileToken(account);
    const ttl = cachedToken ? formatTokenTtl(account) : '';
    if (isPublicProfile) {
        if (cachedToken) {
            setAccessCardState(
                'unlocked',
                'Owner session available',
                `This browser already has a private profile session for ${shortAddress(account)}. Open the private profile without signing again${ttl ? ` - ${ttl}` : ''}.`,
                'ready',
                'Open private'
            );
        } else {
            setAccessCardState(
                'public',
                'Public profile view',
                'Purchases and settlements are visible. Connect the owner wallet once to unlock private balances and saved report snapshots.',
                'public',
                'Unlock private'
            );
        }
        return;
    }
    if (cachedToken) {
        setAccessCardState(
            'unlocked',
            'Private snapshots unlocked',
            `Signed once for this browser session${ttl ? ` - ${ttl}` : ''}. Quick profile and this page will reuse the same token.`,
            'active',
            'Unlocked'
        );
    } else if (account) {
        setAccessCardState(
            'locked',
            'Private snapshots locked',
            'Wallet history is visible, but saved report snapshots need one owner signature for this browser session.',
            'locked',
            'Unlock private'
        );
    } else {
        setAccessCardState(
            'locked',
            'Connect wallet to view private profile',
            'Connect once, then sign once. The token is stored in sessionStorage until it expires.',
            'connect',
            'Connect wallet'
        );
    }
}

async function getActiveWalletAccount(accountHint = '') {
    if (!window.ethereum?.request) return '';
    let accounts = await window.ethereum.request({ method: 'eth_accounts' }).catch(() => []);
    let active = accounts && accounts[0] ? String(accounts[0]) : '';
    if (!active || (accountHint && active.toLowerCase() !== String(accountHint).toLowerCase())) {
        accounts = await window.ethereum.request({ method: 'eth_requestAccounts' });
        active = accounts && accounts[0] ? String(accounts[0]) : '';
    }
    return active;
}

async function unlockWalletProfile(account, options = {}) {
    let finalAccount = account || currentWallet;
    if (!finalAccount) {
        finalAccount = await getActiveWalletAccount();
        if (!finalAccount) throw new Error('No wallet account returned.');
    }
    localStorage.setItem('qma_connected_wallet', finalAccount);
    currentWallet = finalAccount;
    const token = await requestWalletProfileSession(finalAccount);
    if (token && options.updateRoute !== false) {
        syncUserWalletRoute(finalAccount);
    }
    updateAccessUi(finalAccount);
    return token;
}

function walletProfileMessage(account, nonce, issuedAt) {
    return [
        'QMA Wallet Profile Access',
        `Wallet: ${String(account || '').toLowerCase()}`,
        `Nonce: ${nonce}`,
        `Issued At: ${issuedAt}`,
        'Purpose: unlock-paid-report-snapshots',
    ].join('\n');
}

async function requestWalletProfileSession(account) {
    if (!account) return '';
    const cached = getCachedWalletProfileToken(account);
    if (cached) return cached;
    if (!window.ethereum?.request) {
        throw new Error('Connect the wallet owner to unlock private report snapshots.');
    }
    const active = await getActiveWalletAccount(account);
    if (active.toLowerCase() !== String(account).toLowerCase()) {
        throw new Error('Connected wallet does not match this private profile.');
    }
    const issuedAt = Math.floor(Date.now() / 1000);
    const nonce = `${issuedAt}-${Math.random().toString(36).slice(2)}`;
    const message = walletProfileMessage(account, nonce, issuedAt);
    const signature = await window.ethereum.request({
        method: 'personal_sign',
        params: [message, active],
    });
    const resp = await fetch(apiUrl(`/api/v1/wallets/${account.toLowerCase()}/session`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nonce, issued_at: issuedAt, signature }),
    });
    if (!resp.ok) {
        const payload = await resp.json().catch(() => ({}));
        throw new Error(payload.detail || 'Could not unlock private profile.');
    }
    const data = await resp.json();
    const token = data.wallet_token || '';
    if (token) {
        sessionStorage.setItem(walletTokenCacheKey(account), JSON.stringify({
            token,
            expiresAt: Date.now() + Math.max(30, Number(data.expires_in || 3600)) * 1000,
        }));
        localStorage.setItem('qma_connected_wallet', account);
        walletProfileToken = token;
        showToast('Private profile access unlocked for this session.', 'success');
        updateAccessUi(account);
    }
    return token;
}

function walletPrivateHeaders(token) {
    return token ? { 'X-QMA-Wallet-Token': token } : {};
}

function setPrivacyNotice(message = '') {
    // No-op: dynamic privacy notices are disabled in favor of profile access card UI
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
    return entry.entitlement_id || '';
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
            <span class="receipt-kv-label">${escapeHtml(label)}</span>
            <strong class="receipt-kv-value" title="${escapeHtml(value)}">${escapeHtml(value)}</strong>
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
    if (!rowId || !currentWallet) return;
    const detail = document.getElementById(`receipt-detail-${rowId}`);
    const event = paymentRowsById[rowId] || {};
    if (!detail || !detail.classList.contains('needs-report-load')) return;
    try {
        let token = walletProfileToken || getCachedWalletProfileToken(currentWallet);
        if (!token) {
            setPrivacyNotice('Wallet owner signature is required to open private paid snapshots.');
            token = await requestWalletProfileSession(currentWallet);
        }
        const entitlement = await resolvePaymentEntitlement(event, entitlementId, token);
        const wrapper = document.createElement('tbody');
        wrapper.innerHTML = renderPaymentDetail(event, entitlement || {}, rowId).trim();
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
                    <div class="receipt-detail-empty">${escapeHtml(err.message || 'Could not load this paid report snapshot.')}</div>
                </div>
            </td>
        `;
    }
}

async function fetchWalletReportById(entitlementId, token) {
    if (!entitlementId) return null;
    const resp = await fetch(
        apiUrl(`/api/v1/wallets/${currentWallet}/reports/${encodeURIComponent(entitlementId)}`),
        { headers: walletPrivateHeaders(token) }
    );
    if (resp.status === 403) {
        clearWalletProfileSession(currentWallet);
        setPrivacyNotice('Private profile session expired. Unlock again to open paid snapshots.');
        throw new Error('Wallet owner session expired.');
    }
    if (resp.status === 404) return null;
    if (!resp.ok) throw new Error(`Report endpoint returned ${resp.status}`);
    const data = await resp.json();
    return data.entitlement || null;
}

async function fetchWalletEntitlements(token) {
    const resp = await fetch(apiUrl(`/api/v1/entitlements/wallet/${currentWallet}`), {
        headers: walletPrivateHeaders(token),
    });
    if (resp.status === 403) {
        clearWalletProfileSession(currentWallet);
        setPrivacyNotice('Private profile session expired. Unlock again to open paid snapshots.');
        throw new Error('Wallet owner session expired.');
    }
    if (!resp.ok) throw new Error(`Entitlements endpoint returned ${resp.status}`);
    const data = await resp.json();
    return normalizeEntitlementsList(data.entitlements || []);
}

async function resolvePaymentEntitlement(event, entitlementId, token) {
    const direct = await fetchWalletReportById(entitlementId, token);
    if (direct?.report) return direct;

    const entitlements = await fetchWalletEntitlements(token);
    const matched = findEntitlementForPayment(event, entitlements);
    if (matched?.report) return matched;

    const matchedId = matched?.entitlement_id || event?.entitlement_id || '';
    const fallback = await fetchWalletReportById(matchedId, token);
    if (fallback?.report) return fallback;

    throw new Error('No saved report snapshot was found for this receipt.');
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
    const grouped = groupPaymentsByInvoice(payments);
    return grouped.map((payment) => {
        // Emit exactly one wallet-action row per grouped invoice.
        // Using 'verified_split_payment' for split groups, 'verified_payment' otherwise,
        // so local saveWalletEvent entries naturally deduplicate against these.
        const isSplit = payment.is_group || String(payment.settlement_id || '').startsWith('split:');
        return {
            type: isSplit ? 'verified_split_payment' : 'verified_payment',
            amount_usdc: payment.amount_usdc,
            settlement_id: payment.settlement_id,
            tx_hash: payment.transaction_hash,
            explorer_url: payment.explorer_url,
            symbol: payment.symbol,
            gateway_status: payment.gateway_status,
            at: Number(payment.paid_at || 0) > 10_000_000_000
                ? Number(payment.paid_at)
                : Number(payment.paid_at || 0) * 1000,
            source: 'database',
        };
    });
}

// Types that represent individual split legs — they are shown inside the
// grouped row in renderPayments, not as standalone rows in the events feed.
const LEG_LEVEL_TYPES = new Set(['x402_split_leg']);

function mergeWalletActions(localEvents = [], paymentEvents = []) {
    const merged = [];
    const seen = new Set();
    // Filter out leg-level local events so they don't appear as extra rows
    // alongside the already-grouped verified_split_payment row.
    const filteredLocal = localEvents.filter((e) => !LEG_LEVEL_TYPES.has(e.type));
    [...filteredLocal, ...paymentEventsToWalletActions(paymentEvents)].forEach((event) => {
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

// Returns true when a payment event represents an actual split leg
// (created by the x402_direct_split flow). Legacy treasury_ledger events
// carry an invoice_id but are NOT split legs and must not be grouped.
function isSplitLegEvent(event) {
    if (!event) return false;
    // Explicit split leg type from local wallet storage
    if (event.type === 'x402_split_leg') return true;
    // Split leg events have a split_leg descriptor from the backend
    if (event.split_leg && typeof event.split_leg === 'object') return true;
    // Settlement_id that looks like a UUID (not 'split:…') means it came from
    // a single-leg legacy payment — not a real split leg.
    return false;
}

function groupPaymentsByInvoice(events) {
    const grouped = [];
    const invoiceMap = new Map();

    for (const event of events) {
        let invId = event.invoice_id;
        if (!invId && event.settlement_id && String(event.settlement_id).startsWith('split:')) {
            invId = String(event.settlement_id).split(':')[1];
        }

        // No invoice_id → not groupable; render as a standalone row.
        if (!invId) {
            grouped.push({ ...event, is_group: false });
            continue;
        }

        // Aggregate invoice marker (settlement_id = 'split:…') or a locally
        // saved verified_split_payment — these set the totals for the group.
        const isAggregateMarker = (
            event.type === 'verified_split_payment' ||
            (event.settlement_id && String(event.settlement_id).startsWith('split:'))
        );

        // If this event has an invoice_id but is NOT a real split leg and NOT
        // the aggregate marker, it is a legacy treasury_ledger payment that
        // happens to carry an invoice_id. Render it as a single standalone row.
        if (!isAggregateMarker && !isSplitLegEvent(event)) {
            grouped.push({ ...event, is_group: false });
            continue;
        }

        if (!invoiceMap.has(invId)) {
            const newGroup = {
                is_group: true,
                invoice_id: invId,
                legs: [],
                symbol: event.symbol,
                tier: event.tier || event.tier_category,
                provider_id: event.provider_id,
                buyer_type: event.buyer_type,
                gateway_status: event.gateway_status,
                paid_at: event.paid_at || event.at,
                amount_usdc: 0,
                has_report: event.has_report,
                entitlement_id: event.entitlement_id,
                transaction_hash: null,
                settlement_id: `split:${invId}`,
            };
            invoiceMap.set(invId, newGroup);
            grouped.push(newGroup);
        }

        const group = invoiceMap.get(invId);
        if (isAggregateMarker) {
            group.gateway_status = event.gateway_status || group.gateway_status;
            group.has_report = group.has_report || event.has_report;
            group.entitlement_id = group.entitlement_id || event.entitlement_id;
            group.total_override = Number(event.amount_usdc || 0);
            group.paid_at = event.paid_at || event.at || group.paid_at;
            group.type = event.type;
        } else {
            // Real split leg
            group.legs.push(event);
            group.amount_usdc += Number(event.amount_usdc || 0);
            group.has_report = group.has_report || event.has_report;
            group.entitlement_id = group.entitlement_id || event.entitlement_id;
            if (!group.gateway_status && event.gateway_status) {
                group.gateway_status = event.gateway_status;
            }
            if (!group.tier && event.tier) group.tier = event.tier;
        }
    }

    for (const group of grouped) {
        if (group.is_group && group.total_override) {
            group.amount_usdc = group.total_override;
        }
        // A group with no real legs and no total_override is an orphaned
        // aggregate marker that should render as a plain row.
        if (group.is_group && group.legs.length === 0 && !group.total_override) {
            group.is_group = false;
        }
        // Promote gateway_status from legs when all are confirmed.
        if (group.is_group && group.legs.length > 0) {
            const allCompleted = group.legs.every(leg => ['completed', 'confirmed'].includes(String(leg.gateway_status || '').toLowerCase()));
            if (allCompleted) {
                group.gateway_status = 'completed';
            }
        }
    }
    return grouped;
}

function renderPayments(events, entitlements = []) {
    events = groupPaymentsByInvoice(events);
    entitlements = normalizeEntitlementsList(entitlements);
    const ownerSession = hasOwnerProfileSession(currentWallet);
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
        const entitlementIdValue = ownerSession ? (event.entitlement_id || entitlement?.entitlement_id || '') : '';
        const hasReport = ownerSession && Boolean(entitlement?.report || event.has_report || entitlementIdValue);
        const tier = tierLabel(event.tier_category || event.tier || entitlement?.tier);
        const provider = event.provider_id || entitlement?.provider_id || entitlement?.report?.provider_id || 'funding_memory';
        const buyerType = event.buyer_type || 'human';
        const isFinalStatus = ['completed', 'confirmed'].includes(String(event.gateway_status || '').toLowerCase());
        // For the parent (invoice-level) row we show only the settlement-status
        // badge via gatewayStatusBadge() — 'Arcscan unavailable/pending' is only
        // meaningful at the per-leg child-row level where each leg has its own
        // independent Circle batch tx. Do NOT add Arcscan text here.
        const ref = event.explorer_url && event.transaction_hash
            ? `<a class="tx-link" href="${event.explorer_url}" target="_blank" rel="noreferrer">${shortAddress(event.transaction_hash)}</a>`
            : event.settlement_id
                ? `<span class="mono-td" title="${escapeHtml(event.settlement_id)}">${shortAddress(event.settlement_id)}</span>`
                : '<span class="badge badge-muted">n/a</span>';
        const hasLegs = event.is_group && event.legs && event.legs.length > 0;
        const expandBtn = hasLegs ? `<div style="margin-top:4px; font-size:0.75rem; color:var(--primary); cursor:pointer;" onclick="event.stopPropagation(); document.querySelectorAll('.legs-for-${escapeHtml(rowId)}').forEach(e => e.style.display = e.style.display === 'none' ? 'table-row' : 'none');">[expand ▾]</div>` : '';

        let legsHtml = '';
        if (hasLegs) {
            legsHtml = event.legs.map((leg) => {
                const legIsFinal = ['completed', 'confirmed'].includes(String(leg.gateway_status || '').toLowerCase());
                const legMissingTxLabel = legIsFinal ? 'Arcscan unavailable' : 'Arcscan pending';
                const legRef = leg.explorer_url && leg.transaction_hash
                    ? `<a class="tx-link" href="${leg.explorer_url}" target="_blank" rel="noreferrer">${shortAddress(leg.transaction_hash)}</a>`
                    : leg.settlement_id
                        ? `<span class="mono-td" title="${escapeHtml(leg.settlement_id)}">${shortAddress(leg.settlement_id)}</span><div class="badge ${legIsFinal ? 'badge-muted' : 'badge-pending'} tx-pending-badge">${escapeHtml(legMissingTxLabel)}</div>`
                        : '<span class="badge badge-muted">n/a</span>';
                // Derive role label from split_leg.role (creator/platform) — never fall back to bare 'leg'
                const roleStr = (leg.split_leg?.role || leg.role || '').trim() || 'creator';
                const payToStr = leg.split_leg?.pay_to || leg.pay_to || leg.seller_address || '';
                return `
                    <tr class="split-leg-row legs-for-${escapeHtml(rowId)}" style="display:none; background-color: rgba(255,255,255,0.02);">
                        <td colspan="5" style="padding-left: 2rem; border-top:none; border-bottom:none;">
                            <span style="color:var(--text-dark);">└─ ${escapeHtml(roleStr)} leg</span>
                            <span style="margin-left: 1rem; font-weight:600;">${Number(leg.amount_usdc || 0).toFixed(3)} USDC</span>
                            <span style="margin-left: 0.5rem; color:var(--text-dark);">→ ${payToStr ? shortAddress(payToStr) : '...'}</span>
                        </td>
                        <td style="border-top:none; border-bottom:none;"></td>
                        <td style="border-top:none; border-bottom:none;">${gatewayStatusBadge(leg.gateway_status)}</td>
                        <td style="border-top:none; border-bottom:none;">
                            <div class="reference-cell">${legRef}</div>
                        </td>
                    </tr>
                `;
            }).join('');
        }

        return `
            <tr class="${hasReport ? 'user-payment-row is-clickable' : 'user-payment-row'}" data-row-id="${escapeHtml(rowId)}" data-entitlement-id="${escapeHtml(entitlementIdValue)}" title="${escapeHtml(formatDateTime(event.paid_at))}">
                <td class="signal-cell">
                    <strong class="signal-symbol">${escapeHtml(event.symbol || query.symbol || 'n/a')}</strong>
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
                    ${expandBtn}
                </td>
                <td>${gatewayStatusBadge(event.gateway_status)}</td>
                <td>
                    <div class="reference-cell">${ref}</div>
                    ${hasReport ? '' : `<div class="row-subtitle">${ownerSession ? 'No saved report' : 'Owner only'}</div>`}
                </td>
            </tr>
            ${legsHtml}
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
    syncUserWalletRoute(account);
    const cachedToken = getOwnerWalletProfileToken(account);
    updateAccessUi(account);
    if (isPublicProfile) {
        connectBtn.textContent = cachedToken ? shortAddress(account) : 'Unlock Private';
        connectBtn.classList.remove('needs-unlock');
    } else {
        connectBtn.textContent = cachedToken ? shortAddress(account) : 'Unlock Profile';
        if (!cachedToken) {
            connectBtn.classList.add('needs-unlock');
        } else {
            connectBtn.classList.remove('needs-unlock');
        }
    }
    connectBtn.title = account;
    setPrivacyNotice(isPublicProfile
        ? cachedToken
            ? 'Owner token found in sessionStorage. Private paid snapshots can open without signing again.'
            : 'Public profile: purchases and settlements are visible, paid report snapshots are owner-only.'
        : cachedToken
            ? 'Private profile unlocked for this browser session.'
            : 'Private profile: connect wallet once to unlock your own paid report snapshots.'
    );
    renderEvents(cachedToken ? account : '');

    const params = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE)
    });
    const [summaryResp, firstPaymentsResp, walletStatus] = await Promise.all([
        fetch(apiUrl(`/api/v1/wallets/${account}/summary`)),
        fetch(apiUrl(`/api/v1/wallets/${account}/payments?${params.toString()}`), { headers: walletPrivateHeaders(cachedToken) }),
        loadWalletStatus(account)
    ]);
    let paymentsResp = firstPaymentsResp;
    if (paymentsResp.status === 403 && cachedToken) {
        clearWalletProfileSession(account);
        setPrivacyNotice('Private profile session expired. Showing public history until you unlock again.');
        showToast('Private profile session expired. Showing public history until you sign again.', 'warning');
        paymentsResp = await fetch(apiUrl(`/api/v1/wallets/${account}/payments?${params.toString()}`));
    }
    if (!summaryResp.ok || !paymentsResp.ok) {
        paymentsBody.innerHTML = '<tr class="empty-row"><td colspan="8">Could not load wallet history.</td></tr>';
        showToast('Could not load wallet history.', 'error');
        return;
    }
    const summary = await summaryResp.json();
    const payments = await paymentsResp.json();
    if (cachedToken) {
        renderEvents(account, payments.recent_payments || []);
    }
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
    if (currentWallet && getOwnerWalletProfileToken(currentWallet)) {
        syncUserWalletRoute(currentWallet);
        await loadProfile(currentWallet, 1);
        return;
    }
    if (!window.ethereum?.request) {
        alert('EVM is required to connect a wallet.');
        return;
    }
    const walletFromUrl = getWalletQueryParam();
    const targetWallet = walletFromUrl || currentWallet;
    const account = await getActiveWalletAccount(targetWallet);
    if (account) {
        const profileWallet = targetWallet || account;
        localStorage.setItem('qma_connected_wallet', account);
        currentWallet = profileWallet;
        try {
            await unlockWalletProfile(profileWallet, { updateRoute: true });
            setPrivacyNotice('Private profile unlocked for this browser session.');
        } catch (err) {
            setPrivacyNotice(err.message || 'Could not unlock private snapshots.');
            showToast(err.message || 'Connected. Private snapshots can be unlocked later in Profile.', 'warning');
        }
        await loadProfile(currentWallet, 1);
    }
}

connectBtn.addEventListener('click', connectWallet);
if (unlockBtn) unlockBtn.addEventListener('click', connectWallet);
prevBtn.addEventListener('click', () => {
    if (currentPage > 1) loadProfile(currentWallet, currentPage - 1);
});
nextBtn.addEventListener('click', () => {
    if (currentPage < totalPages) loadProfile(currentWallet, currentPage + 1);
});

(async function init() {
    await loadHealth();
    refreshRouteMode();
    currentWallet = getWalletQueryParam() || currentWallet;
    if (currentWallet) {
        await loadProfile(currentWallet, 1);
    } else if (isPublicProfile) {
        connectBtn.textContent = 'Unlock Private';
        paymentsBody.innerHTML = '<tr class="empty-row"><td colspan="8">No wallet address supplied.</td></tr>';
        eventsBody.innerHTML = '<tr class="empty-row"><td colspan="4">Public profile needs a wallet query.</td></tr>';
        setPrivacyNotice('Open /user?wallet=0x... for public history, or connect wallet for your private profile.');
        updateAccessUi('');
    } else {
        connectBtn.textContent = 'Connect Wallet';
        setPrivacyNotice('Connect wallet to view your private QMA profile.');
        updateAccessUi('');
    }
})();
