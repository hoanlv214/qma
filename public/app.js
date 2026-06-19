// Toast Notification System
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

    let icon = 'ℹ️';
    if (type === 'success') icon = '🟢';
    else if (type === 'error') icon = '🔴';
    else if (type === 'warning') icon = '🟡';

    toast.innerHTML = `
                <span class="toast-icon">${icon}</span>
                <span class="toast-message">${escapeHtml(message)}</span>
                <button class="toast-close" type="button">&times;</button>
            `;

    container.appendChild(toast);

    // Handle manual close
    toast.querySelector('.toast-close').addEventListener('click', () => {
        toast.classList.add('fade-out');
        setTimeout(() => toast.remove(), 300);
    });

    // Auto close after 5 seconds
    setTimeout(() => {
        if (toast.parentNode) {
            toast.classList.add('fade-out');
            setTimeout(() => toast.remove(), 300);
        }
    }, 5000);
}

// Global override for native window.alert to use toasts
window.alert = function (msg) {
    const msgLower = String(msg || '').toLowerCase();
    let type = 'info';
    if (msgLower.includes('error') || msgLower.includes('failed') || msgLower.includes('invalid') || msgLower.includes('no wallet') || msgLower.includes('reverted')) {
        type = 'error';
    } else if (msgLower.includes('confirmed') || msgLower.includes('success') || msgLower.includes('paid')) {
        type = 'success';
    } else if (msgLower.includes('cancel') || msgLower.includes('warn') || msgLower.includes('unknown')) {
        type = 'warning';
    }
    showToast(msg, type);
};

// Clock Handler
setInterval(() => {
    const clockEl = document.getElementById('clock');
    const now = new Date();
    clockEl.textContent = now.toLocaleTimeString();
}, 1000);

// Mock window.ethereum if query parameter mock_wallet is present
const urlParams = new URLSearchParams(window.location.search);
const mockWalletAddr = urlParams.get('mock_wallet');
if (mockWalletAddr) {
    console.log("Mocking window.ethereum with wallet address:", mockWalletAddr);
    window.ethereum = {
        request: async ({ method, params }) => {
            if (method === 'eth_accounts' || method === 'eth_requestAccounts') {
                return [mockWalletAddr];
            }
            if (method === 'eth_chainId') {
                return '0x4cef52';
            }
            if (method === 'eth_sendTransaction') {
                console.log("Mock tx send:", params);
                return '0x' + Array.from({ length: 32 }, () => Math.floor(Math.random() * 256).toString(16).padStart(2, '0')).join('');
            }
            if (method === 'eth_signTypedData_v4') {
                console.log("Mock signTypedData:", params);
                return '0x' + Array.from({ length: 65 }, () => Math.floor(Math.random() * 256).toString(16).padStart(2, '0')).join('');
            }
            if (method === 'eth_getTransactionReceipt') {
                return { status: '0x1' };
            }
            return null;
        },
        on: (event, callback) => { }
    };
    // Mock prompt to avoid blocking automated tests
    window.prompt = (msg, def) => { console.log("Mock prompt:", msg, def); return def; };
}

// State variables
let currentInvoiceId = null;
let currentInvoiceSecret = null;
let currentArcGatewayUrl = null;
let currentSettlementId = null;
let currentInvoiceAmount = 0.005;
let currentInvoiceTier = 'full';
let currentProviderId = 'funding_memory';
let pricingConfig = { preview: 0.001, full: 0.005 };
let providerCatalog = {};
let currentSellerAddress = null;
let currentAccessToken = null;
let activeQuery = null;
let hasUnlockedReport = false;
let connectedWallet = null;
let gatewayContractAddress = null;
let sellerWalletAddress = null;
let arcGatewayBaseUrl = '';
const WITHDRAW_FEE_RESERVE_USDC = 0.0035;
const API_BASE_URL = String(window.QMA_API_BASE_URL || '').replace(/\/$/, '');

function apiUrl(path) {
    return `${API_BASE_URL}${path}`;
}

function setArcGatewayBaseUrl(value) {
    arcGatewayBaseUrl = String(value || '').replace(/\/$/, '');
}

function gatewayApiUrl(path) {
    if (!arcGatewayBaseUrl) {
        throw new Error('Arc Gateway URL is not loaded yet. Refresh the page or wait for QMA health check to complete.');
    }
    return `${arcGatewayBaseUrl}${path}`;
}

// Fetch elements
const anomaliesContainer = document.getElementById('anomalies-container');
const queryForm = document.getElementById('query-form');
const paywallElement = document.getElementById('paywall-element');
const reportViewElement = document.getElementById('report-view-element');
const payButton = document.getElementById('pay-button');
const paywallClose = document.getElementById('paywall-close');
const paywallTitle = document.getElementById('paywall-title');
const paywallDesc = document.getElementById('paywall-desc');
const invoiceSignalDisplay = document.getElementById('invoice-signal-display');
const refreshBtn = document.getElementById('refresh-anomalies-btn');
const agentPicksContainer = document.getElementById('agent-picks-container');
const providerMarketplaceContainer = document.getElementById('provider-marketplace-container');
const dsProvider = document.getElementById('ds-provider');
const dsFeatureRows = document.getElementById('ds-feature-rows');
const dsCleanRows = document.getElementById('ds-clean-rows');
const dsSymbols = document.getElementById('ds-symbols');
const dsRange = document.getElementById('ds-range');

// Form Fields
const fSymbol = document.getElementById('q-symbol');
const fFunding = document.getElementById('q-funding');
const fMcap = document.getElementById('q-mcap');
const fFdv = document.getElementById('q-fdv');
const fCirc = document.getElementById('q-circ');
const fAth = document.getElementById('q-ath');
const fVol = document.getElementById('q-vol');
const metricsPayments = document.getElementById('metrics-payments');
const metricsRevenue = document.getElementById('metrics-revenue');
const metricsBalance = document.getElementById('metrics-balance');
const paymentActivityBody = document.getElementById('payment-activity-body');
const payerBreakdownBody = document.getElementById('payer-breakdown-body');
const walletButton = document.getElementById('wallet-button');
const walletButtonLabel = document.getElementById('wallet-button-label');
const walletMenu = document.getElementById('wallet-menu');
const walletMenuAddress = document.getElementById('wallet-menu-address');
const walletProfileBtn = document.getElementById('wallet-profile-btn');
const walletDisconnectBtn = document.getElementById('wallet-disconnect-btn');
const walletProfileModal = document.getElementById('wallet-profile-modal');
const walletProfileClose = document.getElementById('wallet-profile-close');
const walletProfileAddress = document.getElementById('wallet-profile-address');
const profileGatewayBalance = document.getElementById('profile-gateway-balance');
const profileChainBalance = document.getElementById('profile-chain-balance');
const profilePayments = document.getElementById('profile-payments');
const profileSpent = document.getElementById('profile-spent');
const profileTokenList = document.getElementById('profile-token-list');
const profilePaymentsBody = document.getElementById('profile-payments-body');
const profileEventsBody = document.getElementById('profile-events-body');
const actionModal = document.getElementById('action-modal');
const actionModalTitle = document.getElementById('action-modal-title');
const actionModalSubtitle = document.getElementById('action-modal-subtitle');
const actionModalBody = document.getElementById('action-modal-body');
const actionModalClose = document.getElementById('action-modal-close');
const actionModalCancel = document.getElementById('action-modal-cancel');
const actionModalConfirm = document.getElementById('action-modal-confirm');

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function formatCompact(num) {
    if (!Number.isFinite(num)) return 'n/a';
    return new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(num);
}

function formatDatasetDate(value) {
    const n = Number(value);
    if (!Number.isFinite(n) || n <= 0) return 'n/a';
    const ms = n > 10_000_000_000 ? n : n * 1000;
    return new Date(ms).toISOString().slice(0, 10);
}

function shortAddress(value) {
    if (!value) return 'n/a';
    return `${value.slice(0, 6)}...${value.slice(-4)}`;
}

function explorerTx(hash) {
    return `https://testnet.arcscan.app/tx/${hash}`;
}

function formatDateTime(timestamp) {
    if (!timestamp) return 'n/a';
    const ms = timestamp > 10_000_000_000 ? timestamp : timestamp * 1000;
    return new Date(ms).toLocaleString();
}

function getOnChainUsdcBalance(walletStatus) {
    return walletStatus?.usdc?.formatted ?? walletStatus?.usdcBalance?.formatted ?? null;
}

function renderActionRows(rows = []) {
    return rows.map((row) => `
        <div class="action-summary-row">
            <span class="action-summary-label">${escapeHtml(row.label)}</span>
            <span class="action-summary-value">${escapeHtml(row.value)}</span>
        </div>
    `).join('');
}

function requestActionConfirmation({ title, subtitle, rows = [], warning = null, confirmLabel = 'Continue', cancelLabel = 'Cancel' }) {
    return new Promise((resolve) => {
        actionModalTitle.textContent = title || 'Confirm Action';
        actionModalSubtitle.textContent = subtitle || 'Review before opening your wallet';
        actionModalBody.innerHTML = `
            ${renderActionRows(rows)}
            ${warning ? `<div class="action-warning">${escapeHtml(warning)}</div>` : ''}
        `;
        actionModalConfirm.textContent = confirmLabel;
        actionModalCancel.textContent = cancelLabel;
        actionModal.classList.add('open');
        actionModal.setAttribute('aria-hidden', 'false');

        const cleanup = (value) => {
            actionModal.classList.remove('open');
            actionModal.setAttribute('aria-hidden', 'true');
            actionModalConfirm.removeEventListener('click', onConfirm);
            actionModalCancel.removeEventListener('click', onCancel);
            actionModalClose.removeEventListener('click', onCancel);
            actionModal.removeEventListener('click', onBackdrop);
            resolve(value);
        };
        const onConfirm = () => cleanup(true);
        const onCancel = () => cleanup(false);
        const onBackdrop = (event) => {
            if (event.target === actionModal) cleanup(false);
        };

        actionModalConfirm.addEventListener('click', onConfirm);
        actionModalCancel.addEventListener('click', onCancel);
        actionModalClose.addEventListener('click', onCancel);
        actionModal.addEventListener('click', onBackdrop);
    });
}

const ARC_TESTNET_HEX = '0x4cef52';
const ARC_TESTNET = {
    chainId: ARC_TESTNET_HEX,
    chainName: 'Arc Testnet',
    nativeCurrency: { name: 'USDC', symbol: 'USDC', decimals: 18 },
    rpcUrls: ['https://rpc.testnet.arc.network'],
    blockExplorerUrls: ['https://testnet.arcscan.app']
};

async function ensureArcTestnet() {
    const current = await ethereum.request({ method: 'eth_chainId' });
    if (current === ARC_TESTNET_HEX) return;
    try {
        await ethereum.request({
            method: 'wallet_switchEthereumChain',
            params: [{ chainId: ARC_TESTNET_HEX }]
        });
    } catch (err) {
        if (err && err.code === 4902) {
            await ethereum.request({
                method: 'wallet_addEthereumChain',
                params: [ARC_TESTNET]
            });
            return;
        }
        throw err;
    }
}

function randomNonceHex() {
    const bytes = new Uint8Array(32);
    crypto.getRandomValues(bytes);
    return '0x' + Array.from(bytes).map((x) => x.toString(16).padStart(2, '0')).join('');
}

function b64encode(obj) {
    return btoa(unescape(encodeURIComponent(JSON.stringify(obj))));
}

function b64decode(value) {
    return decodeURIComponent(escape(atob(value)));
}

function sameAddress(a, b) {
    return String(a || '').toLowerCase() === String(b || '').toLowerCase();
}

function normalizeSignalPayload(source = {}) {
    const read = (key, fallback) => source[key] ?? source[fallback];
    const numberOrNull = (value) => {
        if (value === undefined || value === null || value === '') return null;
        const num = Number(value);
        return Number.isFinite(num) ? Number(num.toFixed(12)) : null;
    };
    return {
        symbol: String(source.symbol || '').trim().toUpperCase(),
        fundingRate: numberOrNull(read('fundingRate', 'funding_rate')),
        marketCap: numberOrNull(read('marketCap', 'market_cap')),
        FDV: numberOrNull(source.FDV ?? source.fdv),
        circRatio: numberOrNull(read('circRatio', 'circ_ratio')),
        fromATH: numberOrNull(source.fromATH ?? source.fromATHPercent ?? source['fromATH(%)']),
        volume24h: numberOrNull(read('volume24h', 'volume_24h')),
        amount: numberOrNull(source.amount),
    };
}

function signalFingerprint(source = {}) {
    const payload = normalizeSignalPayload(source);
    return b64encode(payload).replace(/[=+/]/g, '_').slice(0, 96);
}

function normalizeTier(tier = 'full') {
    return tier === 'preview' ? 'preview' : 'full';
}

function tierLabel(tier = 'full') {
    return normalizeTier(tier) === 'preview' ? 'Preview' : 'Full Report';
}

function tierPrice(tier = 'full') {
    return Number(pricingConfig[normalizeTier(tier)] || (normalizeTier(tier) === 'preview' ? 0.001 : 0.005));
}

function legacySignalCacheKey(source = {}) {
    const payload = normalizeSignalPayload(source);
    return `qma_paid_signal_v2_${payload.symbol}_${signalFingerprint(payload)}`;
}

function signalCacheKey(source = {}, tier = 'full', providerId = currentProviderId || 'funding_memory') {
    const payload = normalizeSignalPayload(source);
    return `qma_paid_signal_v4_${providerId}_${normalizeTier(tier)}_${payload.symbol}_${signalFingerprint(payload)}`;
}

function legacyTierSignalCacheKey(source = {}, tier = 'full') {
    const payload = normalizeSignalPayload(source);
    return `qma_paid_signal_v3_${normalizeTier(tier)}_${payload.symbol}_${signalFingerprint(payload)}`;
}

function signalSummary(source = {}) {
    const payload = normalizeSignalPayload(source);
    const funding = Number.isFinite(payload.fundingRate) ? `${(payload.fundingRate * 100).toFixed(3)}%` : 'n/a';
    const mcap = Number.isFinite(payload.marketCap) ? `$${formatCompact(payload.marketCap)}` : 'n/a';
    return `${payload.symbol || 'n/a'} · Funding ${funding} · MCap ${mcap}`;
}

function getCachedReport(source, tier = 'full') {
    try {
        const normalizedTier = normalizeTier(tier);
        const exact = localStorage.getItem(signalCacheKey(source, normalizedTier));
        if (exact) return JSON.parse(exact);
        const legacyTier = localStorage.getItem(legacyTierSignalCacheKey(source, normalizedTier));
        if (legacyTier) return JSON.parse(legacyTier);
        if (normalizedTier === 'preview') {
            const full = localStorage.getItem(signalCacheKey(source, 'full'));
            if (full) return JSON.parse(full);
            const legacyFull = localStorage.getItem(legacyTierSignalCacheKey(source, 'full'));
            if (legacyFull) return JSON.parse(legacyFull);
        }
        if (normalizedTier === 'full') {
            const legacy = localStorage.getItem(legacySignalCacheKey(source));
            if (legacy) return JSON.parse(legacy);
        }
        return null;
    } catch {
        return null;
    }
}

function getLegacyCachedReport(symbol) {
    const normalizedSymbol = String(symbol || '').trim().toUpperCase();
    if (!normalizedSymbol) return null;
    try {
        const cached = localStorage.getItem(`qma_paid_report_${normalizedSymbol}`);
        if (!cached) return null;
        const parsed = JSON.parse(cached);
        const report = parsed.report || parsed;
        if (!report) return null;
        const signal = normalizeSignalPayload(report.query || {
            symbol: report.query_symbol || normalizedSymbol
        });
        return {
            saved_at: parsed.saved_at || report.paid_at || Date.now(),
            signal: signal.symbol ? signal : normalizeSignalPayload({ symbol: normalizedSymbol }),
            report,
            legacy: true
        };
    } catch {
        return null;
    }
}

function getCachedReportsForSymbol(symbol) {
    const normalizedSymbol = String(symbol || '').trim().toUpperCase();
    if (!normalizedSymbol) return [];
    const reports = [];
    const seen = new Set();

    try {
        for (let i = 0; i < localStorage.length; i += 1) {
            const key = localStorage.key(i);
            if (!key || (
                !key.includes(`_${normalizedSymbol}_`) &&
                !key.startsWith(`qma_paid_signal_v3_preview_${normalizedSymbol}_`) &&
                !key.startsWith(`qma_paid_signal_v3_full_${normalizedSymbol}_`) &&
                !key.startsWith(`qma_paid_signal_v2_${normalizedSymbol}_`)
            )) continue;
            if (
                !key.startsWith('qma_paid_signal_v4_') &&
                !key.startsWith(`qma_paid_signal_v3_preview_${normalizedSymbol}_`) &&
                !key.startsWith(`qma_paid_signal_v3_full_${normalizedSymbol}_`) &&
                !key.startsWith(`qma_paid_signal_v2_${normalizedSymbol}_`)
            ) continue;
            const cached = JSON.parse(localStorage.getItem(key));
            if (!cached?.report) continue;
            const cacheId = cached.report.query_hash || cached.report.invoice?.settlement_id || key;
            if (seen.has(cacheId)) continue;
            seen.add(cacheId);
            reports.push({
                ...cached,
                signal: normalizeSignalPayload(cached.signal || cached.report.query || { symbol: normalizedSymbol })
            });
        }
    } catch (err) {
        console.warn('Could not scan cached reports', err);
    }

    const legacy = getLegacyCachedReport(normalizedSymbol);
    if (legacy) {
        const legacyId = legacy.report.query_hash || legacy.report.invoice?.settlement_id || `legacy-${normalizedSymbol}`;
        if (!seen.has(legacyId)) reports.push(legacy);
    }

    return reports.sort((a, b) => Number(b.saved_at || 0) - Number(a.saved_at || 0));
}

function saveCachedReport(report) {
    try {
        const query = report.query || activeQuery || { symbol: report.query_symbol };
        const tier = normalizeTier(report.tier || report.invoice?.tier || currentInvoiceTier || 'full');
        const providerId = report.provider_id || report.invoice?.provider_id || currentProviderId || 'funding_memory';
        localStorage.setItem(signalCacheKey(query, tier, providerId), JSON.stringify({
            saved_at: Date.now(),
            signal: normalizeSignalPayload(query),
            tier,
            provider_id: providerId,
            report
        }));
    } catch (err) {
        console.warn('Could not cache report', err);
    }
}

function saveWalletEvent(account, event) {
    try {
        const key = `qma_wallet_events_${String(account || '').toLowerCase()}`;
        const current = JSON.parse(localStorage.getItem(key) || '[]');
        current.unshift({ ...event, at: Date.now() });
        localStorage.setItem(key, JSON.stringify(current.slice(0, 50)));
    } catch (err) {
        console.warn('Could not save wallet event', err);
    }
}

function getWalletEvents(account) {
    try {
        const key = `qma_wallet_events_${String(account || '').toLowerCase()}`;
        return JSON.parse(localStorage.getItem(key) || '[]');
    } catch {
        return [];
    }
}

async function syncWalletEntitlements(account) {
    if (!account) return;
    try {
        const resp = await fetch(apiUrl(`/api/v1/entitlements/wallet/${account}`));
        if (!resp.ok) return;
        const data = await resp.json();
        (data.entitlements || []).forEach((entry) => {
            if (!entry.report) return;
            const report = {
                ...entry.report,
                tier: entry.tier || entry.report.tier || entry.report.invoice?.tier || 'full',
                provider_id: entry.provider_id || entry.report.provider_id || entry.report.invoice?.provider_id || 'funding_memory',
                query: entry.query || entry.report.query,
            };
            const previousTier = currentInvoiceTier;
            const previousProvider = currentProviderId;
            currentInvoiceTier = normalizeTier(report.tier);
            currentProviderId = report.provider_id || previousProvider;
            saveCachedReport(report);
            currentInvoiceTier = previousTier;
            currentProviderId = previousProvider;
        });
    } catch (err) {
        console.warn('Could not sync wallet entitlements', err);
    }
}

function setConnectedWallet(account) {
    connectedWallet = account || null;
    if (connectedWallet) {
        localStorage.setItem('qma_connected_wallet', connectedWallet);
    } else {
        localStorage.removeItem('qma_connected_wallet');
    }
    updateWalletUi();
}

function updateWalletUi() {
    const isConnected = Boolean(connectedWallet);
    walletButton.classList.toggle('connected', isConnected);
    walletButtonLabel.textContent = isConnected ? shortAddress(connectedWallet) : 'Connect Wallet';
    walletMenuAddress.textContent = isConnected ? connectedWallet : 'Not connected';
    walletProfileBtn.disabled = !isConnected;
    walletDisconnectBtn.disabled = !isConnected;

    // Copy button visibility
    const copyBtn = document.getElementById('wallet-copy-btn');
    if (copyBtn) {
        copyBtn.style.display = isConnected ? 'block' : 'none';
    }

    // Show withdraw button inside dropdown ONLY if connected as seller
    const isSeller = isConnected && sellerWalletAddress && sameAddress(connectedWallet, sellerWalletAddress);
    const withdrawMenuBtn = document.getElementById('wallet-withdraw-menu-btn');
    if (withdrawMenuBtn) {
        withdrawMenuBtn.style.display = isSeller ? 'block' : 'none';
    }
}

async function connectWallet(options = {}) {
    if (!window.ethereum) {
        if (!options.silent) alert('MetaMask is required to connect a wallet.');
        return null;
    }
    const method = options.silent ? 'eth_accounts' : 'eth_requestAccounts';
    const accounts = await ethereum.request({ method });
    const account = accounts && accounts[0] ? accounts[0] : null;
    if (account) {
        setConnectedWallet(account);
        syncWalletEntitlements(account);
    } else if (!options.silent) {
        alert('No wallet account returned by MetaMask.');
    }
    return account;
}

async function disconnectWallet() {
    try {
        if (window.ethereum?.request) {
            await ethereum.request({
                method: 'wallet_revokePermissions',
                params: [{ eth_accounts: {} }]
            });
        }
    } catch (err) {
        console.warn('Wallet permission revoke not available', err);
    }
    setConnectedWallet(null);
    walletMenu.classList.remove('open');
    walletProfileModal.classList.remove('open');
    walletProfileModal.setAttribute('aria-hidden', 'true');
}

async function restoreWalletSession() {
    const account = await connectWallet({ silent: true });
    if (!account) {
        setConnectedWallet(null);
    }
}

function extractGatewayBalanceUsdc(data) {
    const candidates = [
        data?.balance,
        data?.available,
        data?.amount,
        data?.balances?.[0]?.amount,
        data?.balances?.[0]?.balance,
        data?.sources?.[0]?.amount,
        data?.sources?.[0]?.balance,
        data?.data?.balances?.[0]?.amount
    ];
    for (const candidate of candidates) {
        if (candidate === undefined || candidate === null) continue;
        const raw = Number(candidate);
        if (!Number.isFinite(raw)) continue;
        return raw > 1000 ? raw / 1_000_000 : raw;
    }
    return null;
}

async function checkGatewayBalance(account) {
    try {
        const resp = await fetch(gatewayApiUrl(`/api/balance/${account}`));
        const data = await resp.json();
        if (!resp.ok) {
            console.warn('Gateway balance lookup failed', data);
            return null;
        }
        return extractGatewayBalanceUsdc(data);
    } catch (err) {
        console.warn('Gateway balance lookup unavailable', err);
        return null;
    }
}

async function getWalletStatus(account) {
    try {
        const resp = await fetch(gatewayApiUrl(`/api/wallet-status/${account}`));
        const data = await resp.json();
        if (!resp.ok) {
            console.warn('Wallet status lookup failed', data);
            return null;
        }
        return data;
    } catch (err) {
        console.warn('Wallet status lookup unavailable', err);
        return null;
    }
}

async function waitForReceipt(txHash) {
    for (let i = 0; i < 60; i++) {
        const receipt = await ethereum.request({
            method: 'eth_getTransactionReceipt',
            params: [txHash]
        });
        if (receipt) {
            if (receipt.status !== '0x1') {
                throw new Error(`Transaction failed: ${txHash}`);
            }
            return receipt;
        }
        await new Promise(resolve => setTimeout(resolve, 2000));
    }
    throw new Error(`Timed out waiting for transaction: ${txHash}`);
}

async function depositToGateway(account, amount, walletStatus = null) {
    const approveAmount = Math.max(10, amount).toFixed(6);
    const url = gatewayApiUrl(`/api/deposit-calldata/${account}?amount=${amount.toFixed(6)}&approveAmount=${approveAmount}`);
    const resp = await fetch(url);
    const data = await resp.json();
    if (!resp.ok) {
        throw new Error(data.error || 'Could not build Gateway deposit transactions.');
    }

    let approvalHash = null;
    const allowance = Number(walletStatus?.allowance?.formatted || 0);
    if (allowance + 1e-9 < amount) {
        showToast('Approve USDC allowance in your wallet. This does not spend funds yet.', 'info');
        payButton.innerHTML = `
                    <div class="spinner" style="width: 16px; height: 16px;"></div>
                    <span>Approve USDC allowance...</span>
                `;
        approvalHash = await ethereum.request({
            method: 'eth_sendTransaction',
            params: [data.approveTx]
        });
        await waitForReceipt(approvalHash);
        saveWalletEvent(account, {
            type: 'approve',
            amount_usdc: approveAmount,
            tx_hash: approvalHash,
            explorer_url: explorerTx(approvalHash)
        });
        showToast('USDC allowance approved. Next, confirm the Gateway deposit transaction.', 'success');
    }

    showToast('Confirm the Gateway deposit in your wallet. This moves USDC into Circle Gateway balance.', 'info');
    payButton.innerHTML = `
                <div class="spinner" style="width: 16px; height: 16px;"></div>
                <span>Deposit to Gateway...</span>
            `;
    const depositHash = await ethereum.request({
        method: 'eth_sendTransaction',
        params: [data.depositTx]
    });
    await waitForReceipt(depositHash);
    saveWalletEvent(account, {
        type: 'deposit',
        amount_usdc: amount.toFixed(6),
        tx_hash: depositHash,
        explorer_url: explorerTx(depositHash)
    });
    showToast('Gateway deposit transaction confirmed. Waiting for Circle balance update.', 'success');
    return { approvalHash, depositHash };
}

async function waitForGatewayBalance(account, requiredAmount) {
    let latest = null;
    for (let i = 0; i < 45; i++) {
        latest = await checkGatewayBalance(account);
        if (latest !== null && latest + 1e-9 >= requiredAmount) {
            return latest;
        }
        await new Promise(resolve => setTimeout(resolve, 2000));
    }
    return latest;
}

function renderProfileEvents(events) {
    if (!events.length) {
        profileEventsBody.innerHTML = '<tr><td colspan="4" style="color: var(--text-dark);">No local wallet actions.</td></tr>';
        return;
    }
    profileEventsBody.innerHTML = events.map((event) => {
        const ref = event.explorer_url && event.tx_hash
            ? `<a class="tx-link" href="${event.explorer_url}" target="_blank" rel="noreferrer">${shortAddress(event.tx_hash)}</a>`
            : event.settlement_id
                ? `<span class="mono-td" title="${escapeHtml(event.settlement_id)}">${shortAddress(event.settlement_id)}</span>`
                : '<span style="color: var(--text-dark);">n/a</span>';
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

function renderProfilePayments(events) {
    if (!events.length) {
        profilePaymentsBody.innerHTML = '<tr><td colspan="4" style="color: var(--text-dark);">No verified payments.</td></tr>';
        return;
    }
    profilePaymentsBody.innerHTML = events.map((event) => {
        const ref = event.explorer_url && event.transaction_hash
            ? `<a class="tx-link" href="${event.explorer_url}" target="_blank" rel="noreferrer" title="Settlement: ${escapeHtml(event.settlement_id || '')}">${shortAddress(event.transaction_hash)}</a>`
            : event.settlement_id
                ? `<span class="mono-td" title="Settlement ID: ${escapeHtml(event.settlement_id)}">${shortAddress(event.settlement_id)}</span><div style="color:#f59e0b; font-size:0.72rem; margin-top:2px;">⏳ Arcscan tx pending</div>`
                : '<span style="color: var(--text-dark);">n/a</span>';
        return `
                    <tr title="${escapeHtml(formatDateTime(event.paid_at))}">
                        <td class="mono-td">${escapeHtml(event.symbol || 'n/a')}<div style="color:var(--green); font-size:0.62rem; margin-top:2px;">${escapeHtml(event.provider_id || 'funding_memory')}</div><div style="color:var(--t3); font-size:0.66rem; margin-top:2px;">${escapeHtml(formatDateTime(event.paid_at))}</div></td>
                        <td>${Number(event.amount_usdc || 0).toFixed(3)} USDC<div style="color:var(--t3); font-size:0.66rem;">${escapeHtml(tierLabel(event.tier || 'full'))} / ${escapeHtml(event.buyer_type || 'human')}</div></td>
                        <td>${gatewayStatusBadge(event.gateway_status)}</td>
                        <td>${ref}</td>
                    </tr>
                `;
    }).join('');
}

async function openWalletProfile() {
    const account = connectedWallet || await connectWallet();
    if (!account) return;
    walletMenu.classList.remove('open');
    walletProfileModal.classList.add('open');
    walletProfileModal.setAttribute('aria-hidden', 'false');
    walletProfileAddress.textContent = account;
    profileGatewayBalance.textContent = 'loading...';
    profileChainBalance.textContent = 'loading...';
    profilePayments.textContent = 'loading...';
    profileSpent.textContent = 'loading...';
    profileTokenList.innerHTML = '<span class="token-chip">Loading</span>';
    profilePaymentsBody.innerHTML = '<tr><td colspan="4" style="color: var(--text-dark);">Loading payments...</td></tr>';
    renderProfileEvents(getWalletEvents(account));

    try {
        const [metricsResp, walletStatus] = await Promise.all([
            fetch(apiUrl(`/api/v1/metrics/wallet/${account}`)),
            getWalletStatus(account)
        ]);
        const metrics = metricsResp.ok ? await metricsResp.json() : null;
        const gatewayBalance = metrics?.gateway_balance?.available_usdc;
        profileGatewayBalance.textContent = gatewayBalance === null || gatewayBalance === undefined
            ? 'n/a'
            : `${Number(gatewayBalance).toFixed(6)} USDC`;
        const chainBalance = getOnChainUsdcBalance(walletStatus);
        profileChainBalance.textContent = chainBalance
            ? `${Number(chainBalance).toFixed(6)} USDC`
            : 'n/a';
        const tierCounts = metrics?.tier_counts || {};
        profilePayments.textContent = `${metrics?.payments || 0} (P:${tierCounts.preview || 0} F:${tierCounts.full || 0})`;
        profileSpent.textContent = `${Number(metrics?.spent_usdc || 0).toFixed(3)} USDC`;

        const symbols = metrics?.purchased_symbols || [];
        profileTokenList.innerHTML = symbols.length
            ? symbols.map(symbol => `<span class="token-chip">${escapeHtml(symbol)}</span>`).join('')
            : '<span class="token-chip">None yet</span>';
        renderProfilePayments(metrics?.recent_payments || []);
    } catch (err) {
        console.warn('Wallet profile unavailable', err);
        profileGatewayBalance.textContent = 'n/a';
        profileChainBalance.textContent = 'n/a';
        profilePayments.textContent = '0';
        profileSpent.textContent = '0.00 USDC';
        profileTokenList.innerHTML = '<span class="token-chip">Unavailable</span>';
        profilePaymentsBody.innerHTML = '<tr><td colspan="4" style="color: var(--color-danger);">Could not load wallet profile.</td></tr>';
    }
}

// Load Live Feed
async function loadLiveAnomalies() {
    try {
        anomaliesContainer.innerHTML = `
                    <div style="text-align: center; color: var(--text-dark); margin-top: 40px;">
                        <div class="spinner" style="margin: 0 auto 12px;"></div>
                        Scanning live exchanges...
                    </div>
                `;
        const resp = await fetch(apiUrl('/api/v1/live-anomalies'));
        const data = await resp.json();

        if (data.anomalies && data.anomalies.length > 0) {
            anomaliesContainer.innerHTML = '';
            data.anomalies.forEach((item, index) => {
                const card = document.createElement('div');
                card.className = `anomaly-card ${index === 0 ? 'active' : ''}`;

                const fundingPercent = (item.fundingRate * 100).toFixed(3);
                const mcapMillions = (item.marketCap / 1000000).toFixed(1);
                const volMillions = (item.volume24h / 1000000).toFixed(1);
                const signal = formSignalFromAnomaly(item);
                const cachedEntry = getCachedReport(signal);
                const isPaid = Boolean(cachedEntry?.report);
                const historyEntries = isPaid ? [] : getCachedReportsForSymbol(signal.symbol);
                const hasHistory = historyEntries.length > 0;
                const cardSeenAt = cachedEntry?.saved_at
                    ? formatDateTime(cachedEntry.saved_at)
                    : hasHistory
                        ? `Last paid ${formatDateTime(historyEntries[0].saved_at)}`
                        : `Live ${formatDateTime(data.last_updated)}`;
                const badgeClass = isPaid ? 'paid' : hasHistory ? 'history' : 'unpaid';
                const badgeText = isPaid ? 'Paid snapshot' : hasHistory ? 'Paid history' : 'Pay to unlock';

                card.innerHTML = `
                            <div class="card-header">
                                <span class="card-symbol">${item.symbol}</span>
                                <span class="card-funding">${fundingPercent}%</span>
                            </div>
                            <div class="card-stats">
                                <div>Mkt Cap: <span class="card-stat-val">$${mcapMillions}M</span></div>
                                <div>Circ Ratio: <span class="card-stat-val">${item.circRatio.toFixed(2)}</span></div>
                                <div>24h Vol: <span class="card-stat-val">$${volMillions}M</span></div>
                                <div>ATH Dist: <span class="card-stat-val">${item.fromATH.toFixed(2)}%</span></div>
                            </div>
                            <div class="card-meta-row">
                                <span>${escapeHtml(cardSeenAt)}</span>
                                <span class="signal-badge ${badgeClass}">${badgeText}</span>
                            </div>
                        `;

                card.addEventListener('click', () => {
                    // Clear active classes
                    document.querySelectorAll('.anomaly-card').forEach(c => c.classList.remove('active'));
                    card.classList.add('active');
                    loadCardIntoForm(item);
                });
                anomaliesContainer.appendChild(card);
                if (index === 0) {
                    loadCardIntoForm(item);
                }
            });
        } else {
            anomaliesContainer.innerHTML = '<div style="text-align: center; color: var(--text-dark); margin-top: 40px;">No funding anomalies found (funding <= -0.25%).</div>';
        }
    } catch (err) {
        console.error(err);
        anomaliesContainer.innerHTML = '<div style="text-align: center; color: var(--color-danger); margin-top: 40px;">Error scanning MEXC. Try again.</div>';
    }
}

async function loadAgentRecommendations() {
    if (!agentPicksContainer) return;
    agentPicksContainer.innerHTML = '<div class="agent-empty">Ranking live signals...</div>';
    try {
        const resp = await fetch(apiUrl('/api/v1/agent/recommendations'));
        if (!resp.ok) throw new Error(`Agent endpoint returned ${resp.status}`);
        const data = await resp.json();
        const picks = data.recommendations || [];
        if (!picks.length) {
            agentPicksContainer.innerHTML = '<div class="agent-empty">No paid opportunities ranked yet.</div>';
            return;
        }
        agentPicksContainer.innerHTML = picks.slice(0, 5).map((pick) => `
            <div class="agent-pick-card" data-symbol="${escapeHtml(pick.symbol)}" data-tier="${escapeHtml(pick.suggested_tier)}">
                <div class="agent-pick-top">
                    <span class="agent-pick-symbol">${escapeHtml(pick.symbol || 'n/a')}</span>
                    <span class="agent-pick-score">${Number(pick.score || 0).toFixed(1)}</span>
                </div>
                <div class="agent-pick-meta">
                    <span class="agent-tier-pill">${escapeHtml(tierLabel(pick.suggested_tier))} ${Number(pick.suggested_price_usdc || tierPrice(pick.suggested_tier)).toFixed(3)}</span>
                    <span style="color:var(--t3); font-size:0.64rem;">${escapeHtml(pick.estimated_value || 'Exploratory')}</span>
                </div>
                <div class="agent-pick-reasons">${escapeHtml((pick.reasons || []).join(' | '))}</div>
            </div>
        `).join('');

        agentPicksContainer.querySelectorAll('.agent-pick-card').forEach((card, index) => {
            card.addEventListener('click', () => {
                const pick = picks[index];
                if (!pick?.query) return;
                applySignalToForm(pick.query);
                activeQuery = normalizeSignalPayload(pick.query);
                currentProviderId = pick.provider_id || 'funding_memory';
                currentInvoiceTier = normalizeTier(pick.suggested_tier);
                currentInvoiceAmount = tierPrice(currentInvoiceTier);
                const submitBtn = document.querySelector(`[data-tier="${currentInvoiceTier}"]`) || document.querySelector('[data-tier="full"]');
                showToast(`Agent selected ${pick.symbol}: ${pick.reasons?.[0] || 'ranked opportunity'}. Creating ${tierLabel(currentInvoiceTier)} invoice.`, 'info');
                queryForm.requestSubmit(submitBtn);
            });
        });
    } catch (err) {
        console.warn('Agent recommendations unavailable', err);
        agentPicksContainer.innerHTML = '<div class="agent-empty">Agent ranking unavailable.</div>';
    }
}

async function loadProviders() {
    if (!providerMarketplaceContainer) return;
    providerMarketplaceContainer.innerHTML = '<div class="agent-empty">Loading providers...</div>';
    try {
        const resp = await fetch(apiUrl('/api/v1/providers'));
        if (!resp.ok) throw new Error(`Providers endpoint returned ${resp.status}`);
        const data = await resp.json();
        const providers = data.providers || [];
        providerCatalog = {};
        providers.forEach((provider) => {
            providerCatalog[provider.provider_id] = provider;
        });
        if (!providers.length) {
            providerMarketplaceContainer.innerHTML = '<div class="agent-empty">No providers registered.</div>';
            return;
        }
        providerMarketplaceContainer.innerHTML = providers.map((provider) => {
            const preview = provider.pricing?.preview?.amount_usdc ?? pricingConfig.preview;
            const full = provider.pricing?.full?.amount_usdc ?? pricingConfig.full;
            return `
                <button type="button" class="provider-card ${provider.provider_id === currentProviderId ? 'active' : ''}" data-provider-id="${escapeHtml(provider.provider_id)}">
                    <div class="provider-card-top">
                        <span class="provider-name">${escapeHtml(provider.provider_name || provider.provider_id)}</span>
                        <span class="provider-id">${escapeHtml(provider.provider_id)}</span>
                    </div>
                    <div class="provider-desc">${escapeHtml(provider.description || '')}</div>
                    <div class="provider-meta">
                        <span>Preview ${Number(preview).toFixed(3)}</span>
                        <span>Full ${Number(full).toFixed(3)}</span>
                    </div>
                    <div class="provider-owner" title="${escapeHtml(provider.owner_wallet || '')}">Owner ${shortAddress(provider.owner_wallet)}</div>
                </button>
            `;
        }).join('');
        providerMarketplaceContainer.querySelectorAll('.provider-card').forEach((card) => {
            card.addEventListener('click', () => {
                currentProviderId = card.dataset.providerId || 'funding_memory';
                providerMarketplaceContainer.querySelectorAll('.provider-card').forEach((el) => el.classList.remove('active'));
                card.classList.add('active');
                showToast(`Provider selected: ${providerCatalog[currentProviderId]?.provider_name || currentProviderId}`, 'info');
            });
        });
    } catch (err) {
        console.warn('Provider marketplace unavailable', err);
        providerMarketplaceContainer.innerHTML = '<div class="agent-empty">Provider marketplace unavailable.</div>';
    }
}

const metricsPendingEl = document.getElementById('metrics-balance-pending');

async function loadMetrics() {
    try {
        const resp = await fetch(apiUrl('/api/v1/metrics'));
        if (!resp.ok) return;
        const data = await resp.json();
        const tierCounts = data.tier_counts || {};
        metricsPayments.textContent = `Paid: ${data.paid_count} (P:${tierCounts.preview || 0} F:${tierCounts.full || 0})`;
        metricsRevenue.textContent = `Revenue: ${Number(data.revenue_usdc || 0).toFixed(3)} USDC`;

        const sellerBal = data.seller_gateway_balance;
        const available = sellerBal?.available_usdc;
        const pendingBatch = sellerBal?.pending_batch_usdc;

        metricsBalance.textContent = available === null || available === undefined
            ? 'Seller Available: n/a'
            : `Seller Available: ${Number(available).toFixed(2)} USDC`;
        metricsBalance.title = `Seller Treasury Wallet: ${data.seller_address || 'n/a'}`;

        if (metricsPendingEl) {
            metricsPendingEl.textContent = pendingBatch != null && pendingBatch > 0
                ? `Pending Batch: ${Number(pendingBatch).toFixed(2)} USDC`
                : 'Pending Batch: —';
        }

        // Update seller balance summary cards in report section
        const sbAvail = document.getElementById('sb-available');
        const sbPend = document.getElementById('sb-pending');
        const sbWallet = document.getElementById('sb-wallet-addr');
        if (sbAvail) sbAvail.textContent = available != null ? `${Number(available).toFixed(6)} USDC` : '—';
        if (sbPend) sbPend.textContent = pendingBatch != null ? `${Number(pendingBatch).toFixed(6)} USDC` : '—';
        if (sbWallet) sbWallet.textContent = data.seller_address || '—';

        renderPaymentActivity(data.recent_payments || []);
        renderPayerBreakdown(data.payer_breakdown || []);
    } catch (err) {
        console.warn('Metrics unavailable', err);
    }
}

async function loadHealthInfo() {
    try {
        const resp = await fetch(apiUrl('/api/v1/health'));
        if (resp.ok) {
            const data = await resp.json();
            setArcGatewayBaseUrl(data.arc_gateway);
            gatewayContractAddress = data.circle_deposit_contract;
            sellerWalletAddress = data.seller_wallet;
            const dataset = data.dataset || {};
            const provider = (data.providers || [])[0] || providerCatalog[currentProviderId];
            if (dsProvider) dsProvider.textContent = provider?.provider_id || currentProviderId || 'funding_memory';
            if (dsFeatureRows) dsFeatureRows.textContent = Number(dataset.historical_feature_rows || 0).toLocaleString();
            if (dsCleanRows) dsCleanRows.textContent = Number(dataset.clean_joined_rows || 0).toLocaleString();
            if (dsSymbols) dsSymbols.textContent = Number(dataset.unique_symbols || 0).toLocaleString();
            if (dsRange) {
                dsRange.textContent = `${formatDatasetDate(dataset.time_min)} to ${formatDatasetDate(dataset.time_max)}`;
                dsRange.title = 'Historical anomaly event range in the loaded backend dataset';
            }
            if (data.pricing) {
                pricingConfig = {
                    preview: Number(data.pricing.preview_usdc || pricingConfig.preview),
                    full: Number(data.pricing.full_usdc || pricingConfig.full),
                };
                document.querySelectorAll('[data-tier="preview"] span').forEach(el => {
                    el.textContent = `Preview ${pricingConfig.preview.toFixed(3)}`;
                });
                document.querySelectorAll('[data-tier="full"] span').forEach(el => {
                    el.textContent = `Full ${pricingConfig.full.toFixed(3)}`;
                });
            }
            if (gatewayContractAddress) {
                const gwEl = document.getElementById('pf-gateway-contract');
                if (gwEl) {
                    gwEl.textContent = gatewayContractAddress;
                    gwEl.title = gatewayContractAddress;
                }
            }
            updateWalletUi();
        }
    } catch (err) {
        console.warn('Could not load health info', err);
    }
}

function encodeGatewayMintCalldata(attestationHex, signatureHex) {
    const att = attestationHex.replace(/^0x/, '').toLowerCase();
    const sig = signatureHex.replace(/^0x/, '').toLowerCase();
    const attLen = att.length / 2;
    const sigLen = sig.length / 2;
    const offset1 = 64;
    const attPaddedLen = Math.ceil(attLen / 32) * 32;
    const offset2 = 64 + 32 + attPaddedLen;
    const toWord = (val) => val.toString(16).padStart(64, '0');
    const padTo32 = (hex) => hex.padEnd(Math.ceil(hex.length / 64) * 64, '0');
    return '0x9fb01cc5' + toWord(offset1) + toWord(offset2) + toWord(attLen) + padTo32(att) + toWord(sigLen) + padTo32(sig);
}

function requestWithdrawAmount(availableUsdc) {
    return new Promise((resolve) => {
        const modal = document.getElementById('withdraw-modal');
        const closeBtn = document.getElementById('withdraw-modal-close');
        const cancelBtn = document.getElementById('withdraw-cancel-btn');
        const confirmBtn = document.getElementById('withdraw-confirm-btn');
        const maxBtn = document.getElementById('withdraw-max-btn');
        const input = document.getElementById('withdraw-amount-input');
        const availableEl = document.getElementById('withdraw-available');
        const destinationEl = document.getElementById('withdraw-destination');
        const addressEl = document.getElementById('withdraw-modal-address');
        const maxWithdrawUsdc = Math.max(0, Number(availableUsdc) - WITHDRAW_FEE_RESERVE_USDC);
        const formattedAvailable = Number(availableUsdc).toFixed(6);
        const formattedMax = maxWithdrawUsdc.toFixed(6);

        if (!modal || !input || !confirmBtn || !cancelBtn || !closeBtn || !maxBtn) {
            resolve(null);
            return;
        }

        availableEl.textContent = `${formattedAvailable} USDC`;
        destinationEl.textContent = shortAddress(connectedWallet);
        destinationEl.title = connectedWallet || '';
        addressEl.textContent = connectedWallet || 'Seller wallet';
        input.value = formattedMax;
        input.max = formattedMax;
        input.min = '0.000001';
        document.getElementById('withdraw-help').textContent =
            `Circle Gateway requires a small withdrawal fee reserve. Max withdraw is ${formattedMax} USDC, leaving about ${WITHDRAW_FEE_RESERVE_USDC.toFixed(4)} USDC for fees.`;
        modal.classList.add('open');
        modal.setAttribute('aria-hidden', 'false');
        setTimeout(() => input.focus(), 50);

        const cleanup = () => {
            modal.classList.remove('open');
            modal.setAttribute('aria-hidden', 'true');
            closeBtn.onclick = null;
            cancelBtn.onclick = null;
            confirmBtn.onclick = null;
            maxBtn.onclick = null;
            input.onkeydown = null;
        };

        const cancel = () => {
            cleanup();
            resolve(null);
        };

        const submit = () => {
            const amount = Number(input.value);
            if (!Number.isFinite(amount) || amount <= 0 || amount > maxWithdrawUsdc) {
                showToast(`Enter an amount between 0 and ${formattedMax} USDC. The remaining balance covers Circle Gateway withdrawal fees.`, 'warning');
                return;
            }
            cleanup();
            resolve(amount.toFixed(6));
        };

        closeBtn.onclick = cancel;
        cancelBtn.onclick = cancel;
        maxBtn.onclick = () => {
            input.value = formattedMax;
            input.focus();
        };
        confirmBtn.onclick = submit;
        input.onkeydown = (event) => {
            if (event.key === 'Enter') submit();
            if (event.key === 'Escape') cancel();
        };
    });
}

async function withdrawSellerGatewayFunds() {
    if (!connectedWallet) {
        alert("Connect your wallet first.");
        return;
    }
    if (!sameAddress(connectedWallet, sellerWalletAddress)) {
        alert(`Connected wallet is not the designated Seller wallet (${sellerWalletAddress}).`);
        return;
    }
    if (!gatewayContractAddress) {
        alert("Circle Gateway contract address is unknown. Wait for health check.");
        return;
    }

    try {
        const metricsResp = await fetch(apiUrl(`/api/v1/metrics/wallet/${connectedWallet}`));
        if (!metricsResp.ok) throw new Error("Could not fetch seller balance.");
        const metrics = await metricsResp.json();
        const availableUsdc = metrics?.gateway_balance?.available_usdc || 0;

        if (availableUsdc <= 0) {
            alert(`Seller Gateway has no available balance to withdraw. (Current: ${availableUsdc} USDC)`);
            return;
        }
        if (availableUsdc <= WITHDRAW_FEE_RESERVE_USDC) {
            alert(`Seller Gateway balance is ${availableUsdc.toFixed(6)} USDC, which is not enough after the estimated ${WITHDRAW_FEE_RESERVE_USDC.toFixed(4)} USDC withdrawal fee reserve.`);
            return;
        }

        const amountStr = await requestWithdrawAmount(availableUsdc);
        if (amountStr === null) return;

        const amount = parseFloat(amountStr);
        if (isNaN(amount) || amount <= 0 || amount > availableUsdc) {
            alert("Invalid amount specified.");
            return;
        }

        await ensureArcTestnet();

        const withdrawBtn = document.getElementById('wallet-withdraw-menu-btn');
        const originalText = withdrawBtn ? withdrawBtn.innerHTML : '';
        if (withdrawBtn) {
            withdrawBtn.disabled = true;
            withdrawBtn.innerHTML = `<span>Signing...</span>`;
        }

        try {
            // 1. Prepare EIP-712 typed signature for BurnIntent
            const addressToBytes32 = (addr) => '0x' + addr.replace('0x', '').toLowerCase().padStart(64, '0');
            const salt = '0x' + Array.from({ length: 32 }, () => Math.floor(Math.random() * 256).toString(16).padStart(2, '0')).join('');
            const usdcContract = '0x3600000000000000000000000000000000000000';
            const gatewayMinter = '0x0022222ABE238Cc2C7Bb1f21003F0a260052475B';

            const burnIntent = {
                maxBlockHeight: '115792089237316195423570985008687907853269984665640564039457584007913129639935',
                maxFee: String(Math.round(2.01 * 1_000_000)),
                spec: {
                    version: 1,
                    sourceDomain: 26,
                    destinationDomain: 26,
                    sourceContract: addressToBytes32(gatewayContractAddress),
                    destinationContract: addressToBytes32(gatewayMinter),
                    sourceToken: addressToBytes32(usdcContract),
                    destinationToken: addressToBytes32(usdcContract),
                    sourceDepositor: addressToBytes32(connectedWallet),
                    destinationRecipient: addressToBytes32(connectedWallet),
                    sourceSigner: addressToBytes32(connectedWallet),
                    destinationCaller: addressToBytes32('0x0000000000000000000000000000000000000000'),
                    value: String(Math.round(amount * 1_000_000)),
                    salt: salt,
                    hookData: "0x"
                }
            };

            const msgParams = JSON.stringify({
                domain: { name: "GatewayWallet", version: "1" },
                message: burnIntent,
                primaryType: "BurnIntent",
                types: {
                    EIP712Domain: [
                        { name: "name", type: "string" },
                        { name: "version", type: "string" }
                    ],
                    TransferSpec: [
                        { name: "version", type: "uint32" },
                        { name: "sourceDomain", type: "uint32" },
                        { name: "destinationDomain", type: "uint32" },
                        { name: "sourceContract", type: "bytes32" },
                        { name: "destinationContract", type: "bytes32" },
                        { name: "sourceToken", type: "bytes32" },
                        { name: "destinationToken", type: "bytes32" },
                        { name: "sourceDepositor", type: "bytes32" },
                        { name: "destinationRecipient", type: "bytes32" },
                        { name: "sourceSigner", type: "bytes32" },
                        { name: "destinationCaller", type: "bytes32" },
                        { name: "value", type: "uint256" },
                        { name: "salt", type: "bytes32" },
                        { name: "hookData", type: "bytes" }
                    ],
                    BurnIntent: [
                        { name: "maxBlockHeight", type: "uint256" },
                        { name: "maxFee", type: "uint256" },
                        { name: "spec", type: "TransferSpec" }
                    ]
                }
            });

            const signature = await ethereum.request({
                method: 'eth_signTypedData_v4',
                params: [connectedWallet, msgParams]
            });

            // 2. Submit the signed burnIntent to Circle Gateway
            if (withdrawBtn) withdrawBtn.innerHTML = `<span>Withdrawing...</span>`;
            const submitResp = await fetch(apiUrl('/api/v1/payment/withdraw'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ burnIntent, signature })
            });
            if (!submitResp.ok) {
                const errData = await submitResp.json();
                throw new Error(errData.detail || "Circle Gateway transfer submission failed.");
            }
            const submitResult = await submitResp.json();
            if (!submitResult.attestation || !submitResult.signature) {
                throw new Error("Circle Gateway did not return a mint attestation. Withdrawal transaction was not sent.");
            }

            // 3. Mint the USDC on Arc Testnet via GatewayMinter contract
            if (withdrawBtn) withdrawBtn.innerHTML = `<span>Minting...</span>`;
            const mintCalldata = encodeGatewayMintCalldata(submitResult.attestation, submitResult.signature);

            const txHash = await ethereum.request({
                method: 'eth_sendTransaction',
                params: [{
                    from: connectedWallet,
                    to: gatewayMinter,
                    data: mintCalldata,
                    gas: '0x493e0'
                }]
            });

            if (withdrawBtn) withdrawBtn.innerHTML = `<span>Confirming...</span>`;
            await waitForReceipt(txHash);

            saveWalletEvent(connectedWallet, {
                type: 'withdraw',
                amount_usdc: amount.toFixed(6),
                tx_hash: txHash,
                explorer_url: explorerTx(txHash)
            });

            alert(`Withdrawal transaction confirmed!\nTx hash: ${txHash.slice(0, 10)}...${txHash.slice(-8)}\nUSDC has been transferred to your wallet.`);
            loadMetrics();
        } finally {
            if (withdrawBtn) {
                withdrawBtn.disabled = false;
                withdrawBtn.innerHTML = originalText;
            }
        }
    } catch (err) {
        if (err.code === 4001 || err.message?.includes('User rejected')) {
            alert("Withdrawal cancelled by user.");
        } else {
            alert("Error executing withdrawal: " + err.message);
        }
    }
}

function gatewayStatusBadge(status) {
    if (!status) return '<span style="color:var(--text-dark);">—</span>';
    const s = String(status).toLowerCase();
    if (s === 'received' || s === 'batched') {
        return `<span style="color:#f59e0b;font-weight:600;" title="Circle accepted the payment signature. On-chain batch not yet submitted.">⏳ ${escapeHtml(status)}</span>`;
    }
    if (s === 'completed' || s === 'confirmed') {
        return `<span style="color:var(--color-success);font-weight:600;" title="On-chain batch transaction confirmed on Arcscan.">✔ ${escapeHtml(status)}</span>`;
    }
    return `<span style="color:var(--text-muted);">${escapeHtml(status)}</span>`;
}

function renderPaymentActivity(events) {
    if (!paymentActivityBody) return;
    if (!events.length) {
        paymentActivityBody.innerHTML = '<tr><td colspan="5" style="color: var(--text-dark);">No payments yet.</td></tr>';
        return;
    }
    paymentActivityBody.innerHTML = events.map((event) => {
        const ref = event.explorer_url && event.transaction_hash
            ? `<a class="tx-link" href="${event.explorer_url}" target="_blank" rel="noreferrer" title="Settlement: ${escapeHtml(event.settlement_id || '')}">${shortAddress(event.transaction_hash)}</a>`
            : event.settlement_id
                ? `<span class="mono-td" title="Settlement ID: ${escapeHtml(event.settlement_id)}">${shortAddress(event.settlement_id)}</span><div style="color:#f59e0b; font-size:0.72rem; margin-top:2px;">⏳ Arcscan tx pending</div>`
                : '<span style="color: var(--text-dark);">n/a</span>';
        return `
                    <tr>
                        <td class="mono-td">${escapeHtml(event.symbol || 'n/a')}<div style="color:var(--t3); font-size:0.66rem; margin-top:2px;">${escapeHtml(formatDateTime(event.paid_at))}</div></td>
                        <td title="${escapeHtml(event.payer_address || '')}">${shortAddress(event.payer_address)}</td>
                        <td>${Number(event.amount_usdc || 0).toFixed(3)} USDC<div style="color:var(--t3); font-size:0.66rem;">${escapeHtml(tierLabel(event.tier || 'full'))}</div></td>
                        <td>${gatewayStatusBadge(event.gateway_status)}</td>
                        <td>${ref}</td>
                    </tr>
                `;
    }).join('');
}

function renderPayerBreakdown(payers) {
    if (!payerBreakdownBody) return;
    if (!payers.length) {
        payerBreakdownBody.innerHTML = '<tr><td colspan="3" style="color: var(--text-dark);">No wallet activity yet.</td></tr>';
        return;
    }
    payerBreakdownBody.innerHTML = payers.map((payer) => {
        const symbols = (payer.symbols || []).slice(0, 5).join(', ') || 'n/a';
        const overflow = (payer.symbols || []).length > 5 ? ` +${payer.symbols.length - 5}` : '';
        return `
                    <tr title="Last paid: ${escapeHtml(formatDateTime(payer.last_paid_at))}">
                        <td class="mono-td" title="${escapeHtml(payer.payer_address || '')}">${shortAddress(payer.payer_address)}</td>
                        <td>${payer.payments || 0} / ${escapeHtml(symbols)}${overflow}</td>
                        <td>${Number(payer.spent_usdc || 0).toFixed(3)} USDC<div style="color:var(--t3); font-size:0.66rem;">P:${payer.preview_count || 0} F:${payer.full_count || 0}</div></td>
                    </tr>
                `;
    }).join('');
}

function getFormQuery() {
    return {
        symbol: fSymbol.value,
        fundingRate: parseFloat(fFunding.value),
        marketCap: parseFloat(fMcap.value),
        FDV: parseFloat(fFdv.value),
        circRatio: parseFloat(fCirc.value),
        fromATH: parseFloat(fAth.value),
        volume24h: parseFloat(fVol.value)
    };
}

function formSignalFromAnomaly(item) {
    return {
        symbol: item.symbol,
        fundingRate: Number(item.fundingRate.toFixed(4)),
        marketCap: Math.round(item.marketCap),
        FDV: Math.round(item.FDV),
        circRatio: Number(item.circRatio.toFixed(2)),
        fromATH: Number(item.fromATH.toFixed(2)),
        volume24h: Math.round(item.volume24h),
        ...(item.amount ? { amount: Number(item.amount) } : {})
    };
}

function applySignalToForm(signal) {
    fSymbol.value = signal.symbol;
    fFunding.value = Number(signal.fundingRate).toFixed(4);
    fMcap.value = Math.round(signal.marketCap);
    fFdv.value = Math.round(signal.FDV);
    fCirc.value = Number(signal.circRatio).toFixed(2);
    fAth.value = Number(signal.fromATH).toFixed(2);
    fVol.value = Math.round(signal.volume24h);
}

function hidePaywall() {
    paywallElement.style.display = 'none';
    paywallElement.classList.remove('compact-paywall');
    currentInvoiceId = null;
    currentInvoiceSecret = null;
    currentArcGatewayUrl = null;
    currentSettlementId = null;
    currentSellerAddress = null;
    currentAccessToken = null;
    document.getElementById('inv-id-row').style.display = 'none';
    document.getElementById('payment-flow-panel').style.display = 'none';
}

function showSignalPaywall(source, options = {}) {
    const signal = normalizeSignalPayload(source);
    const tier = normalizeTier(options.tier || currentInvoiceTier || 'full');
    currentInvoiceTier = tier;
    currentInvoiceAmount = tierPrice(tier);
    activeQuery = {
        symbol: signal.symbol,
        fundingRate: signal.fundingRate,
        marketCap: signal.marketCap,
        FDV: signal.FDV,
        circRatio: signal.circRatio,
        fromATH: signal.fromATH,
        volume24h: signal.volume24h,
        ...(signal.amount ? { amount: signal.amount } : {})
    };
    currentInvoiceId = null;
    currentInvoiceSecret = null;
    currentArcGatewayUrl = null;
    currentSettlementId = null;
    currentSellerAddress = null;
    currentAccessToken = null;
    paywallTitle.textContent = options.title || 'USDC Micro-Payment Required';
    paywallDesc.textContent = options.description || 'This exact signal snapshot has not been purchased. Create a paid invoice to unlock the historical analog report for these current inputs.';
    invoiceSignalDisplay.textContent = signalSummary(signal);
    document.getElementById('invoice-amount-display').textContent = `${currentInvoiceAmount.toFixed(3)} USDC`;
    document.getElementById('invoice-tier-display').textContent = tierLabel(tier);
    document.getElementById('invoice-network-display').textContent = 'Arc Testnet';
    document.getElementById('inv-id-row').style.display = 'none';
    document.getElementById('payment-flow-panel').style.display = 'none';
    payButton.innerHTML = `<span>Create ${tierLabel(tier)} Invoice First</span>`;
    paywallElement.style.display = 'flex';
    paywallElement.classList.remove('compact-paywall');
}

function loadCardIntoForm(item) {
    const signal = formSignalFromAnomaly(item);
    applySignalToForm(signal);
    activeQuery = signal;
    const cachedEntry = getCachedReport(signal);
    if (cachedEntry?.report) {
        renderReport(cachedEntry.report, cachedEntry);
        showToast(`Loaded paid ${item.symbol} signal from ${formatDateTime(cachedEntry.saved_at)}.`, 'success');
        return;
    }

    const previousReports = getCachedReportsForSymbol(signal.symbol);
    if (previousReports.length) {
        const previousEntry = {
            ...previousReports[0],
            previous_snapshot_for: signal
        };
        if (normalizeTier(previousEntry.tier || previousEntry.report?.tier || previousEntry.report?.invoice?.tier) === 'preview') {
            renderPreviewReport(previousEntry.report, previousEntry);
        } else {
            renderReport(previousEntry.report, previousEntry);
        }
        showToast(
            `Showing previous paid ${signal.symbol} report from ${formatDateTime(previousEntry.saved_at)}. The current live snapshot still needs a new purchase.`,
            'warning'
        );
    } else {
        showSignalPaywall(getFormQuery(), {
            tier: 'full',
            title: 'Signal Not Purchased',
            description: 'This Live Anomaly snapshot is not unlocked yet. Click Retrieve Analogs to create a paid invoice for this exact signal.'
        });
    }
}

function lockViewport() {
    paywallElement.style.display = 'flex';
    paywallElement.classList.remove('compact-paywall');
    if (!hasUnlockedReport) {
        document.getElementById('viewport-container').classList.remove('unlocked');
    }
    currentInvoiceId = null;
    currentInvoiceSecret = null;
    currentArcGatewayUrl = null;
    currentSettlementId = null;
    currentSellerAddress = null;
    currentAccessToken = null;
    invoiceSignalDisplay.textContent = activeQuery ? signalSummary(activeQuery) : 'n/a';
    document.getElementById('invoice-amount-display').textContent = `${currentInvoiceAmount.toFixed(3)} USDC`;
    document.getElementById('invoice-tier-display').textContent = tierLabel(currentInvoiceTier);
    payButton.innerHTML = `<span>Pay on Arc Testnet (${currentInvoiceAmount.toFixed(3)} USDC)</span>`;
    document.getElementById('inv-id-row').style.display = 'none';
    document.getElementById('payment-flow-panel').style.display = 'none';
}

// Trigger retrieval (Creates payment invoice)
queryForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    activeQuery = getFormQuery();
    currentInvoiceTier = normalizeTier(e.submitter?.dataset?.tier || 'full');
    currentInvoiceAmount = tierPrice(currentInvoiceTier);
    const cachedEntry = getCachedReport(activeQuery, currentInvoiceTier);
    if (cachedEntry?.report) {
        if (normalizeTier(cachedEntry.tier || cachedEntry.report?.tier || cachedEntry.report?.invoice?.tier) === 'preview') {
            renderPreviewReport(cachedEntry.report, cachedEntry);
        } else {
            renderReport(cachedEntry.report, cachedEntry);
        }
        showToast(`Loaded paid ${tierLabel(currentInvoiceTier)} ${activeQuery.symbol} signal from ${formatDateTime(cachedEntry.saved_at)}.`, 'success');
        return;
    }

    lockViewport();

    // Call create invoice
    try {
        const invoiceResp = await fetch(apiUrl('/api/v1/payment/invoice'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ...activeQuery,
                provider_id: currentProviderId,
                buyer_type: 'human',
                tier: currentInvoiceTier,
                resource_type: 'qma_signal_report'
            })
        });
        const invoiceData = await invoiceResp.json();

        currentInvoiceId = invoiceData.invoice_id;
        currentInvoiceSecret = invoiceData.invoice_secret;
        currentArcGatewayUrl = invoiceData.arc_gateway_url;
        currentInvoiceAmount = Number(invoiceData.amount);
        currentInvoiceTier = normalizeTier(invoiceData.tier || currentInvoiceTier);
        currentProviderId = invoiceData.provider_id || currentProviderId;
        currentSellerAddress = invoiceData.wallet_address;
        document.getElementById('inv-id-display').textContent = currentInvoiceId;
        document.getElementById('inv-id-row').style.display = 'flex';
        invoiceSignalDisplay.textContent = signalSummary(activeQuery);
        paywallTitle.textContent = `${tierLabel(currentInvoiceTier)} Payment Required`;
        paywallDesc.textContent = currentInvoiceTier === 'preview'
            ? `Unlock a lightweight ${invoiceData.provider_name || 'QMA'} preview for this exact live signal. Upgrade to the full report for all analogs, percentiles, and diagnostics.`
            : `Unlock this exact full ${invoiceData.provider_name || 'QMA'} signal snapshot. If the token changes later, QMA treats that as a new signal and requires a new paid report.`;
        document.getElementById('invoice-amount-display').textContent = `${invoiceData.amount} ${invoiceData.currency}`;
        document.getElementById('invoice-tier-display').textContent = invoiceData.tier_label || tierLabel(currentInvoiceTier);
        document.getElementById('invoice-network-display').textContent = invoiceData.network_name || invoiceData.network;
        payButton.innerHTML = `<span>Pay on Arc Testnet (${Number(invoiceData.amount).toFixed(3)} USDC)</span>`;

        // Show payment flow panel and pre-fill seller wallet info
        const pfPanel = document.getElementById('payment-flow-panel');
        pfPanel.style.display = 'block';
        document.getElementById('pf-seller-wallet-addr').textContent = invoiceData.wallet_address || '—';
        // Gateway contract address
        document.getElementById('pf-gateway-contract').textContent = gatewayContractAddress || 'Circle Gateway Contract (fetching...)';

        // Pre-fetch balance status if wallet connected
        let currentWalletBal = null;
        let currentGwBal = null;
        if (connectedWallet) {
            try {
                const [status, gw] = await Promise.all([
                    getWalletStatus(connectedWallet),
                    checkGatewayBalance(connectedWallet)
                ]);
                currentWalletBal = getOnChainUsdcBalance(status);
                currentGwBal = gw;
            } catch (e) {
                console.warn("Could not pre-fetch balances", e);
            }
        }

        // Reset flow rows to pre-payment state
        updatePaymentFlowPanel({
            stage: 'created',
            buyerWalletBal: currentWalletBal,
            buyerGatewayBal: currentGwBal
        });
    } catch (err) {
        alert("Failed to initiate micro-payment invoice. Backend may be offline.");
    }
});

// Circle Gateway x402 payment on Arc Testnet
payButton.addEventListener('click', async () => {
    if (!currentInvoiceId) {
        alert("Please submit the query first to generate an invoice.");
        return;
    }
    if (!currentArcGatewayUrl) {
        alert("Arc Gateway URL is missing. Create a new invoice.");
        return;
    }
    if (!window.ethereum) {
        alert("MetaMask is required to pay on Arc Testnet.");
        return;
    }

    payButton.disabled = true;
    payButton.innerHTML = `
                <div class="spinner" style="width: 16px; height: 16px;"></div>
                <span>Waiting for MetaMask...</span>
            `;

    let account = null;
    try {
        account = connectedWallet || await connectWallet();
        if (!account) {
            throw new Error('Connect a buyer wallet first.');
        }
        await ensureArcTestnet();
        if (sameAddress(account, currentSellerAddress)) {
            throw new Error(`Connected wallet is the seller wallet (${currentSellerAddress}). Circle rejects self-transfer payments. Switch MetaMask to a buyer wallet such as acc1, or set QMA_ARC_SELLER_ADDRESS to a separate treasury wallet.`);
        }

        payButton.innerHTML = `
                    <div class="spinner" style="width: 16px; height: 16px;"></div>
                    <span>Checking Gateway balance...</span>
                `;
        if (!arcGatewayBaseUrl) {
            await loadHealthInfo();
        }
        const [gatewayBalance, walletStatus] = await Promise.all([
            checkGatewayBalance(account),
            getWalletStatus(account)
        ]);
        const walletBal = getOnChainUsdcBalance(walletStatus);
        updatePaymentFlowPanel({ stage: 'checking', buyerGatewayBal: gatewayBalance, buyerWalletBal: walletBal });

        if (gatewayBalance === null) {
            throw new Error('Could not read Circle Gateway balance from the Arc Gateway service. Please retry after the Gateway health check is ready.');
        }

        if (gatewayBalance + 1e-9 < currentInvoiceAmount) {
            const defaultDeposit = Math.max(1, currentInvoiceAmount * 20);
            const requiredTopUp = Math.max(currentInvoiceAmount - gatewayBalance, 0);
            const depositAmount = Math.max(defaultDeposit, requiredTopUp);
            const ok = await requestActionConfirmation({
                title: 'Deposit to Circle Gateway',
                subtitle: 'Pre-fund Gateway balance for paid QMA reports',
                rows: [
                    { label: 'Buyer Wallet', value: shortAddress(account) },
                    { label: 'Current Gateway Balance', value: `${gatewayBalance.toFixed(6)} USDC` },
                    { label: 'Report Tier', value: tierLabel(currentInvoiceTier) },
                    { label: 'Report Cost', value: `${currentInvoiceAmount.toFixed(3)} USDC` },
                    { label: 'Deposit Amount', value: `${depositAmount.toFixed(2)} USDC` },
                    { label: 'Gateway Contract', value: shortAddress(gatewayContractAddress) },
                ],
                warning: 'This will open your wallet for USDC approval if allowance is too low, then a Gateway deposit transaction. Future reports can skip deposit until this prepaid balance runs out.',
                confirmLabel: 'Deposit',
            });
            if (!ok) {
                throw new Error('Payment requires Circle Gateway balance. Deposit first, then retry.');
            }
            const depositResult = await depositToGateway(account, depositAmount, walletStatus);
            payButton.innerHTML = `
                        <div class="spinner" style="width: 16px; height: 16px;"></div>
                        <span>Waiting for Gateway balance...</span>
                    `;
            const refreshedBalance = await waitForGatewayBalance(account, currentInvoiceAmount);

            const updatedWalletStatus = await getWalletStatus(account);
            const updatedWalletBal = getOnChainUsdcBalance(updatedWalletStatus);
            updatePaymentFlowPanel({ stage: 'checking', buyerGatewayBal: refreshedBalance, buyerWalletBal: updatedWalletBal });

            if (refreshedBalance === null) {
                throw new Error(`Gateway deposit tx was mined, but QMA could not read Circle Gateway balance yet. Deposit tx: ${depositResult.depositHash}. Wait a bit and retry payment.`);
            }

            if (refreshedBalance + 1e-9 < currentInvoiceAmount) {
                throw new Error(`Gateway deposit is mined but Circle balance has not updated enough yet. Current balance: ${refreshedBalance.toFixed(6)} USDC. Deposit tx: ${depositResult.depositHash}. Wait a bit and retry payment.`);
            }
        }

        payButton.innerHTML = `
                    <div class="spinner" style="width: 16px; height: 16px;"></div>
                    <span>Fetching x402 challenge...</span>
                `;
        const challengeResp = await fetch(currentArcGatewayUrl);
        if (challengeResp.status !== 402) {
            const body = await challengeResp.text();
            throw new Error(`Expected x402 challenge, got ${challengeResp.status}: ${body}`);
        }

        const requiredHeader = challengeResp.headers.get('PAYMENT-REQUIRED') || challengeResp.headers.get('payment-required');
        if (!requiredHeader) {
            throw new Error('Arc Gateway did not return PAYMENT-REQUIRED header.');
        }

        const challenge = JSON.parse(b64decode(requiredHeader));
        const accepted = challenge.accepts[0];
        const chainId = parseInt(accepted.network.split(':')[1], 10);
        const now = Math.floor(Date.now() / 1000);
        const validBefore = (now + Math.max(accepted.maxTimeoutSeconds || 0, 7 * 24 * 3600 + 600)).toString();
        const validAfter = (now - 600).toString();
        const nonce = randomNonceHex();

        const typedData = {
            types: {
                EIP712Domain: [
                    { name: 'name', type: 'string' },
                    { name: 'version', type: 'string' },
                    { name: 'chainId', type: 'uint256' },
                    { name: 'verifyingContract', type: 'address' }
                ],
                TransferWithAuthorization: [
                    { name: 'from', type: 'address' },
                    { name: 'to', type: 'address' },
                    { name: 'value', type: 'uint256' },
                    { name: 'validAfter', type: 'uint256' },
                    { name: 'validBefore', type: 'uint256' },
                    { name: 'nonce', type: 'bytes32' }
                ]
            },
            primaryType: 'TransferWithAuthorization',
            domain: {
                name: 'GatewayWalletBatched',
                version: '1',
                chainId,
                verifyingContract: accepted.extra.verifyingContract
            },
            message: {
                from: account,
                to: accepted.payTo,
                value: accepted.amount,
                validAfter,
                validBefore,
                nonce
            }
        };

        payButton.innerHTML = `
                    <div class="spinner" style="width: 16px; height: 16px;"></div>
                    <span>Sign payment authorization...</span>
                `;
        const signature = await ethereum.request({
            method: 'eth_signTypedData_v4',
            params: [account, JSON.stringify(typedData)]
        });

        const paymentPayload = {
            x402Version: 2,
            payload: {
                signature,
                authorization: {
                    from: account,
                    to: accepted.payTo,
                    value: accepted.amount,
                    validAfter,
                    validBefore,
                    nonce
                }
            },
            accepted,
            resource: challenge.resource
        };

        payButton.innerHTML = `
                    <div class="spinner" style="width: 16px; height: 16px;"></div>
                    <span>Settling via Circle...</span>
                `;
        const paidResp = await fetch(currentArcGatewayUrl, {
            headers: { 'payment-signature': b64encode(paymentPayload) }
        });
        const paidData = await paidResp.json().catch(async () => ({ error: await paidResp.text() }));
        if (!paidResp.ok) {
            const reason = paidData.reason || paidData.errorReason || paidData.message || paidData.error;
            throw new Error(reason ? `${paidData.error || 'Arc settlement failed'}: ${reason}` : `Arc Gateway returned ${paidResp.status}`);
        }
        currentSettlementId = paidData.settlementId;
        if (!currentSettlementId) {
            throw new Error('Arc Gateway did not return a settlementId.');
        }
        saveWalletEvent(account, {
            type: 'x402_settlement',
            amount_usdc: paidData.amount_usdc,
            settlement_id: currentSettlementId,
            tier: currentInvoiceTier,
            symbol: activeQuery.symbol
        });
        // Update flow panel: Circle received the signature
        updatePaymentFlowPanel({ stage: 'received', settlementId: currentSettlementId });

        const verifyResp = await fetch(apiUrl(`/api/v1/payment/verify?invoice_id=${currentInvoiceId}`), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                settlement_id: currentSettlementId,
                invoice_secret: currentInvoiceSecret,
                payer_address: account,
                amount_usdc: Number(paidData.amount_usdc)
            })
        });
        const verifyData = await verifyResp.json();
        if (!verifyResp.ok) {
            const detail = typeof verifyData.detail === 'object'
                ? JSON.stringify(verifyData.detail)
                : verifyData.detail;
            throw new Error(detail || 'QMA could not verify Circle settlement.');
        }

        if (verifyData.status === 'paid') {
            currentAccessToken = verifyData.access_token || null;
            if (!currentAccessToken) {
                throw new Error('QMA verification did not return an access token for this paid report.');
            }
            saveWalletEvent(account, {
                type: 'verified_payment',
                amount_usdc: paidData.amount_usdc || currentInvoiceAmount,
                settlement_id: currentSettlementId,
                tx_hash: verifyData.transaction_hash,
                explorer_url: verifyData.explorer_url,
                tier: currentInvoiceTier,
                symbol: activeQuery.symbol
            });

            // Fetch latest balances
            const finalStatus = await getWalletStatus(account);
            const finalGwBal = await checkGatewayBalance(account);

            // Update flow panel with verify response data
            updatePaymentFlowPanel({
                stage: verifyData.transaction_hash ? 'completed' : 'received',
                buyerWalletBal: getOnChainUsdcBalance(finalStatus),
                buyerGatewayBal: finalGwBal,
                settlementId: currentSettlementId,
                gatewayStatus: verifyData.gateway_status,
                sellerAvailable: verifyData.seller_gateway_available_usdc,
                sellerPending: verifyData.seller_gateway_pending_batch_usdc,
                sellerWallet: verifyData.seller_wallet,
                txHash: verifyData.transaction_hash,
                explorerUrl: verifyData.explorer_url,
            });
            // Pull paid QMA output for the selected tier
            const outputEndpoint = currentInvoiceTier === 'preview'
                ? `/api/v1/providers/${encodeURIComponent(currentProviderId)}/preview`
                : `/api/v1/providers/${encodeURIComponent(currentProviderId)}/full-report`;
            const analyzeResp = await fetch(apiUrl(`${outputEndpoint}?invoice_id=${currentInvoiceId}`), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-QMA-Access-Token': currentAccessToken,
                },
                body: JSON.stringify(activeQuery)
            });
            const reportData = await analyzeResp.json();
            if (!analyzeResp.ok) {
                throw new Error(reportData.detail?.message || reportData.detail || 'Analysis request failed.');
            }

            if (currentInvoiceTier === 'preview') {
                renderPreviewReport(reportData);
            } else {
                renderReport(reportData);
            }
        } else {
            alert("Payment was not accepted by QMA.");
        }
    } catch (err) {
        console.error("Payment error detail:", err);
        const isMetaMaskReject = err.code === 4001 ||
            err.message?.includes('User rejected') ||
            err.message?.includes('rejected') ||
            err.message?.includes('cancelled');

        const isCancelError = isMetaMaskReject || err.message?.includes('Payment requires Circle Gateway balance');

        if (isCancelError) {
            let cancelMessage = "Payment cancelled";
            if (err.message?.includes('Payment requires Circle Gateway balance')) {
                cancelMessage = "Cancelled: Gateway balance insufficient. Deposit required.";
            } else if (err.message?.includes('User rejected')) {
                cancelMessage = "MetaMask signature rejected — no funds sent";
            }

            let latestWalletBal = null;
            let latestGwBal = null;
            if (account) {
                try {
                    const [status, gw] = await Promise.all([
                        getWalletStatus(account),
                        checkGatewayBalance(account)
                    ]);
                    latestWalletBal = getOnChainUsdcBalance(status);
                    latestGwBal = gw;
                } catch (e) { }
            }

            updatePaymentFlowPanel({
                stage: 'cancelled',
                cancelMessage: cancelMessage,
                buyerWalletBal: latestWalletBal,
                buyerGatewayBal: latestGwBal
            });
        } else {
            alert("Error during payment verification: " + err.message);
        }
    } finally {
        payButton.disabled = false;
        payButton.innerHTML = `<span>Pay on Arc Testnet (${currentInvoiceAmount.toFixed(3)} USDC)</span>`;
    }
});

/**
 * updatePaymentFlowPanel — updates the 4-level payment flow panel.
 * stages: 'created' | 'checking' | 'received' | 'completed' | 'cancelled'
 */
function updatePaymentFlowPanel(opts = {}) {
    const { stage, buyerWalletBal, buyerGatewayBal, settlementId, gatewayStatus, sellerAvailable, sellerPending, sellerWallet, txHash, explorerUrl, cancelMessage } = opts;

    // Buyer wallet balance
    const pfBuyerWalletBal = document.getElementById('pf-buyer-wallet-bal');
    if (pfBuyerWalletBal) {
        if (buyerWalletBal != null) {
            pfBuyerWalletBal.textContent = `${Number(buyerWalletBal).toFixed(6)} USDC`;
        } else if (stage === 'created') {
            pfBuyerWalletBal.textContent = '—';
        }
    }

    // Buyer gateway balance
    const pfBuyerGwBal = document.getElementById('pf-buyer-gateway-bal');
    if (pfBuyerGwBal) {
        if (buyerGatewayBal != null) {
            pfBuyerGwBal.textContent = `Your gateway balance (no deduction yet): ${Number(buyerGatewayBal).toFixed(6)} USDC`;
        } else if (stage === 'created') {
            pfBuyerGwBal.textContent = 'Your gateway balance: —';
        }
    }

    // Settlement status row
    const pfStatus = document.getElementById('pf-settlement-status');
    const pfSettleId = document.getElementById('pf-settlement-id');
    if (pfStatus) {
        if (stage === 'received') {
            pfStatus.innerHTML = '<span class="pf-status-received">⏳ Circle accepted — waiting for on-chain batch</span>';
        } else if (stage === 'completed') {
            pfStatus.innerHTML = '<span class="pf-status-completed">✔ On-chain batch confirmed</span>';
        } else if (stage === 'checking') {
            pfStatus.innerHTML = '<span class="pf-status-pending">⏳ Checking / preparing signature...</span>';
        } else if (stage === 'cancelled') {
            pfStatus.innerHTML = `<span style="color: var(--color-danger); font-weight: 600;">❌ ${cancelMessage || 'Payment cancelled — no funds sent'}</span>`;
        } else {
            pfStatus.innerHTML = '<span class="pf-status-pending">— awaiting payment</span>';
        }
    }
    if (pfSettleId) {
        if (settlementId) {
            pfSettleId.textContent = `Settlement ID: ${shortAddress(settlementId)}`;
            pfSettleId.title = settlementId;
        } else if (stage === 'created' || stage === 'checking' || stage === 'cancelled') {
            pfSettleId.textContent = '—';
        }
    }

    // Seller gateway balances
    if (sellerAvailable != null) document.getElementById('pf-seller-available').textContent = `${Number(sellerAvailable).toFixed(6)} USDC`;
    if (sellerPending != null) document.getElementById('pf-seller-pending').textContent = `${Number(sellerPending).toFixed(6)} USDC`;
    if (sellerWallet) document.getElementById('pf-seller-wallet-addr').textContent = sellerWallet;

    // Arcscan tx link
    const pfArcscanRow = document.getElementById('pf-arcscan-tx');
    const pfArcscanLink = document.getElementById('pf-arcscan-link');
    if (txHash && explorerUrl && pfArcscanRow && pfArcscanLink) {
        pfArcscanLink.href = explorerUrl;
        pfArcscanLink.textContent = shortAddress(txHash);
        pfArcscanLink.title = txHash;
        pfArcscanRow.style.display = 'block';
    } else if (stage === 'created' || stage === 'checking' || stage === 'cancelled') {
        if (pfArcscanRow) pfArcscanRow.style.display = 'none';
    }
}

// Render report output
function renderPreviewReport(report, cachedEntry = null) {
    if (!report.query && cachedEntry?.signal) {
        report.query = normalizeSignalPayload(cachedEntry.signal);
    } else if (!report.query && activeQuery) {
        report.query = normalizeSignalPayload(activeQuery);
    }
    if (!cachedEntry) {
        saveCachedReport(report);
    }
    paywallElement.style.display = 'none';
    paywallElement.classList.remove('compact-paywall');
    document.getElementById('viewport-container').classList.add('unlocked');
    hasUnlockedReport = true;

    document.getElementById('res-win-rate').textContent = `${Number(report.rough_win_rate || 0).toFixed(1)}%`;
    document.getElementById('res-win-rate-ci').textContent = `Preview band: ${escapeHtml(report.win_rate_band || 'n/a')}`;
    document.getElementById('res-avg-pnl').textContent = 'Upgrade';
    document.getElementById('res-avg-pnl-ci').textContent = 'Full report unlocks weighted PnL and confidence intervals';
    document.getElementById('res-regime-name').textContent = report.regime_cluster || 'Preview Regime';
    document.getElementById('res-regime-desc').textContent = report.regime_description || report.upgrade_cta || 'Preview unlocked.';

    const oodBadge = document.getElementById('res-ood-status');
    if (report.is_ood) {
        oodBadge.textContent = "Out-Of-Distribution";
        oodBadge.className = "pnl-badge loss";
    } else {
        oodBadge.textContent = "In-Distribution";
        oodBadge.className = "pnl-badge win";
    }
    document.getElementById('res-ood-p').textContent = Number(report.ood_p_value || 0).toFixed(5);

    ['p90', 'p75', 'p50', 'p25', 'p10'].forEach((id) => {
        document.getElementById(`res-${id}`).textContent = 'Full';
        document.getElementById(`pb-${id}`).style.width = id === 'p50' ? '18%' : '8%';
    });

    const tbody = document.getElementById('analogs-table-body');
    tbody.innerHTML = '';
    (report.top_analogs || []).forEach(item => {
        const tr = document.createElement('tr');
        const pnl = Number(item.profit_pct || 0);
        const pnlClass = pnl > 0 ? 'win' : 'loss';
        tr.innerHTML = `
                    <td class="mono-td" style="font-weight: 600;">${escapeHtml(item.symbol || 'n/a')}</td>
                    <td class="mono-td">${(Number(item.fundingRate || 0) * 100).toFixed(3)}%</td>
                    <td class="mono-td">Preview</td>
                    <td class="mono-td">Preview</td>
                    <td class="mono-td">Preview</td>
                    <td class="mono-td">${(Number(item.similarity || 0) * 100).toFixed(2)}%</td>
                    <td><span class="pnl-badge ${pnlClass}">${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}%</span></td>
                `;
        tbody.appendChild(tr);
    });

    document.getElementById('diag-clean-rows').textContent = 'Preview';
    document.getElementById('diag-ess').textContent = 'Preview';
    document.getElementById('diag-distance').textContent = 'Preview';
    document.getElementById('diag-ood').textContent = report.is_ood ? 'OOD' : 'In-dist';

    const riskList = document.getElementById('risk-list');
    riskList.innerHTML = '';
    const paidMeta = cachedEntry || getCachedReport(activeQuery || report.query || { symbol: report.query_symbol }, 'preview');
    if (paidMeta?.saved_at) {
        const div = document.createElement('div');
        div.className = 'risk-item';
        div.innerHTML = `<span style="color:var(--green);">Paid preview snapshot:</span> ${escapeHtml(signalSummary(paidMeta.signal || activeQuery || report.query || { symbol: report.query_symbol }))} <span style="color:var(--t3);">- bought ${escapeHtml(formatDateTime(paidMeta.saved_at))}</span>`;
        riskList.appendChild(div);
    }
    const cta = document.createElement('div');
    cta.className = 'risk-item';
    cta.innerHTML = `<span style="color:#f59e0b;">Upgrade:</span> ${escapeHtml(report.upgrade_cta || 'Buy the full report for complete analog evidence.')}`;
    riskList.appendChild(cta);
    if (paidMeta?.previous_snapshot_for) {
        const div = document.createElement('div');
        div.className = 'risk-item';
        div.innerHTML = `<span style="color:#f59e0b;">Current live snapshot is different:</span> ${escapeHtml(signalSummary(paidMeta.previous_snapshot_for))}`;
        riskList.appendChild(div);
    }
    if (report.invoice?.explorer_url && report.invoice?.transaction_hash) {
        const div = document.createElement('div');
        div.className = 'risk-item';
        div.innerHTML = `<span style="color:var(--color-success);">Arcscan batch tx confirmed:</span> <a href="${report.invoice.explorer_url}" target="_blank" rel="noreferrer" style="color: var(--color-primary);">${shortAddress(report.invoice.transaction_hash)}</a>`;
        riskList.prepend(div);
    } else if (report.invoice?.settlement_id) {
        const div = document.createElement('div');
        div.className = 'risk-item';
        div.innerHTML = `<span style="color:#f59e0b;">Circle accepted preview payment</span> - Settlement ID: <span class="mono-td">${shortAddress(report.invoice.settlement_id)}</span>`;
        riskList.prepend(div);
    }
    loadMetrics();
}

function renderReport(report, cachedEntry = null) {
    if (!report.query && cachedEntry?.signal) {
        report.query = normalizeSignalPayload(cachedEntry.signal);
    } else if (!report.query && activeQuery) {
        report.query = normalizeSignalPayload(activeQuery);
    }
    if (!cachedEntry) {
        saveCachedReport(report);
    }
    // Hide paywall and unlock viewport
    paywallElement.style.display = 'none';
    paywallElement.classList.remove('compact-paywall');
    document.getElementById('viewport-container').classList.add('unlocked');
    hasUnlockedReport = true;

    // Render KPIs
    document.getElementById('res-win-rate').textContent = `${report.weighted_win_rate.toFixed(1)}%`;
    document.getElementById('res-win-rate-ci').textContent = `95% CI: [${report.ci_win_rate_95[0].toFixed(1)}% - ${report.ci_win_rate_95[1].toFixed(1)}%]`;

    document.getElementById('res-avg-pnl').textContent = `${report.weighted_avg_profit >= 0 ? '+' : ''}${report.weighted_avg_profit.toFixed(2)}%`;
    document.getElementById('res-avg-pnl-ci').textContent = `95% CI: [${report.ci_avg_profit_95[0].toFixed(2)}% - ${report.ci_avg_profit_95[1].toFixed(2)}%]`;

    // Regime Details
    document.getElementById('res-regime-name').textContent = report.regime_cluster;
    document.getElementById('res-regime-desc').textContent = report.regime_description;

    const oodBadge = document.getElementById('res-ood-status');
    if (report.is_ood) {
        oodBadge.textContent = "Out-Of-Distribution";
        oodBadge.className = "pnl-badge loss";
    } else {
        oodBadge.textContent = "In-Distribution";
        oodBadge.className = "pnl-badge win";
    }
    document.getElementById('res-ood-p').textContent = report.ood_p_value.toFixed(5);

    // Outcome Percentiles
    const perc = report.percentiles;
    document.getElementById('res-p90').textContent = `${perc.P90.toFixed(1)}%`;
    document.getElementById('res-p75').textContent = `${perc.P75.toFixed(1)}%`;
    document.getElementById('res-p50').textContent = `${perc.P50_median.toFixed(1)}%`;
    document.getElementById('res-p25').textContent = `${perc.P25.toFixed(1)}%`;
    document.getElementById('res-p10').textContent = `${perc.P10.toFixed(1)}%`;

    // Percentile bars use a literal 0-100% PnL scale so a 29% value is not drawn as a full bar.
    const pctWidth = (value) => `${Math.min(100, Math.max(0, Math.abs(Number(value) || 0)))}%`;
    document.getElementById('pb-p90').style.width = pctWidth(perc.P90);
    document.getElementById('pb-p75').style.width = pctWidth(perc.P75);
    document.getElementById('pb-p50').style.width = pctWidth(perc.P50_median);
    document.getElementById('pb-p25').style.width = pctWidth(perc.P25);
    document.getElementById('pb-p10').style.width = pctWidth(perc.P10);

    // Populate Analogs table
    const tbody = document.getElementById('analogs-table-body');
    tbody.innerHTML = '';

    report.analogs.forEach(item => {
        const tr = document.createElement('tr');
        const pnlClass = item.profit_pct > 0 ? 'win' : 'loss';

        tr.innerHTML = `
                    <td class="mono-td" style="font-weight: 600;">${item.symbol}</td>
                    <td class="mono-td">${(item.fundingRate * 100).toFixed(3)}%</td>
                    <td class="mono-td">$${(item.marketCap / 1000000).toFixed(1)}M</td>
                    <td class="mono-td">${Math.round(item.age_days)}d ago</td>
                    <td class="mono-td">${item.decay_weight.toFixed(3)}</td>
                    <td class="mono-td">${(item.similarity * 100).toFixed(2)}%</td>
                    <td><span class="pnl-badge ${pnlClass}">${item.profit_pct >= 0 ? '+' : ''}${item.profit_pct.toFixed(2)}%</span></td>
                `;
        tbody.appendChild(tr);
    });

    const quality = report.data_quality || {};
    const distance = report.distance_summary || {};
    document.getElementById('diag-clean-rows').textContent = `${quality.clean_joined_rows || 0} / ${formatCompact(quality.historical_feature_rows || 0)}`;
    document.getElementById('diag-ess').textContent = `${report.matched_k} / ${report.effective_sample_size.toFixed(1)}`;
    document.getElementById('diag-distance').textContent = `${distance.nearest.toFixed(3)} nearest`;
    document.getElementById('diag-ood').textContent = `${report.ood_empirical_percentile.toFixed(1)}%`;

    const riskList = document.getElementById('risk-list');
    const riskItems = [...(report.risk_flags || []), ...(report.validation_warnings || [])];
    riskList.innerHTML = '';
    const paidMeta = cachedEntry || getCachedReport(activeQuery || report.query || { symbol: report.query_symbol });
    if (paidMeta?.saved_at) {
        const div = document.createElement('div');
        div.className = 'risk-item';
        div.innerHTML = `<span style="color:var(--green);">Paid signal snapshot:</span> ${escapeHtml(signalSummary(paidMeta.signal || activeQuery || report.query || { symbol: report.query_symbol }))} <span style="color:var(--t3);">· bought ${escapeHtml(formatDateTime(paidMeta.saved_at))}</span>`;
        riskList.appendChild(div);
    }
    if (paidMeta?.previous_snapshot_for) {
        const div = document.createElement('div');
        div.className = 'risk-item';
        div.innerHTML = `<span style="color:#f59e0b;">Current live snapshot is different:</span> ${escapeHtml(signalSummary(paidMeta.previous_snapshot_for))} <span style="color:var(--t3);">- click Retrieve Analogs to buy and unlock this current signal.</span>`;
        riskList.appendChild(div);
    }
    riskItems.forEach(item => {
        const div = document.createElement('div');
        div.className = 'risk-item';
        div.textContent = item;
        riskList.appendChild(div);
    });
    // Payment status notice in report
    if (report.invoice && report.invoice.explorer_url && report.invoice.transaction_hash) {
        const div = document.createElement('div');
        div.className = 'risk-item';
        const payer = report.invoice.payer_address ? shortAddress(report.invoice.payer_address) : 'n/a';
        const amount = Number(report.invoice.amount_usdc || 0).toFixed(3);
        div.innerHTML = `<span style="color:var(--color-success);">✔ Arcscan batch tx confirmed:</span> <a href="${report.invoice.explorer_url}" target="_blank" rel="noreferrer" title="Settlement ID: ${escapeHtml(report.invoice.settlement_id || '')}" style="color: var(--color-primary);">${shortAddress(report.invoice.transaction_hash)}</a> <span style="color: var(--text-muted);">(${amount} USDC from ${payer})</span>`;
        riskList.prepend(div);
    } else if (report.invoice && report.invoice.settlement_id) {
        const div = document.createElement('div');
        div.className = 'risk-item';
        div.innerHTML = `<span style="color:#f59e0b;">⏳ Circle accepted payment</span> — Arcscan on-chain batch tx is pending. Report access is already unlocked. Settlement ID: <span style="font-family:var(--font-mono);font-size:0.78rem;">${shortAddress(report.invoice.settlement_id)}</span>`;
        riskList.prepend(div);
    }
    loadMetrics();
    if (report.invoice?.settlement_id && !report.invoice.explorer_url) {
        hydrateReportPayment(report);
    }
}

async function hydrateReportPayment(report) {
    try {
        const resp = await fetch(apiUrl(`/api/v1/payment/settlement/${report.invoice.settlement_id}`));
        if (!resp.ok) return;
        const data = await resp.json();
        if (!data.batch?.explorer_url || !data.batch?.batch_tx) return;
        report.invoice.gateway_status = data.settlement?.status || report.invoice.gateway_status;
        report.invoice.transaction_hash = data.batch.batch_tx;
        report.invoice.explorer_url = data.batch.explorer_url;
        saveCachedReport(report);
        renderReport(report);
    } catch (err) {
        console.warn('Could not hydrate Arc payment tx', err);
    }
}

// Init
walletButton.addEventListener('click', async (event) => {
    event.stopPropagation();
    if (!connectedWallet) {
        await connectWallet();
        return;
    }
    walletMenu.classList.toggle('open');
});
walletProfileBtn.addEventListener('click', openWalletProfile);
walletDisconnectBtn.addEventListener('click', disconnectWallet);
paywallClose.addEventListener('click', () => {
    hidePaywall();
    showToast('Payment panel closed. Select another signal or click Retrieve to reopen it.', 'info');
});

const copyBtn = document.getElementById('wallet-copy-btn');
if (copyBtn) {
    copyBtn.addEventListener('click', async () => {
        if (!connectedWallet) return;
        try {
            await navigator.clipboard.writeText(connectedWallet);
            const originalText = copyBtn.textContent;
            copyBtn.textContent = 'Copied!';
            setTimeout(() => {
                copyBtn.textContent = originalText;
            }, 2000);
        } catch (err) {
            console.error('Failed to copy address', err);
        }
    });
}

const wBtn = document.getElementById('wallet-withdraw-btn');
const wMenuBtn = document.getElementById('wallet-withdraw-menu-btn');
if (wBtn) wBtn.addEventListener('click', withdrawSellerGatewayFunds);
if (wMenuBtn) wMenuBtn.addEventListener('click', withdrawSellerGatewayFunds);
walletProfileClose.addEventListener('click', () => {
    walletProfileModal.classList.remove('open');
    walletProfileModal.setAttribute('aria-hidden', 'true');
});
walletProfileModal.addEventListener('click', (event) => {
    if (event.target === walletProfileModal) {
        walletProfileModal.classList.remove('open');
        walletProfileModal.setAttribute('aria-hidden', 'true');
    }
});
document.addEventListener('click', (event) => {
    if (!walletMenu.contains(event.target) && !walletButton.contains(event.target)) {
        walletMenu.classList.remove('open');
    }
});
if (window.ethereum?.on) {
    ethereum.on('accountsChanged', (accounts) => {
        setConnectedWallet(accounts && accounts[0] ? accounts[0] : null);
    });
    ethereum.on('chainChanged', () => {
        updateWalletUi();
    });
}
restoreWalletSession();
loadProviders();
loadLiveAnomalies();
loadAgentRecommendations();
loadMetrics();
loadHealthInfo();
setInterval(loadMetrics, 15000);
refreshBtn.addEventListener('click', () => {
    loadLiveAnomalies();
    loadAgentRecommendations();
});
