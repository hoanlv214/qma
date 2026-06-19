const API_BASE_URL = String(window.QMA_API_BASE_URL || '').replace(/\/$/, '');
const PAGE_SIZE = 10;

let currentWallet = new URLSearchParams(window.location.search).get('wallet') || '';
let currentPage = 1;
let totalPages = 1;
let arcGatewayBaseUrl = '';

const connectBtn = document.getElementById('profile-connect-btn');
const walletAddressEl = document.getElementById('profile-wallet-address');
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

function tierLabel(tier) {
    return String(tier || 'full').toLowerCase() === 'preview' ? 'Preview' : 'Full';
}

function gatewayStatusBadge(status) {
    if (!status) return '<span style="color:var(--t3);">n/a</span>';
    const s = String(status).toLowerCase();
    if (s === 'completed' || s === 'confirmed') {
        return `<span style="color:var(--green);font-weight:600;">confirmed</span>`;
    }
    if (s === 'received' || s === 'batched') {
        return `<span style="color:var(--amber);font-weight:600;">pending batch</span>`;
    }
    return `<span style="color:var(--t2);">${escapeHtml(status)}</span>`;
}

function getWalletEvents(account) {
    try {
        const key = `qma_wallet_events_${String(account || '').toLowerCase()}`;
        const raw = localStorage.getItem(key);
        const events = raw ? JSON.parse(raw) : [];
        return Array.isArray(events) ? events : [];
    } catch {
        return [];
    }
}

function renderEvents(account) {
    const events = getWalletEvents(account);
    if (!events.length) {
        eventsBody.innerHTML = '<tr><td colspan="4" style="color:var(--t3);">No local wallet actions.</td></tr>';
        return;
    }
    eventsBody.innerHTML = events.map((event) => {
        const ref = event.explorer_url && event.tx_hash
            ? `<a class="tx-link" href="${event.explorer_url}" target="_blank" rel="noreferrer">${shortAddress(event.tx_hash)}</a>`
            : '<span style="color:var(--t3);">n/a</span>';
        return `
            <tr title="${escapeHtml(formatDateTime(event.at))}">
                <td>${escapeHtml(event.type || 'event')}</td>
                <td>${escapeHtml(event.amount_usdc || 'n/a')}${event.amount_usdc ? ' USDC' : ''}</td>
                <td class="mono-td">${escapeHtml(event.symbol || 'n/a')}</td>
                <td>${ref}</td>
            </tr>
        `;
    }).join('');
}

function renderPayments(events) {
    if (!events.length) {
        paymentsBody.innerHTML = '<tr><td colspan="5" style="color:var(--t3);">No verified payments yet.</td></tr>';
        return;
    }
    paymentsBody.innerHTML = events.map((event) => {
        const ref = event.explorer_url && event.transaction_hash
            ? `<a class="tx-link" href="${event.explorer_url}" target="_blank" rel="noreferrer">${shortAddress(event.transaction_hash)}</a>`
            : event.settlement_id
                ? `<span class="mono-td" title="${escapeHtml(event.settlement_id)}">${shortAddress(event.settlement_id)}</span><div style="color:var(--amber);font-size:0.72rem;margin-top:2px;">Arcscan tx pending</div>`
                : '<span style="color:var(--t3);">n/a</span>';
        return `
            <tr title="${escapeHtml(formatDateTime(event.paid_at))}">
                <td class="mono-td">${escapeHtml(event.symbol || 'n/a')}<div style="color:var(--t3);font-size:0.66rem;margin-top:2px;">${escapeHtml(formatDateTime(event.paid_at))}</div></td>
                <td>${escapeHtml(tierLabel(event.tier))}</td>
                <td>${Number(event.amount_usdc || 0).toFixed(3)} USDC</td>
                <td>${gatewayStatusBadge(event.gateway_status)}</td>
                <td>${ref}</td>
            </tr>
        `;
    }).join('');
}

async function loadHealth() {
    const resp = await fetch(apiUrl('/api/v1/health'));
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
    walletAddressEl.textContent = account;
    connectBtn.textContent = shortAddress(account);
    renderEvents(account);

    const params = new URLSearchParams({
        payment_page: String(page),
        payment_page_size: String(PAGE_SIZE),
        entitlement_page_size: '100'
    });
    const [metricsResp, walletStatus] = await Promise.all([
        fetch(apiUrl(`/api/v1/metrics/wallet/${account}?${params.toString()}`)),
        loadWalletStatus(account)
    ]);
    if (!metricsResp.ok) {
        paymentsBody.innerHTML = '<tr><td colspan="5" style="color:var(--red);">Could not load wallet history.</td></tr>';
        return;
    }
    const metrics = await metricsResp.json();
    const gatewayBalance = metrics?.gateway_balance?.available_usdc;
    const chainBalance = walletStatus?.usdc?.formatted ?? walletStatus?.usdcBalance?.formatted ?? null;
    chainBalanceEl.textContent = chainBalance ? `${Number(chainBalance).toFixed(6)} USDC` : 'n/a';
    gatewayBalanceEl.textContent = gatewayBalance == null ? 'n/a' : `${Number(gatewayBalance).toFixed(6)} USDC`;
    const tierCounts = metrics.tier_counts || {};
    paymentCountEl.textContent = `${metrics.payments || 0} (P:${tierCounts.preview || 0} F:${tierCounts.full || 0})`;
    spentEl.textContent = `${Number(metrics.spent_usdc || 0).toFixed(3)} USDC`;
    const symbols = metrics.purchased_symbols || [];
    tokenListEl.innerHTML = symbols.length
        ? symbols.map((symbol) => `<span class="token-chip">${escapeHtml(symbol)}</span>`).join('')
        : '<span class="token-chip">None yet</span>';
    renderPayments(metrics.recent_payments || []);
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
