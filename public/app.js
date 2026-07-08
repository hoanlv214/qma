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
let currentInvoiceAmount = null;
let currentInvoiceTier = 'full';
let currentProviderId = urlParams.get('provider') || 'funding_memory';
let pricingConfig = { preview: null, full: null };
let quotedPrices = { preview: null, full: null };
let gatewayDepositConfig = { default_usdc: null, default_approve_usdc: null };
let providerCatalog = {};
let currentSellerAddress = null;
let currentAccessToken = null;
let activeQuery = null;
let hasUnlockedReport = false;
let paymentSuccessReady = false;
let connectedWallet = null;
let gatewayContractAddress = null;
let sellerWalletAddress = null;
let arcGatewayBaseUrl = '';
let paymentActivityPage = 1;
let paymentActivityTotalPages = 1;
let payerBreakdownPage = 1;
let payerBreakdownTotalPages = 1;
let lastPlatformPaymentKey = null;
let platformTablesLoaded = false;
let profilePaymentsPage = 1;
let profilePaymentsTotalPages = 1;
let activeProfileWallet = null;
let nextInvoiceBuyerType = 'human';
let currentInvoiceBuyerType = 'human';
let agentRunTraceLines = [];
let liveFeedRefreshInFlight = false;
let agentRecommendationsInFlight = false;
const WITHDRAW_FEE_RESERVE_USDC = 0.0035;
const PAYMENT_ACTIVITY_PAGE_SIZE = 10;
const PAYER_BREAKDOWN_PAGE_SIZE = 10;
const PROFILE_PAYMENTS_PAGE_SIZE = 10;
const LIVE_FEED_REFRESH_MS = 30000;
const API_BASE_URL = String(window.QMA_API_BASE_URL || '').replace(/\/$/, '');

function apiUrl(path) {
    return `${API_BASE_URL}${path}`;
}

function apiErrorMessage(data, fallback = 'Request failed') {
    const detail = data?.detail ?? data?.error ?? data?.message;
    if (Array.isArray(detail)) {
        return detail.map((item) => item?.msg || item?.message || JSON.stringify(item)).join('; ');
    }
    if (detail && typeof detail === 'object') {
        return detail.msg || detail.message || JSON.stringify(detail);
    }
    return detail || fallback;
}

function walletTokenCacheKey(account) {
    return `qma_wallet_profile_token_${String(account || '').toLowerCase()}`;
}

function clearWalletProfileSession(account) {
    if (!account) return;
    sessionStorage.removeItem(walletTokenCacheKey(account));
}

function getCachedWalletProfileToken(account) {
    if (!account) return '';
    const raw = sessionStorage.getItem(walletTokenCacheKey(account));
    if (!raw) return '';
    try {
        const cached = JSON.parse(raw);
        if (cached?.token && Number(cached.expiresAt || 0) > Date.now() + 15_000) {
            return cached.token;
        }
    } catch {
        // Older builds used raw token strings. Drop them so expired tokens never fail silently.
    }
    clearWalletProfileSession(account);
    return '';
}

function walletPrivateHeaders(token) {
    return token ? { 'X-QMA-Wallet-Token': token } : {};
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

async function requestWalletProfileSession(account, options = {}) {
    if (!account) return '';
    const cached = getCachedWalletProfileToken(account);
    if (cached) return cached;
    const provider = await getWalletProvider();
    if (!provider?.request) {
        throw new Error('Connect the wallet owner to unlock private report snapshots.');
    }
    const accounts = await provider.request({ method: 'eth_accounts' });
    const active = accounts && accounts[0] ? String(accounts[0]) : '';
    if (active.toLowerCase() !== String(account).toLowerCase()) {
        if (options.silent) return '';
        throw new Error('Connected wallet does not match this profile.');
    }
    const issuedAt = Math.floor(Date.now() / 1000);
    const nonce = `${issuedAt}-${Math.random().toString(36).slice(2)}`;
    const signature = await provider.request({
        method: 'personal_sign',
        params: [walletProfileMessage(account, nonce, issuedAt), active],
    });
    const resp = await fetch(apiUrl(`/api/v1/wallets/${account.toLowerCase()}/session`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nonce, issued_at: issuedAt, signature }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
        throw new Error(apiErrorMessage(data, 'Could not unlock private profile.'));
    }
    const token = data.wallet_token || '';
    if (token) {
        sessionStorage.setItem(walletTokenCacheKey(account), JSON.stringify({
            token,
            expiresAt: Date.now() + Math.max(30, Number(data.expires_in || 3600)) * 1000,
        }));
    }
    return token;
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

const WALLET_REQUEST_TIMEOUT_MS = 45000;
let walletRequestInFlight = null;

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function walletErrorCode(err) {
    return err?.code ?? err?.data?.code ?? err?.error?.code;
}

function isUnknownChainError(err) {
    const msg = String(err?.message || err || '').toLowerCase();
    const code = walletErrorCode(err);
    return code === 4902
        || msg.includes('unrecognized chain')
        || msg.includes('unknown chain')
        || msg.includes('not available in this wallet')
        || msg.includes('not added to this wallet');
}

function describeWalletError(err) {
    const msg = String(err?.message || err || '');
    const lower = msg.toLowerCase();
    const code = walletErrorCode(err);
    if (code === -32002 || lower.includes('already pending')) {
        return 'Wallet already has a pending request. Open wallet, finish or reject it, then retry.';
    }
    if (code === 4001 || lower.includes('user rejected') || lower.includes('rejected')) {
        return 'Wallet request was rejected.';
    }
    if (isUnknownChainError(err)) {
        return 'Arc Testnet is not available in this wallet yet. Approve the add-network request if it appears. If Rabby does not show one, add Arc Testnet manually using the network details in Funding Assistant, then retry.';
    }
    return msg || 'Wallet request failed.';
}

function normalizeWalletError(err) {
    const wrapped = new Error(describeWalletError(err));
    const code = walletErrorCode(err);
    if (code !== undefined) wrapped.code = code;
    return wrapped;
}

function withTimeout(promise, ms, label) {
    let timer = null;
    const timeout = new Promise((_, reject) => {
        timer = setTimeout(() => {
            reject(new Error(`${label} timed out. Open wallet and finish any pending request, then retry.`));
        }, ms);
    });
    return Promise.race([promise, timeout]).finally(() => {
        if (timer) clearTimeout(timer);
    });
}

async function walletRequest(args, label, timeoutMs = WALLET_REQUEST_TIMEOUT_MS) {
    const provider = await getWalletProvider();
    if (!provider?.request) {
        if (isMobileDevice()) {
            openMobileWalletModal();
        } else {
            _showDesktopInstallPrompt();
        }
        throw new Error('No wallet provider detected.');
    }
    if (walletRequestInFlight) {
        throw new Error('A wallet request is already in progress. Open MetaMask, finish it, then retry.');
    }
    walletRequestInFlight = withTimeout(provider.request(args), timeoutMs, label);
    try {
        return await walletRequestInFlight;
    } catch (err) {
        throw normalizeWalletError(err);
    } finally {
        walletRequestInFlight = null;
    }
}

async function directWalletRequest(provider, args, label, timeoutMs = WALLET_REQUEST_TIMEOUT_MS) {
    try {
        return await withTimeout(provider.request(args), timeoutMs, label);
    } catch (err) {
        throw normalizeWalletError(err);
    }
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
const liveRefreshPill = document.getElementById('live-refresh-pill');
const agentPicksContainer = document.getElementById('agent-picks-container');
const agentRunBtn = document.getElementById('agent-run-btn');
const agentRunBudgetInput = document.getElementById('agent-run-budget');
const agentRunMaxPriceInput = document.getElementById('agent-run-max-price');
const agentRunTrace = document.getElementById('agent-run-trace');
const providerMarketplaceContainer = document.getElementById('provider-marketplace-container');
const providerSelect = document.getElementById('q-provider');
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
const paymentPrevBtn = document.getElementById('payment-prev-btn');
const paymentNextBtn = document.getElementById('payment-next-btn');
const paymentPageLabel = document.getElementById('payment-page-label');
const payerPrevBtn = document.getElementById('payer-prev-btn');
const payerNextBtn = document.getElementById('payer-next-btn');
const payerPageLabel = document.getElementById('payer-page-label');
const walletButton = document.getElementById('wallet-button');
const walletButtonLabel = document.getElementById('wallet-button-label');
const walletMenu = document.getElementById('wallet-menu');
const walletMenuAddress = document.getElementById('wallet-menu-address');
const walletProfileBtn = document.getElementById('wallet-profile-btn');
const walletQuickProfileBtn = document.getElementById('wallet-quick-profile-btn');
const walletAgentRunBtn = document.getElementById('wallet-agent-run-btn');
const walletFundArcBtn = document.getElementById('wallet-fund-arc-btn');
const walletDisconnectBtn = document.getElementById('wallet-disconnect-btn');
const walletProfileModal = document.getElementById('wallet-profile-modal');
const walletProfileClose = document.getElementById('wallet-profile-close');
const agentRunModal = document.getElementById('agent-run-modal');
const agentRunClose = document.getElementById('agent-run-close');
const agentRunDismiss = document.getElementById('agent-run-dismiss');
const fundArcModal = document.getElementById('fund-arc-modal');
const fundArcClose = document.getElementById('fund-arc-close');
const fundArcDismiss = document.getElementById('fund-arc-dismiss');
const paywallFundingAssistantBtn = document.getElementById('paywall-funding-assistant-btn');
const fundWalletStatus = document.getElementById('fund-wallet-status');
const fundProviderStatus = document.getElementById('fund-provider-status');
const fundChainStatus = document.getElementById('fund-chain-status');
const fundArcStatus = document.getElementById('fund-arc-status');
const fundWalletUsdc = document.getElementById('fund-wallet-usdc');
const fundGatewayBalance = document.getElementById('fund-gateway-balance');
const fundRequiredAmount = document.getElementById('fund-required-amount');
const fundReadinessStatus = document.getElementById('fund-readiness-status');
const fundNextStep = document.getElementById('fund-next-step');
const fundPrimaryAction = document.getElementById('fund-primary-action');
const walletProfileAddress = document.getElementById('wallet-profile-address');
const profileGatewayBalance = document.getElementById('profile-gateway-balance');
const profileChainBalance = document.getElementById('profile-chain-balance');
const profilePayments = document.getElementById('profile-payments');
const profileSpent = document.getElementById('profile-spent');
const profileTokenList = document.getElementById('profile-token-list');
const profilePaymentsBody = document.getElementById('profile-payments-body');
const profileEventsBody = document.getElementById('profile-events-body');
const profilePaymentsPrevBtn = document.getElementById('profile-payments-prev-btn');
const profilePaymentsNextBtn = document.getElementById('profile-payments-next-btn');
const profilePaymentsPageLabel = document.getElementById('profile-payments-page-label');
const profilePageLink = document.getElementById('profile-page-link');
const actionModal = document.getElementById('action-modal');
const actionModalTitle = document.getElementById('action-modal-title');
const actionModalSubtitle = document.getElementById('action-modal-subtitle');
const actionModalBody = document.getElementById('action-modal-body');
const actionModalClose = document.getElementById('action-modal-close');
const actionModalCancel = document.getElementById('action-modal-cancel');
const actionModalConfirm = document.getElementById('action-modal-confirm');
const viewModeButtons = document.querySelectorAll('[data-view-mode]');

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// ─────────────────────────────────────────────────────────────
// MOBILE WALLET DETECTION & ONBOARDING
// ─────────────────────────────────────────────────────────────

/**
 * Returns true when running on a mobile/tablet UA.
 */
function isMobileDevice() {
    return /Android|iPhone|iPad|iPod|Opera Mini|IEMobile|WPDesktop/i.test(navigator.userAgent);
}

/**
 * Detect all injected EIP-1193 providers.
 * Returns an array of { id, label, icon } describing each detected wallet.
 */
function detectInjectedProviders() {
    const found = [];
    const eth = window.ethereum;
    if (!eth) return found;

    // Some wallets expose an array of providers via window.ethereum.providers
    const providerList = Array.isArray(eth.providers) ? eth.providers : [eth];

    for (const p of providerList) {
        if (p.isRabby)                         found.push({ id: 'rabby',    label: 'Rabby', icon: '🐰' });
        else if (p.isOKExWallet || p.isOKX)    found.push({ id: 'okx',      label: 'OKX Wallet', icon: '⬡' });
        else if (p.isCoinbaseWallet)           found.push({ id: 'coinbase', label: 'Coinbase Wallet', icon: '🔵' });
        else if (p.isMetaMask)                 found.push({ id: 'metamask', label: 'MetaMask', icon: '🦊' });
        else if (p.isPhantom && p.ethereum)    found.push({ id: 'phantom',  label: 'Phantom', icon: '👻' });
        else if (p.isTrust)                    found.push({ id: 'trust',    label: 'Trust Wallet', icon: '🛡️' });
    }
    // Deduplicate by id
    return [...new Map(found.map(x => [x.id, x])).values()];
}

function getInjectedProviderLabel(provider, fallbackLabel = 'Injected Wallet') {
    if (provider?.isRabby) return 'Rabby';
    if (provider?.isOKExWallet || provider?.isOKX) return 'OKX Wallet';
    if (provider?.isCoinbaseWallet) return 'Coinbase Wallet';
    if (provider?.isMetaMask) return 'MetaMask';
    if (provider?.isTrust) return 'Trust Wallet';
    return fallbackLabel;
}

function getInjectedProviderCandidates() {
    const providers = [];
    const push = (provider, fallbackLabel = 'Injected Wallet') => {
        if (!provider?.request || providers.some((entry) => entry.provider === provider)) return;
        providers.push({ provider, label: getInjectedProviderLabel(provider, fallbackLabel) });
    };

    const eth = window.ethereum;
    push(window.ethereum);
    push(window.rabby, 'Rabby');
    push(window.okxwallet, 'OKX Wallet');
    if (Array.isArray(eth?.providers)) {
        eth.providers.forEach((provider) => push(provider));
    }
    return providers;
}

async function getWalletProvider() {
    const candidates = getInjectedProviderCandidates();
    if (!candidates.length) return null;
    if (!connectedWallet) return candidates[0].provider;

    for (const entry of candidates) {
        try {
            const accounts = await withTimeout(
                entry.provider.request({ method: 'eth_accounts' }),
                3000,
                `${entry.label} account lookup`
            );
            if ((accounts || []).some((account) => sameAddress(account, connectedWallet))) {
                return entry.provider;
            }
        } catch (err) {
            console.warn(`${entry.label} account lookup failed`, err);
        }
    }
    return candidates[0].provider;
}

function getWalletProviderLabel(provider) {
    const entry = getInjectedProviderCandidates().find((candidate) => candidate.provider === provider);
    return entry?.label || 'Injected Wallet';
}

/**
 * Build a WalletConnect-style deeplink URI for common mobile wallets.
 * We use a simple `dapp` deeplink that opens the wallet's in-app browser
 * pointing to this page — the wallet then injects window.ethereum.
 */
function buildMobileDeeplink(walletId) {
    const pageUrl = encodeURIComponent(window.location.href);
    const map = {
        metamask: `https://metamask.app.link/dapp/${window.location.host}${window.location.pathname}${window.location.search}`,
        okx:      `okx://wallet/dapp/url?dappUrl=${pageUrl}`,
        coinbase:  `https://go.cb-w.com/dapp?cb_url=${pageUrl}`,
        trust:    `https://link.trustwallet.com/open_url?coin_id=60&url=${pageUrl}`,
        phantom:  `https://phantom.app/ul/browse/${pageUrl}?ref=${pageUrl}`,
    };
    return map[walletId] || null;
}

// ─── QR Code (pure-JS, no CDN required) ──────────────────────
// Minimal QR encoder using qrcode-generator (inline-loaded lazily)
let _qrScriptLoaded = false;
let _qrScriptCallbacks = [];

function loadQrScript(cb) {
    if (typeof qrcode !== 'undefined') { cb(); return; }
    if (_qrScriptLoaded) { _qrScriptCallbacks.push(cb); return; }
    _qrScriptLoaded = true;
    _qrScriptCallbacks.push(cb);
    const s = document.createElement('script');
    s.src = 'https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js';
    s.onload = () => { _qrScriptCallbacks.forEach(fn => fn()); _qrScriptCallbacks = []; };
    document.head.appendChild(s);
}

/**
 * Render a QR code SVG string for the given text.
 * Falls back to a simple bordered container if library fails.
 */
function renderQrSvg(container, text) {
    container.innerHTML = '';
    loadQrScript(() => {
        try {
            // eslint-disable-next-line no-undef
            new QRCode(container, {
                text,
                width: 192,
                height: 192,
                colorDark: '#e8eaf0',
                colorLight: '#0f1220',
                correctLevel: QRCode.CorrectLevel.M
            });
        } catch (e) {
            container.innerHTML = `<div style="width:192px;height:192px;display:flex;align-items:center;justify-content:center;border:1px dashed rgba(255,255,255,.15);border-radius:8px;font-size:.7rem;color:var(--t3);text-align:center;padding:12px;">QR unavailable<br>${escapeHtml(text.slice(0, 40))}...</div>`;
        }
    });
}

// ─── Mobile Wallet Modal ──────────────────────────────────────

let _mobileModalEl = null;

function getMobileModal() {
    if (_mobileModalEl) return _mobileModalEl;
    const el = document.createElement('div');
    el.id = 'mobile-wallet-modal';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-modal', 'true');
    el.setAttribute('aria-label', 'Connect wallet on mobile');
    el.style.cssText = [
        'position:fixed', 'inset:0', 'z-index:2000',
        'display:none', 'align-items:flex-end', 'justify-content:center',
        'background:rgba(3,5,12,.78)', 'backdrop-filter:blur(14px)',
        'padding:0'
    ].join(';');

    el.innerHTML = `
<div id="mwm-sheet" style="
    width:min(480px,100%);
    max-height:92dvh;
    overflow-y:auto;
    background:var(--bg-2);
    border:1px solid var(--bdr-md);
    border-bottom:none;
    border-radius:16px 16px 0 0;
    padding:24px 20px 32px;
    display:flex;
    flex-direction:column;
    gap:0;
">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;">
        <div>
            <div style="font-family:var(--mono);font-size:.62rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--t3);margin-bottom:6px;">Connect Wallet</div>
            <div style="font-size:1rem;font-weight:700;color:var(--t1);">Open in your wallet browser</div>
        </div>
        <button id="mwm-close" type="button" style="
            width:30px;height:30px;border:1px solid var(--bdr);border-radius:6px;
            background:transparent;color:var(--t3);cursor:pointer;font-size:1.1rem;
            display:flex;align-items:center;justify-content:center;flex-shrink:0;
        " aria-label="Close">&times;</button>
    </div>

    <!-- Trust note -->
    <div id="mwm-trust" style="
        border-left:2px solid var(--accent);
        background:var(--accent-dim);
        border-radius:0 6px 6px 0;
        padding:10px 13px;
        margin-bottom:18px;
        font-size:.78rem;
        color:var(--t2);
        line-height:1.55;
    ">
        🔒 Connecting only shares your <strong style="color:var(--t1)">public address</strong>.
        QMA cannot move funds unless you explicitly approve a transaction in your wallet.
    </div>

    <!-- Deeplink buttons (mobile-only) -->
    <div id="mwm-deeplinks" style="display:flex;flex-direction:column;gap:8px;margin-bottom:20px;"></div>

    <!-- Separator -->
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:20px;">
        <div style="flex:1;height:1px;background:var(--bdr);"></div>
        <span style="font-size:.66rem;color:var(--t3);font-family:var(--mono);">OR SCAN WITH MOBILE WALLET</span>
        <div style="flex:1;height:1px;background:var(--bdr);"></div>
    </div>

    <!-- QR code section -->
    <div style="display:flex;flex-direction:column;align-items:center;gap:12px;margin-bottom:20px;">
        <div id="mwm-qr" style="
            background:var(--bg-1);
            border:1px solid var(--bdr-md);
            border-radius:10px;
            padding:16px;
            display:flex;align-items:center;justify-content:center;
            min-height:224px;
        "></div>
        <p style="font-size:.74rem;color:var(--t3);text-align:center;line-height:1.5;max-width:280px;">
            Scan with MetaMask, OKX, or any WalletConnect-compatible wallet to open this page inside the wallet browser.
        </p>
    </div>

    <!-- Copy link -->
    <button id="mwm-copy-link" type="button" style="
        display:flex;align-items:center;justify-content:center;gap:8px;
        width:100%;border:1px solid var(--bdr-md);border-radius:7px;
        background:transparent;color:var(--t2);cursor:pointer;
        padding:10px 14px;font-family:var(--sans);font-size:.84rem;font-weight:500;
        margin-bottom:12px;transition:background .14s,color .14s;
    ">
        <span id="mwm-copy-icon">📋</span> Copy page link
    </button>

    <!-- Get testnet USDC hint -->
    <a id="mwm-get-usdc" href="https://faucet.testnet.arc.network" target="_blank" rel="noreferrer" style="
        display:flex;align-items:center;justify-content:center;gap:8px;
        width:100%;border:1px solid rgba(34,211,160,.25);border-radius:7px;
        background:var(--green-dim);color:var(--green);cursor:pointer;
        padding:10px 14px;font-family:var(--sans);font-size:.84rem;font-weight:600;
        text-decoration:none;margin-bottom:20px;
    ">
        ⬡ Get Arc Testnet USDC
    </a>

    <!-- Source + security links -->
    <div style="display:flex;gap:16px;justify-content:center;flex-wrap:wrap;">
        <a href="https://github.com/hoanlv214/qma" target="_blank" rel="noreferrer"
            style="font-size:.72rem;color:var(--t3);text-decoration:none;font-family:var(--mono);">
            ⌥ Open source
        </a>
        <a href="https://github.com/hoanlv214/qma/blob/main/docs/API_SECURITY.md"
            target="_blank" rel="noreferrer"
            style="font-size:.72rem;color:var(--t3);text-decoration:none;font-family:var(--mono);">
            ⚿ Payment security model
        </a>
    </div>
</div>`;

    document.body.appendChild(el);
    _mobileModalEl = el;

    // Close on backdrop click
    el.addEventListener('click', (e) => {
        if (e.target === el) closeMobileWalletModal();
    });
    el.querySelector('#mwm-close').addEventListener('click', closeMobileWalletModal);

    // Copy link button
    el.querySelector('#mwm-copy-link').addEventListener('click', async () => {
        try {
            await navigator.clipboard.writeText(window.location.href);
            const btn = el.querySelector('#mwm-copy-link');
            const icon = el.querySelector('#mwm-copy-icon');
            icon.textContent = '✓';
            btn.style.color = 'var(--green)';
            btn.style.borderColor = 'rgba(34,211,160,.35)';
            setTimeout(() => {
                icon.textContent = '📋';
                btn.style.color = '';
                btn.style.borderColor = '';
            }, 2000);
        } catch (err) {
            // Clipboard API may be blocked; show URL instead
            prompt('Copy this URL to open in your wallet browser:', window.location.href);
        }
    });

    return el;
}

/**
 * Open the mobile wallet modal.
 * Renders deeplink buttons for common wallets and a QR code of the current URL.
 */
function openMobileWalletModal() {
    const modal = getMobileModal();
    const deeplinksEl = modal.querySelector('#mwm-deeplinks');
    const qrEl = modal.querySelector('#mwm-qr');

    // Build deeplink buttons
    const wallets = [
        { id: 'metamask', label: 'Open in MetaMask', icon: '🦊' },
        { id: 'okx',      label: 'Open in OKX Wallet', icon: '⬡' },
        { id: 'trust',    label: 'Open in Trust Wallet', icon: '🛡️' },
        { id: 'coinbase', label: 'Open in Coinbase Wallet', icon: '🔵' },
    ];

    deeplinksEl.innerHTML = wallets.map(w => {
        const url = buildMobileDeeplink(w.id);
        if (!url) return '';
        return `<a href="${escapeHtml(url)}" style="
            display:flex;align-items:center;gap:11px;
            border:1px solid var(--bdr-md);border-radius:8px;
            background:var(--bg-1);color:var(--t1);text-decoration:none;
            padding:11px 14px;font-size:.86rem;font-weight:500;
            font-family:var(--sans);transition:background .14s,border-color .14s;
        " onmouseover="this.style.background='rgba(255,255,255,.04)'" onmouseout="this.style.background='var(--bg-1)'">
            <span style="font-size:1.25rem;width:24px;text-align:center;">${w.icon}</span>
            ${escapeHtml(w.label)}
            <span style="margin-left:auto;font-size:.7rem;color:var(--t3);">→</span>
        </a>`;
    }).join('');

    // QR code of current page URL
    renderQrSvg(qrEl, window.location.href);

    modal.style.display = 'flex';
    // Slide-in: trigger reflow then animate sheet
    const sheet = modal.querySelector('#mwm-sheet');
    sheet.style.transform = 'translateY(100%)';
    sheet.style.transition = 'none';
    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            sheet.style.transition = 'transform .28s cubic-bezier(.32,1,.56,1)';
            sheet.style.transform = 'translateY(0)';
        });
    });

    // Trap focus: focus close button
    setTimeout(() => modal.querySelector('#mwm-close')?.focus(), 50);
}

function closeMobileWalletModal() {
    if (!_mobileModalEl) return;
    const sheet = _mobileModalEl.querySelector('#mwm-sheet');
    sheet.style.transition = 'transform .22s ease-in';
    sheet.style.transform = 'translateY(100%)';
    setTimeout(() => {
        if (_mobileModalEl) _mobileModalEl.style.display = 'none';
    }, 240);
}

/**
 * Main entry point for the "Connect Wallet" button.
 * On desktop with injected provider → call connectWallet().
 * On mobile without provider → show mobile onboarding modal.
 * On desktop without provider → show a minimal install prompt.
 */
function handleConnectWalletClick() {
    if (window.ethereum) {
        // Provider present — normal flow
        connectWallet();
        return;
    }

    if (isMobileDevice()) {
        openMobileWalletModal();
        return;
    }

    // Desktop, no extension
    _showDesktopInstallPrompt();
}

function _showDesktopInstallPrompt() {
    const existing = document.getElementById('desktop-wallet-prompt');
    if (existing) { existing.remove(); }

    const div = document.createElement('div');
    div.id = 'desktop-wallet-prompt';
    div.setAttribute('role', 'alertdialog');
    div.setAttribute('aria-modal', 'true');
    div.style.cssText = [
        'position:fixed', 'inset:0', 'z-index:2000',
        'display:flex', 'align-items:center', 'justify-content:center',
        'background:rgba(3,5,12,.78)', 'backdrop-filter:blur(14px)', 'padding:20px'
    ].join(';');
    div.innerHTML = `
<div style="
    width:min(440px,100%);
    background:var(--bg-2);
    border:1px solid var(--bdr-md);
    border-radius:12px;
    padding:24px;
">
    <div style="font-size:.96rem;font-weight:700;color:var(--t1);margin-bottom:8px;">No wallet detected</div>
    <div style="font-size:.82rem;color:var(--t2);line-height:1.6;margin-bottom:18px;">
        Install a browser wallet extension to connect, or open this page in your wallet's built-in browser on mobile.
    </div>

    <!-- Trust note -->
    <div style="
        border-left:2px solid var(--accent);background:var(--accent-dim);
        border-radius:0 6px 6px 0;padding:9px 12px;margin-bottom:18px;
        font-size:.76rem;color:var(--t2);line-height:1.55;
    ">
        🔒 Connecting only shares your <strong style="color:var(--t1)">public address</strong>.
        QMA cannot move funds unless you explicitly approve a transaction.
    </div>

    <div style="display:flex;flex-direction:column;gap:8px;margin-bottom:18px;">
        <a href="https://metamask.io/download/" target="_blank" rel="noreferrer" style="
            display:flex;align-items:center;gap:10px;
            border:1px solid var(--bdr-md);border-radius:7px;background:var(--bg-1);
            color:var(--t1);text-decoration:none;padding:10px 13px;
            font-size:.84rem;font-weight:500;font-family:var(--sans);
        ">🦊 Install MetaMask</a>
        <a href="https://www.okx.com/web3" target="_blank" rel="noreferrer" style="
            display:flex;align-items:center;gap:10px;
            border:1px solid var(--bdr-md);border-radius:7px;background:var(--bg-1);
            color:var(--t1);text-decoration:none;padding:10px 13px;
            font-size:.84rem;font-weight:500;font-family:var(--sans);
        ">⬡ Install OKX Wallet</a>
    </div>

    <div style="display:flex;gap:16px;justify-content:center;flex-wrap:wrap;margin-bottom:18px;">
        <a href="https://github.com/hoanlv214/qma" target="_blank" rel="noreferrer"
            style="font-size:.72rem;color:var(--t3);text-decoration:none;font-family:var(--mono);">
            ⌥ Open source
        </a>
        <a href="https://github.com/hoanlv214/qma/blob/main/docs/API_SECURITY.md"
            target="_blank" rel="noreferrer"
            style="font-size:.72rem;color:var(--t3);text-decoration:none;font-family:var(--mono);">
            ⚿ Payment security model
        </a>
    </div>

    <button id="dwp-close" type="button" style="
        width:100%;border:1px solid var(--bdr);border-radius:7px;
        background:transparent;color:var(--t3);cursor:pointer;
        padding:9px;font-family:var(--sans);font-size:.82rem;
    ">Dismiss</button>
</div>`;
    document.body.appendChild(div);
    div.querySelector('#dwp-close').addEventListener('click', () => div.remove());
    div.addEventListener('click', (e) => { if (e.target === div) div.remove(); });
}

// ─── Trust layer injected inside the payment paywall ─────────
/**
 * Insert (or update) the security notice + source links inside the paywall element.
 * Called once when the paywall element is first shown.
 */
function ensurePaywallTrustLayer() {
    const paywall = document.getElementById('paywall-element');
    const paywallMain = paywall?.querySelector('.paywall-main');
    if (!paywallMain || paywallMain.querySelector('#paywall-trust-layer')) return;

    const trust = document.createElement('div');
    trust.id = 'paywall-trust-layer';
    trust.className = 'paywall-trust-layer';
    trust.innerHTML = `
<span class="paywall-trust-title">Wallet connection only exposes your public address.</span>
<span class="paywall-trust-links">
    <a href="https://github.com/hoanlv214/qma/blob/main/docs/API_SECURITY.md" target="_blank" rel="noreferrer">Learn more →</a>
</span>`;

    const snapshotNote = paywallMain.querySelector('.paywall-snapshot-note');
    if (snapshotNote) {
        snapshotNote.insertAdjacentElement('afterend', trust);
    } else {
        paywallMain.appendChild(trust);
    }
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

function shouldShortenPaymentValue(value) {
    const text = String(value || '');
    return /^0x[a-fA-F0-9]{10,}$/.test(text) || (/^\S{29,}$/.test(text));
}

function setPaymentDetailValue(id, value, fallback = '—') {
    const el = document.getElementById(id);
    if (!el) return;
    const raw = value == null || value === '' ? fallback : String(value);
    const hasFull = raw !== fallback && raw !== 'n/a';
    const display = hasFull && shouldShortenPaymentValue(raw) ? shortAddress(raw) : raw;
    el.textContent = display;
    el.title = hasFull ? raw : '';
    if (hasFull) {
        el.dataset.fullValue = raw;
        el.dataset.hasFull = 'true';
    } else {
        delete el.dataset.fullValue;
        delete el.dataset.hasFull;
    }
}

function setupPaywallCopyButtons() {
    if (!paywallElement) return;
    paywallElement.addEventListener('click', async (event) => {
        const btn = event.target.closest('.paywall-copy-btn');
        if (!btn) return;
        const target = document.getElementById(btn.dataset.copyFor);
        if (!target) return;
        const value = target.dataset.fullValue || target.getAttribute('href') || target.textContent.trim();
        if (!value || value === '—' || value === 'n/a') return;
        try {
            await navigator.clipboard.writeText(value);
            btn.classList.add('copied');
            const previous = btn.textContent;
            btn.textContent = 'Copied';
            setTimeout(() => {
                btn.classList.remove('copied');
                btn.textContent = previous;
            }, 1400);
        } catch (err) {
            console.error('Failed to copy payment detail', err);
        }
    });
}

function setPaymentStepState(stepId, state, label) {
    const row = document.getElementById(stepId);
    if (!row) return;
    row.classList.remove('is-waiting', 'is-active', 'is-pending', 'is-completed', 'is-failed');
    row.classList.add(`is-${state}`);
    const badge = row.querySelector('.pf-badge');
    if (badge) {
        badge.className = `pf-badge is-${state}`;
        badge.textContent = label;
    }
}

function updatePaymentTimeline(stage = 'created', cancelMessage = '') {
    if (stage === 'completed') {
        setPaymentStepState('pf-buyer-wallet', 'completed', 'Connected');
        setPaymentStepState('pf-buyer-gateway', 'completed', 'Confirmed');
        setPaymentStepState('pf-settlement', 'completed', 'Completed');
        setPaymentStepState('pf-report-unlocked', 'completed', 'Completed');
        const unlock = document.getElementById('pf-unlock-status');
        if (unlock) unlock.textContent = 'Report is unlocked and ready.';
        return;
    }
    if (stage === 'received') {
        setPaymentStepState('pf-buyer-wallet', 'completed', 'Connected');
        setPaymentStepState('pf-buyer-gateway', 'completed', 'Confirmed');
        setPaymentStepState('pf-settlement', 'active', 'Pending');
        setPaymentStepState('pf-report-unlocked', 'waiting', 'Waiting');
        const unlock = document.getElementById('pf-unlock-status');
        if (unlock) unlock.textContent = 'Unlocking after settlement verification.';
        return;
    }
    if (stage === 'checking') {
        setPaymentStepState('pf-buyer-wallet', connectedWallet ? 'completed' : 'active', connectedWallet ? 'Connected' : 'Waiting');
        setPaymentStepState('pf-buyer-gateway', 'active', 'Pending');
        setPaymentStepState('pf-settlement', 'waiting', 'Waiting');
        setPaymentStepState('pf-report-unlocked', 'waiting', 'Waiting');
        return;
    }
    if (stage === 'cancelled') {
        setPaymentStepState('pf-buyer-wallet', connectedWallet ? 'completed' : 'waiting', connectedWallet ? 'Connected' : 'Waiting');
        setPaymentStepState('pf-buyer-gateway', 'failed', 'Failed');
        setPaymentStepState('pf-settlement', 'waiting', 'Waiting');
        setPaymentStepState('pf-report-unlocked', 'waiting', 'Waiting');
        const unlock = document.getElementById('pf-unlock-status');
        if (unlock) unlock.textContent = cancelMessage || 'Payment cancelled. No report unlocked.';
        return;
    }
    setPaymentStepState('pf-buyer-wallet', connectedWallet ? 'completed' : 'active', connectedWallet ? 'Connected' : 'Waiting');
    setPaymentStepState('pf-buyer-gateway', connectedWallet ? 'active' : 'waiting', connectedWallet ? 'Pending' : 'Waiting');
    setPaymentStepState('pf-settlement', 'waiting', 'Waiting');
    setPaymentStepState('pf-report-unlocked', 'waiting', 'Waiting');
}

function resetPaywallSuccessState() {
    paymentSuccessReady = false;
    paywallElement?.classList.remove('payment-success');
}

function resetPaymentDetailPanel() {
    document.getElementById('inv-id-row')?.style.setProperty('display', 'none');
    setPaymentDetailValue('inv-id-display', null);
    setPaymentDetailValue('pf-settlement-id', null);
    setPaymentDetailValue('pf-gateway-contract', null);
    setPaymentDetailValue('pf-seller-wallet-addr', null);
    setPaymentDetailValue('pf-buyer-gateway-bal', null);
    setPaymentDetailValue('pf-seller-available', null);
    setPaymentDetailValue('pf-seller-pending', null);
    setPaymentDetailValue('pf-wallet-address', null);
    const arcscanRow = document.getElementById('pf-arcscan-tx');
    if (arcscanRow) arcscanRow.style.display = 'none';
}

function showPaymentUnlockingState() {
    paywallElement.style.display = 'flex';
    paywallElement.classList.add('payment-success');
    paywallTitle.textContent = 'Payment Confirmed';
    paywallDesc.textContent = 'Settlement accepted. Unlocking report...';
    document.getElementById('payment-flow-panel').style.display = 'block';
    const unlockStatus = document.getElementById('pf-unlock-status');
    if (unlockStatus) unlockStatus.textContent = 'QMA is loading your report.';
    payButton.disabled = true;
    payButton.innerHTML = `
                <div class="spinner" style="width: 16px; height: 16px;"></div>
                <span>Unlocking Report...</span>
            `;
}

function showPaymentSuccessState() {
    paymentSuccessReady = true;
    paywallElement.style.display = 'flex';
    paywallElement.classList.add('payment-success');
    paywallElement.classList.remove('compact-paywall');
    document.getElementById('payment-flow-panel').style.display = 'block';
    paywallTitle.textContent = 'Payment Confirmed';
    paywallDesc.textContent = 'Settlement complete. Your report is ready.';
    updatePaymentTimeline('completed');
    const unlockStatus = document.getElementById('pf-unlock-status');
    if (unlockStatus) unlockStatus.textContent = 'Report is unlocked and ready.';
    payButton.disabled = false;
    payButton.innerHTML = '<span>Open Report</span>';
}

function explorerTx(hash) {
    return `https://testnet.arcscan.app/tx/${hash}`;
}

function formatDateTime(timestamp) {
    if (!timestamp) return 'n/a';
    const ms = timestamp > 10_000_000_000 ? timestamp : timestamp * 1000;
    return new Date(ms).toLocaleString();
}

function formatTimeOnly(timestamp) {
    if (!timestamp) return 'n/a';
    const ms = timestamp > 10_000_000_000 ? timestamp : timestamp * 1000;
    return new Date(ms).toLocaleTimeString();
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

function requestActionConfirmation({
    title,
    subtitle,
    rows = [],
    warning = null,
    customHtml = '',
    confirmLabel = 'Continue',
    cancelLabel = 'Cancel',
    onOpen = null,
}) {
    return new Promise((resolve) => {
        actionModalTitle.textContent = title || 'Confirm Action';
        actionModalSubtitle.textContent = subtitle || 'Review before opening your wallet';
        actionModalBody.innerHTML = `
            ${renderActionRows(rows)}
            ${customHtml || ''}
            ${warning ? `<div class="action-warning">${escapeHtml(warning)}</div>` : ''}
        `;
        actionModalConfirm.textContent = confirmLabel;
        actionModalCancel.textContent = cancelLabel;
        actionModalConfirm.disabled = false;
        actionModal.classList.add('open');
        actionModal.setAttribute('aria-hidden', 'false');

        if (typeof onOpen === 'function') {
            onOpen({
                confirmButton: actionModalConfirm,
                cancelButton: actionModalCancel,
                body: actionModalBody,
            });
        }

        const cleanup = (value) => {
            actionModal.classList.remove('open');
            actionModal.setAttribute('aria-hidden', 'true');
            actionModalConfirm.disabled = false;
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
    const provider = await getWalletProvider();
    if (!provider?.request) throw new Error('No wallet provider detected.');
    const switchRequest = {
        method: 'wallet_switchEthereumChain',
        params: [{ chainId: ARC_TESTNET_HEX }]
    };

    try {
        const current = await directWalletRequest(provider, { method: 'eth_chainId' }, 'Arc network check', 8000);
        if (normalizeChainId(current) === ARC_TESTNET_HEX) return;
    } catch (err) {
        console.warn('Could not read current chain before Arc switch; trying switch/add anyway.', err);
    }

    try {
        await directWalletRequest(provider, switchRequest, 'Arc network switch');
    } catch (err) {
        if (isUnknownChainError(err)) {
            await directWalletRequest(
                provider,
                {
                    method: 'wallet_addEthereumChain',
                    params: [ARC_TESTNET]
                },
                'Add Arc Testnet'
            );
            // Rabby can resolve addEthereumChain before its internal chain registry is ready.
            // Give the extension a short moment, then retry the switch once.
            await sleep(700);
            try {
                await directWalletRequest(provider, switchRequest, 'Arc network switch');
                return;
            } catch (retryErr) {
                if (isUnknownChainError(retryErr)) {
                    await sleep(700);
                    try {
                        const current = await directWalletRequest(provider, { method: 'eth_chainId' }, 'Arc network recheck', 8000);
                        if (normalizeChainId(current) === ARC_TESTNET_HEX) return;
                    } catch (checkErr) {
                        console.warn('Could not recheck Arc chain after add-network attempt.', checkErr);
                    }
                    await directWalletRequest(provider, switchRequest, 'Arc network switch retry');
                    return;
                }
                throw retryErr;
            }
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
    if (String(tier || '').toLowerCase() === 'legacy') return 'Legacy Report';
    const normalized = normalizeTier(tier);
    if (isBasicView()) {
        return normalized === 'preview' ? 'Summary' : 'Full Report';
    }
    return normalized === 'preview' ? 'Preview' : 'Full Report';
}

function tierButtonLabel(tier = 'full') {
    const normalized = normalizeTier(tier);
    if (isBasicView()) {
        return normalized === 'preview' ? 'Summary' : 'Full Report';
    }
    return normalized === 'preview' ? 'Preview' : 'Full';
}

function isBasicView() {
    return document.body.classList.contains('basic-view');
}

function tierPrice(tier = 'full') {
    const normalized = normalizeTier(tier);
    if (quotedPrices[normalized] != null && Number.isFinite(Number(quotedPrices[normalized]))) {
        return Number(quotedPrices[normalized]);
    }
    const providerPrice = providerCatalog[currentProviderId]?.pricing?.[normalized]?.amount_usdc;
    if (providerPrice != null && Number.isFinite(Number(providerPrice))) {
        return Number(providerPrice);
    }
    const configPrice = pricingConfig[normalized];
    if (configPrice != null && Number.isFinite(Number(configPrice))) {
        return Number(configPrice);
    }
    return null;
}

let quoteRefreshTimer = null;

async function refreshQuotedPrices(query = null) {
    const payload = query || activeQuery || resolveActiveQuery();
    if (!payload?.symbol) return;
    try {
        const tiers = ['preview', 'full'];
        const results = await Promise.all(tiers.map(async (tier) => {
            const resp = await fetch(apiUrl('/api/v1/payment/quote'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ...payload,
                    provider_id: currentProviderId,
                    tier,
                }),
            });
            if (!resp.ok) return null;
            const data = await resp.json();
            return [tier, Number(data.amount_usdc)];
        }));
        results.forEach((entry) => {
            if (entry && Number.isFinite(entry[1])) {
                quotedPrices[entry[0]] = entry[1];
            }
        });
        updateTierPriceLabels();
        updateBasicSignalCard(payload);
    } catch (err) {
        console.warn('Price quote unavailable', err);
    }
}

function scheduleQuotedPriceRefresh() {
    clearTimeout(quoteRefreshTimer);
    quoteRefreshTimer = setTimeout(() => {
        refreshQuotedPrices();
        updateBasicSignalCard();
    }, 300);
}

function formatTierPrice(tier = 'full') {
    const price = tierPrice(tier);
    return price != null ? `${price.toFixed(3)} USDC` : '— USDC';
}

function updateTierPriceLabels() {
    document.querySelectorAll('.tier-btn[data-tier="preview"] span').forEach((el) => {
        const price = tierPrice('preview');
        if (price != null) el.textContent = `${tierButtonLabel('preview')} ${price.toFixed(3)}`;
    });
    document.querySelectorAll('.tier-btn[data-tier="full"] span').forEach((el) => {
        const price = tierPrice('full');
        if (price != null) el.textContent = `${tierButtonLabel('full')} ${price.toFixed(3)}`;
    });
}

function formatFundingPlain(rate, { includeNumbers = true } = {}) {
    if (!Number.isFinite(rate)) return 'funding data unavailable';
    const pct = Math.abs(rate * 100);
    const signed = rate < 0 ? 'negative' : 'positive';
    if (!includeNumbers) {
        if (pct >= 0.5) return `very ${signed} funding`;
        if (pct >= 0.1) return `notable ${signed} funding`;
        return `${signed} funding`;
    }
    if (pct >= 0.5) return `very ${signed} funding (${pct.toFixed(2)}% per period)`;
    if (pct >= 0.1) return `notable ${signed} funding (${pct.toFixed(2)}% per period)`;
    return `${signed} funding (${pct.toFixed(2)}% per period)`;
}

function updateBasicSignalCard(source = null) {
    const symbolEl = document.getElementById('basic-signal-symbol');
    const leadEl = document.getElementById('basic-signal-lead');
    const metaEl = document.getElementById('basic-signal-meta');
    if (!symbolEl || !leadEl || !metaEl) return;

    let payload;
    try {
        payload = normalizeSignalPayload(source || activeQuery || resolveActiveQuery());
    } catch (err) {
        return;
    }

    const symbol = payload.symbol || '—';
    const fundingText = formatFundingPlain(payload.fundingRate, { includeNumbers: false });
    const previewPrice = tierPrice('preview');
    const fullPrice = tierPrice('full');

    symbolEl.textContent = symbol;
    leadEl.textContent = `${symbol} currently shows ${fundingText}. QMA compares this snapshot with similar historical funding events.`;
    const priceHint = previewPrice != null && fullPrice != null
        ? `Summary from ${previewPrice.toFixed(3)} USDC. Full report from ${fullPrice.toFixed(3)} USDC.`
        : 'Pay once per exact snapshot. No subscription.';
    metaEl.textContent = priceHint;
}

function updatePaywallCopyForViewMode() {
    if (!paywallDesc || paywallElement.style.display === 'none') return;
    if (isBasicView()) {
        paywallDesc.textContent = 'Unlock a plain-language historical comparison for this token. QMA shows how similar past funding setups usually played out.';
    } else {
        paywallDesc.textContent = 'Unlock a regime analog report for this token. QMA matches the live vector against historical funding events in Mahalanobis space with Ledoit-Wolf covariance.';
    }
}

function resolveGatewayApproveDefault(walletStatus = null) {
    const fromWallet = walletStatus?.defaultApproveUsdc;
    if (fromWallet != null && fromWallet !== '' && Number.isFinite(Number(fromWallet))) {
        return Number(fromWallet);
    }
    if (gatewayDepositConfig.default_approve_usdc != null && Number.isFinite(Number(gatewayDepositConfig.default_approve_usdc))) {
        return Number(gatewayDepositConfig.default_approve_usdc);
    }
    return null;
}

function setViewMode(mode = 'basic') {
    const normalized = mode === 'advanced' ? 'advanced' : 'basic';
    document.body.classList.toggle('advanced-view', normalized === 'advanced');
    document.body.classList.toggle('basic-view', normalized !== 'advanced');
    if (normalized === 'advanced') {
        document.body.classList.remove('basic-show-fields');
        if (activeQuery) {
            syncFormFromSignal(activeQuery);
        }
    } else {
        document.body.classList.remove('basic-show-fields');
        const toggleBtn = document.getElementById('basic-toggle-fields-btn');
        if (toggleBtn) toggleBtn.textContent = 'Edit technical fields';
    }
    try {
        localStorage.setItem('qma_view_mode', normalized);
    } catch (err) {
        /* ignore */
    }
    viewModeButtons.forEach((button) => {
        const active = button.dataset.viewMode === normalized;
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    updateTierPriceLabels();
    updateBasicSignalCard();
    updatePaywallCopyForViewMode();
}

function reportConfidenceLabel({ isOod = false, matchedCount = 0, ess = 0 } = {}) {
    if (isOod) return 'Low';
    if (matchedCount >= 25 && ess >= 10) return 'High';
    if (matchedCount >= 8) return 'Medium';
    return 'Exploratory';
}

function updatePlainSummary(report, { preview = false } = {}) {
    const similarCount = Number(report.matched_k || report.top_analogs?.length || report.analogs?.length || 0);
    const ess = Number(report.effective_sample_size || 0);
    const winRate = Number((preview ? report.rough_win_rate : report.weighted_win_rate) || 0);
    const median = preview ? null : report.percentiles?.P50_median;
    const confidence = reportConfidenceLabel({ isOod: Boolean(report.is_ood), matchedCount: similarCount, ess });
    const symbol = report.query_symbol || report.query?.symbol || activeQuery?.symbol || 'this signal';
    const direction = winRate >= 60 ? 'mostly positive' : winRate >= 45 ? 'mixed' : 'weak or negative';
    const noveltyText = report.is_ood
        ? 'This setup looks more unusual than most historical matches, so treat the evidence carefully.'
        : 'This setup looks familiar enough to compare with past events.';
    const regimeName = report.regime_cluster || 'a similar market context';
    const medianText = median == null
        ? (preview ? 'Full report required' : 'n/a')
        : `${median >= 0 ? '+' : ''}${Number(median).toFixed(1)}%`;

    const summaryText = similarCount
        ? `${symbol} is being compared with ${similarCount} similar historical events in a ${regimeName} context. In those past cases, outcomes were ${direction}, with a ${winRate.toFixed(1)}% win rate. ${noveltyText}`
        : `${symbol} has been unlocked, but QMA could not find enough similar historical events yet. Use the technical report carefully.`;

    const setText = (id, value) => {
        const node = document.getElementById(id);
        if (node) node.textContent = value;
    };
    setText('plain-summary-text', summaryText);
    setText('summary-confidence', confidence);
    setText('summary-similar-count', preview ? `${similarCount} (summary)` : String(similarCount));
    setText('summary-win-rate', `${winRate.toFixed(1)}%`);
    setText('summary-median', medianText);
}

function walletCacheScope(account = connectedWallet) {
    const normalized = String(account || '').trim().toLowerCase();
    return normalized || null;
}

function signalCacheKey(source = {}, tier = 'full', providerId = currentProviderId || 'funding_memory', account = connectedWallet) {
    const payload = normalizeSignalPayload(source);
    const wallet = walletCacheScope(account);
    if (!wallet) return null;
    return `qma_paid_signal_v5_${wallet}_${providerId}_${normalizeTier(tier)}_${payload.symbol}_${signalFingerprint(payload)}`;
}

function signalSummary(source = {}) {
    const payload = normalizeSignalPayload(source);
    const funding = Number.isFinite(payload.fundingRate) ? `${(payload.fundingRate * 100).toFixed(3)}%` : 'n/a';
    const mcap = Number.isFinite(payload.marketCap) ? `$${formatCompact(payload.marketCap)}` : 'n/a';
    return `${payload.symbol || 'n/a'} · Funding ${funding} · MCap ${mcap}`;
}

function signalPlainLabel(source = {}) {
    const payload = normalizeSignalPayload(source);
    const fundingText = formatFundingPlain(payload.fundingRate, { includeNumbers: false });
    return `${payload.symbol || 'n/a'} — ${fundingText}`;
}

function displaySignalLabel(source = {}) {
    return isBasicView() ? signalPlainLabel(source) : signalSummary(source);
}

function entitlementBadgeForSignal(signal) {
    const normalized = normalizeSignalPayload(signal);
    const cachedEntry = getCachedReport(normalized, 'full') || getCachedReport(normalized, 'preview');
    const isPaid = Boolean(cachedEntry?.report);
    const historyEntries = isPaid ? [] : getCachedReportsForSymbol(normalized.symbol);
    const hasHistory = historyEntries.length > 0;
    return {
        badgeClass: isPaid ? 'paid' : hasHistory ? 'history' : 'unpaid',
        badgeText: isPaid ? paidBadgeText(cachedEntry) : hasHistory ? 'Paid History' : 'Pay to Unlock',
        cachedEntry,
        historyEntries,
        isPaid,
        hasHistory,
    };
}

function getCachedReport(source, tier = 'full', providerId = currentProviderId || 'funding_memory') {
    try {
        if (!walletCacheScope()) return null;
        const normalizedTier = normalizeTier(tier);
        const exactKey = signalCacheKey(source, normalizedTier, providerId);
        const exact = exactKey ? localStorage.getItem(exactKey) : null;
        if (exact) return JSON.parse(exact);
        if (normalizedTier === 'preview') {
            const fullKey = signalCacheKey(source, 'full', providerId);
            const full = fullKey ? localStorage.getItem(fullKey) : null;
            if (full) return JSON.parse(full);
        }
        return null;
    } catch {
        return null;
    }
}

function getCachedReportsForSymbol(symbol) {
    const normalizedSymbol = String(symbol || '').trim().toUpperCase();
    const wallet = walletCacheScope();
    if (!normalizedSymbol || !wallet) return [];
    const reports = [];
    const seen = new Set();
    const keyFragment = `qma_paid_signal_v5_${wallet}_`;

    try {
        for (let i = 0; i < localStorage.length; i += 1) {
            const key = localStorage.key(i);
            if (!key || !key.startsWith(keyFragment) || !key.includes(`_${normalizedSymbol}_`)) continue;
            const cached = JSON.parse(localStorage.getItem(key));
            if (!cached?.report) continue;
            if (!sameAddress(cached.payer_address, connectedWallet)) continue;
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

    return reports.sort((a, b) => Number(b.saved_at || 0) - Number(a.saved_at || 0));
}

function getLatestCachedReportForSymbolTier(symbol, tier = 'preview', providerId = null) {
    const normalizedTier = normalizeTier(tier);
    return getCachedReportsForSymbol(symbol).find((entry) => (
        normalizeTier(entry.tier || entry.report?.tier || entry.report?.invoice?.tier || 'full') === normalizedTier
        && (!providerId || (entry.provider_id || entry.report?.provider_id || entry.report?.invoice?.provider_id) === providerId)
    )) || null;
}

function paidBadgeText(entry) {
    if (!entry) return isBasicView() ? 'Pay to Unlock' : 'Pay to unlock';
    const tier = normalizeTier(entry.tier || entry.report?.tier || entry.report?.invoice?.tier || 'full');
    if (isBasicView()) {
        return tier === 'preview' ? 'Paid Summary' : 'Paid Full Report';
    }
    return tier === 'preview' ? 'Paid Preview' : 'Paid Full';
}

function updateAnomalyPaidState(signalSource, entry = null) {
    const signal = normalizeSignalPayload(signalSource || activeQuery || {});
    if (!signal.symbol) return;
    const cachedEntry = entry || getCachedReport(signal, 'full') || getCachedReport(signal, 'preview');
    const historyEntries = cachedEntry ? [] : getCachedReportsForSymbol(signal.symbol);
    const hasHistory = historyEntries.length > 0;
    const summary = signalSummary(signal);

    document.querySelectorAll('.anomaly-card').forEach((card) => {
        const cardSummary = card.dataset.signalSummary || '';
        const cardSymbol = card.dataset.symbol || '';
        const isExact = cardSummary === summary;
        const isSameSymbol = cardSymbol === signal.symbol;
        if (!isExact && !isSameSymbol) return;

        const badge = card.querySelector('.signal-badge');
        const metaTime = card.querySelector('[data-card-paid-at]');
        if (!badge) return;

        if (isExact && cachedEntry) {
            badge.className = 'signal-badge paid';
            badge.textContent = paidBadgeText(cachedEntry);
            if (metaTime) metaTime.textContent = `Bought ${formatDateTime(cachedEntry.saved_at)}`;
        } else if (hasHistory || isSameSymbol) {
            badge.className = 'signal-badge history';
            badge.textContent = 'Paid History';
            if (metaTime && historyEntries[0]?.saved_at) {
                metaTime.textContent = `Last paid ${formatDateTime(historyEntries[0].saved_at)}`;
            }
        }
    });

    updateAgentPickPaidState(signal);
}

function updateAgentPickPaidState(signalSource, entry = null) {
    const signal = normalizeSignalPayload(signalSource || activeQuery || {});
    if (!signal.symbol || !agentPicksContainer) return;

    const cachedEntry = entry || getCachedReport(signal, 'full') || getCachedReport(signal, 'preview');
    const historyEntries = cachedEntry ? [] : getCachedReportsForSymbol(signal.symbol);
    const hasHistory = historyEntries.length > 0;
    const summary = signalSummary(signal);

    agentPicksContainer.querySelectorAll('.agent-pick-card').forEach((card) => {
        const cardSummary = card.dataset.signalSummary || '';
        const cardSymbol = card.dataset.symbol || '';
        const isExact = cardSummary === summary;
        const isSameSymbol = cardSymbol === signal.symbol;
        if (!isExact && !isSameSymbol) return;

        const badge = card.querySelector('.signal-badge');
        const metaTime = card.querySelector('[data-pick-paid-at]');
        if (!badge) return;

        if (isExact && cachedEntry) {
            badge.className = 'signal-badge paid';
            badge.textContent = paidBadgeText(cachedEntry);
            if (metaTime) metaTime.textContent = `Bought ${formatDateTime(cachedEntry.saved_at)}`;
        } else if (hasHistory || isSameSymbol) {
            badge.className = 'signal-badge history';
            badge.textContent = 'Paid History';
            if (metaTime && historyEntries[0]?.saved_at) {
                metaTime.textContent = `Last paid ${formatDateTime(historyEntries[0].saved_at)}`;
            }
        }
    });
}

function saveCachedReport(report, account = connectedWallet || report?.invoice?.payer_address) {
    let cachedEntry = null;
    try {
        const wallet = walletCacheScope(account);
        if (!wallet) return null;
        const query = report.query || activeQuery || { symbol: report.query_symbol };
        const tier = normalizeTier(report.tier || report.invoice?.tier || currentInvoiceTier || 'full');
        const providerId = report.provider_id || report.invoice?.provider_id || currentProviderId || 'funding_memory';
        const key = signalCacheKey(query, tier, providerId, wallet);
        if (!key) return null;
        cachedEntry = {
            saved_at: Date.now(),
            signal: normalizeSignalPayload(query),
            tier,
            provider_id: providerId,
            payer_address: wallet,
            report
        };
        localStorage.setItem(key, JSON.stringify(cachedEntry));
        updateAnomalyPaidState(query, cachedEntry);
    } catch (err) {
        console.warn('Could not cache report', err);
    }
    return cachedEntry;
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

function setConnectedWallet(account) {
    const previousWallet = connectedWallet;
    connectedWallet = account || null;
    if (connectedWallet) {
        localStorage.setItem('qma_connected_wallet', connectedWallet);
    } else {
        clearWalletProfileSession(previousWallet);
        localStorage.removeItem('qma_connected_wallet');
    }
    updateWalletUi();
    if (fundArcModal?.classList.contains('open')) {
        refreshFundingReadiness();
    }
}

function updateWalletUi() {
    const isConnected = Boolean(connectedWallet);
    walletButton.classList.toggle('connected', isConnected);
    walletButtonLabel.textContent = isConnected ? shortAddress(connectedWallet) : 'Connect Wallet';
    walletMenuAddress.textContent = isConnected ? shortAddress(connectedWallet) : 'Not connected';
    walletMenuAddress.title = isConnected ? connectedWallet : '';
    walletProfileBtn.disabled = !isConnected;
    if (walletQuickProfileBtn) walletQuickProfileBtn.disabled = !isConnected;
    walletDisconnectBtn.disabled = !isConnected;

    // Copy button visibility
    const copyBtn = document.getElementById('wallet-copy-btn');
    if (copyBtn) {
        copyBtn.style.display = isConnected ? 'inline-flex' : 'none';
    }

    // Show withdraw button inside dropdown ONLY if connected as seller
    const isSeller = isConnected && sellerWalletAddress && sameAddress(connectedWallet, sellerWalletAddress);
    const withdrawMenuBtn = document.getElementById('wallet-withdraw-menu-btn');
    if (withdrawMenuBtn) {
        withdrawMenuBtn.style.display = isSeller ? 'flex' : 'none';
    }
}

async function connectWallet(options = {}) {
    const provider = await getWalletProvider();
    if (!provider?.request) {
        if (!options.silent) {
            if (isMobileDevice()) {
                openMobileWalletModal();
            } else {
                _showDesktopInstallPrompt();
            }
        }
        return null;
    }
    const method = options.silent ? 'eth_accounts' : 'eth_requestAccounts';
    let accounts = [];
    try {
        accounts = options.silent
            ? await withTimeout(provider.request({ method }), 15000, 'Wallet session restore')
            : await walletRequest({ method }, 'Wallet connection');
    } catch (err) {
        const message = describeWalletError(err);
        if (options.notify === false) {
            throw err;
        }
        if (!options.silent) {
            alert(message);
        } else {
            console.warn('Wallet session restore failed', err);
        }
        return null;
    }
    const account = accounts && accounts[0] ? accounts[0] : null;
    if (account) {
        setConnectedWallet(account);
        if (!options.silent) {
            await sleep(250);
            requestWalletProfileSession(account, { silent: true }).catch((err) => {
                console.warn('Wallet profile session was not unlocked during connect', err);
                showToast('Wallet connected. Sign once from Profile to unlock paid snapshots.', 'info');
            });
        }
    } else if (!options.silent) {
        alert('No wallet account returned by MetaMask.');
    }
    return account;
}

async function disconnectWallet() {
    const previousWallet = connectedWallet;
    try {
        const provider = await getWalletProvider();
        if (provider?.request) {
            await provider.request({
                method: 'wallet_revokePermissions',
                params: [{ eth_accounts: {} }]
            });
        }
    } catch (err) {
        console.warn('Wallet permission revoke not available', err);
    }
    clearWalletProfileSession(previousWallet);
    setConnectedWallet(null);
    walletMenu.classList.remove('open');
    walletProfileModal.classList.remove('open');
    walletProfileModal.setAttribute('aria-hidden', 'true');
    closeFundArcModal();
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
    const provider = await getWalletProvider();
    if (!provider?.request) throw new Error('No wallet provider detected.');
    for (let i = 0; i < 60; i++) {
        const receipt = await provider.request({
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

async function requestDepositAmount({ account, gatewayBalance, walletBalance, requiredPayment, walletStatus = null }) {
    const minAmount = Number(requiredPayment || 0);
    const requiredTopUp = Math.max(minAmount - Number(gatewayBalance || 0), 0);
    let selectedAmount = Math.max(minAmount, requiredTopUp);
    const quickAmounts = [
        { label: 'Exact', value: minAmount },
        { label: '0.005', value: 0.005 },
        { label: '0.1', value: 0.1 },
        { label: '1', value: 1 },
    ].filter((item, index, list) => (
        Number.isFinite(item.value)
        && item.value > 0
        && item.value + 1e-9 >= minAmount
        && list.findIndex(other => Math.abs(other.value - item.value) < 1e-9) === index
    ));
    const confirmed = await requestActionConfirmation({
        title: 'Deposit to Circle Gateway',
        subtitle: 'Choose how much USDC to deposit for this purchase',
        rows: [
            { label: 'Buyer Wallet', value: shortAddress(account) },
            { label: 'Wallet USDC', value: walletBalance == null ? 'n/a' : `${Number(walletBalance).toFixed(6)} USDC` },
            { label: 'Current Gateway Balance', value: `${Number(gatewayBalance || 0).toFixed(6)} USDC` },
            { label: 'Report Tier', value: tierLabel(currentInvoiceTier) },
            { label: 'Minimum Required', value: `${minAmount.toFixed(6)} USDC` },
            { label: 'Gateway Contract', value: shortAddress(gatewayContractAddress) },
        ],
        customHtml: `
            <div class="deposit-picker">
                <label class="deposit-input-label" for="gateway-deposit-amount">Deposit amount (USDC)</label>
                <input id="gateway-deposit-amount" class="deposit-amount-input" type="number" min="${minAmount}" step="0.001" value="${selectedAmount.toFixed(6)}">
                <div class="deposit-quick-row">
                    ${quickAmounts.map(item => `<button type="button" class="deposit-quick-btn" data-deposit-amount="${item.value}">${escapeHtml(item.label)} USDC</button>`).join('')}
                </div>
                <div class="deposit-validation" id="gateway-deposit-validation">Minimum for this purchase: ${minAmount.toFixed(6)} USDC.</div>
            </div>
        `,
        warning: 'You can deposit the exact report cost, or a larger amount (for example 1 USDC) to preload Gateway balance for future reports.',
        confirmLabel: 'Deposit',
        onOpen: ({ confirmButton, body }) => {
            const input = body.querySelector('#gateway-deposit-amount');
            const validation = body.querySelector('#gateway-deposit-validation');
            const validate = () => {
                selectedAmount = Number(input?.value || 0);
                const valid = selectedAmount > 0 && selectedAmount + 1e-9 >= minAmount;
                confirmButton.disabled = !valid;
                if (validation) {
                    validation.textContent = valid
                        ? `Will deposit ${selectedAmount.toFixed(6)} USDC into Circle Gateway.`
                        : `Enter at least ${minAmount.toFixed(6)} USDC for this purchase.`;
                    validation.classList.toggle('invalid', !valid);
                }
            };
            body.querySelectorAll('[data-deposit-amount]').forEach((button) => {
                button.addEventListener('click', () => {
                    if (input) input.value = Number(button.dataset.depositAmount || minAmount).toFixed(6);
                    validate();
                });
            });
            input?.addEventListener('input', validate);
            validate();
        },
    });
    return confirmed ? selectedAmount : null;
}

async function depositToGateway(account, amount, walletStatus = null) {
    const approveDefault = resolveGatewayApproveDefault(walletStatus) ?? Number(gatewayDepositConfig.default_approve_usdc ?? 10);
    const approveAmount = Math.max(approveDefault, amount).toFixed(6);
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
        approvalHash = await walletRequest(
            {
                method: 'eth_sendTransaction',
                params: [data.approveTx]
            },
            'USDC allowance approval'
        );
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
    const depositHash = await walletRequest(
        {
            method: 'eth_sendTransaction',
            params: [data.depositTx]
        },
        'Circle Gateway deposit'
    );
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
        const txHash = event.tx_hash || event.txHash || event.transaction_hash;
        const ref = event.explorer_url && txHash
            ? `<a class="tx-link" href="${event.explorer_url}" target="_blank" rel="noreferrer">${shortAddress(txHash)}</a>`
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

function renderProfilePayments(events, entitlements = []) {
    if (!events.length) {
        profilePaymentsBody.innerHTML = '<tr><td colspan="5" style="color: var(--text-dark);">No verified payments.</td></tr>';
        return;
    }
    profilePaymentsBody.innerHTML = events.map((event) => {
        const entitlement = findEntitlementForPayment(event, entitlements);
        const query = entitlement?.query || entitlement?.report?.query || event.query || {};
        const reportIdRaw = event.entitlement_id || (entitlement?.report ? entitlementId(entitlement) : '');
        const reportId = reportIdRaw ? escapeHtml(reportIdRaw) : '';
        const hasReport = Boolean(entitlement?.report || event.has_report || reportIdRaw);
        const action = hasReport
            ? `<button type="button" class="refresh-btn profile-open-report-btn" data-entitlement-id="${reportId}">Open</button>`
            : '<span style="color:var(--t3); font-size:0.68rem;">No saved report</span>';
        const isFinalStatus = ['completed', 'confirmed'].includes(String(event.gateway_status || '').toLowerCase());
        const missingTxLabel = isFinalStatus ? 'Arcscan tx unavailable' : 'Arcscan tx pending';
        const missingTxColor = isFinalStatus ? 'var(--text-dark)' : '#f59e0b';
        const ref = event.explorer_url && event.transaction_hash
            ? `<a class="tx-link" href="${event.explorer_url}" target="_blank" rel="noreferrer" title="Settlement: ${escapeHtml(event.settlement_id || '')}">${shortAddress(event.transaction_hash)}</a>`
            : event.settlement_id
                ? `<span class="mono-td" title="Settlement ID: ${escapeHtml(event.settlement_id)}">${shortAddress(event.settlement_id)}</span><div style="color:${missingTxColor}; font-size:0.72rem; margin-top:2px;">${escapeHtml(missingTxLabel)}</div>`
                : '<span style="color: var(--text-dark);">n/a</span>';
        return `
                    <tr class="${hasReport ? 'profile-payment-row is-clickable' : 'profile-payment-row'}" data-entitlement-id="${reportId}" title="${escapeHtml(formatDateTime(event.paid_at))}">
                        <td class="mono-td">${escapeHtml(event.symbol || query.symbol || 'n/a')}<div class="quick-payment-sub">${escapeHtml(formatDateTime(event.paid_at))}</div></td>
                        <td>${Number(event.amount_usdc || 0).toFixed(3)} USDC<div class="quick-payment-sub">${escapeHtml(tierLabel(event.tier_category || event.tier || 'legacy'))}</div></td>
                        <td>${gatewayStatusBadge(event.gateway_status)}</td>
                        <td>${ref}</td>
                        <td>${action}</td>
                    </tr>
                `;
    }).join('');
    const openById = async (id) => {
        const localTarget = entitlements.find(entry => entitlementId(entry) === id);
        if (localTarget?.report) {
            openPurchasedReport(localTarget);
            return;
        }
        if (!id || !activeProfileWallet) {
            showToast('This payment does not include a saved report snapshot yet.', 'warning');
            return;
        }
        try {
            let token = getCachedWalletProfileToken(activeProfileWallet);
            if (!token) {
                showToast('Sign once to unlock your private paid snapshots.', 'info');
                token = await requestWalletProfileSession(activeProfileWallet);
            }
            const resp = await fetch(
                apiUrl(`/api/v1/wallets/${activeProfileWallet}/reports/${encodeURIComponent(id)}`),
                { headers: walletPrivateHeaders(token) }
            );
            if (resp.status === 403) {
                clearWalletProfileSession(activeProfileWallet);
                throw new Error('Private profile session expired. Sign again to open snapshots.');
            }
            if (!resp.ok) throw new Error(`Report endpoint returned ${resp.status}`);
            const data = await resp.json();
            openPurchasedReport(data.entitlement);
        } catch (err) {
            console.warn('Could not open paid report detail', err);
            showToast(err.message || 'Could not load this paid report snapshot.', 'error');
        }
    };
    profilePaymentsBody.querySelectorAll('.profile-payment-row.is-clickable').forEach((row) => {
        row.addEventListener('click', (event) => {
            if (event.target.closest('a')) return;
            openById(row.dataset.entitlementId);
        });
    });
    profilePaymentsBody.querySelectorAll('.profile-open-report-btn').forEach((button) => {
        button.addEventListener('click', (event) => {
            event.stopPropagation();
            openById(button.dataset.entitlementId);
        });
    });
}

function updatePagerControls(prefix, pageMeta) {
    const page = Number(pageMeta?.page || 1);
    const totalPages = Number(pageMeta?.total_pages || 1);
    const total = Number(pageMeta?.total || 0);
    const label = document.getElementById(`${prefix}-page-label`);
    const prev = document.getElementById(`${prefix}-prev-btn`);
    const next = document.getElementById(`${prefix}-next-btn`);
    if (label) {
        label.textContent = total ? `Page ${page} / ${totalPages} (${total})` : 'Page 1 / 1';
        if (pageMeta?.legacy) {
            label.textContent = totalPages > 1
                ? `Page 1 / ${totalPages} (${total}) - API redeploy needed`
                : 'Page 1 / 1';
            label.title = 'The API response does not include pagination metadata yet. Restart local backend or redeploy Render from the latest commit.';
        } else {
            label.title = '';
        }
    }
    if (prev) prev.disabled = page <= 1;
    if (next) next.disabled = pageMeta?.legacy || page >= totalPages;
}

function fallbackPageMeta(meta, currentPage, pageSize, totalFallback, visibleCount) {
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

function renderWalletProfileSummary(metrics, walletStatus) {
    const gatewayBalance = metrics?.gateway_balance?.available_usdc;
    profileGatewayBalance.textContent = gatewayBalance === null || gatewayBalance === undefined
        ? 'n/a'
        : `${Number(gatewayBalance).toFixed(6)} USDC`;
    const chainBalance = getOnChainUsdcBalance(walletStatus);
    profileChainBalance.textContent = chainBalance
        ? `${Number(chainBalance).toFixed(6)} USDC`
        : 'n/a';
    const tierCounts = metrics?.tier_counts || {};
    const legacyProfile = Number(tierCounts.legacy || 0);
    profilePayments.textContent = `${metrics?.current_payments ?? metrics?.payments ?? 0} (P:${tierCounts.preview || 0} F:${tierCounts.full || 0}${legacyProfile ? ` L:${legacyProfile}` : ''})`;
    profileSpent.textContent = `${Number(metrics?.spent_usdc || 0).toFixed(3)} USDC`;

    const symbols = metrics?.purchased_symbols || [];
    profileTokenList.innerHTML = symbols.length
        ? symbols.map(symbol => `<span class="token-chip">${escapeHtml(symbol)}</span>`).join('')
        : '<span class="token-chip">None yet</span>';
}

async function loadProfilePaymentsPage(account, page = profilePaymentsPage) {
    const params = new URLSearchParams({
        page: String(page),
        page_size: String(PROFILE_PAYMENTS_PAGE_SIZE)
    });
    const token = getCachedWalletProfileToken(account);
    let resp = await fetch(apiUrl(`/api/v1/wallets/${account}/payments?${params.toString()}`), {
        headers: walletPrivateHeaders(token),
    });
    if (resp.status === 403 && token) {
        clearWalletProfileSession(account);
        showToast('Private profile session expired. Showing public payment history until you sign again.', 'warning');
        resp = await fetch(apiUrl(`/api/v1/wallets/${account}/payments?${params.toString()}`));
    }
    const data = resp.ok ? await resp.json() : null;
    if (!data) {
        throw new Error('Could not load wallet profile.');
    }
    const pageMeta = fallbackPageMeta(
        data?.recent_payments_page,
        page,
        PROFILE_PAYMENTS_PAGE_SIZE,
        data?.recent_payments_page?.total,
        (data?.recent_payments || []).length
    );
    profilePaymentsPage = Number(pageMeta.page || page || 1);
    profilePaymentsTotalPages = Number(pageMeta.total_pages || 1);
    renderProfilePayments(data?.recent_payments || [], []);
    updatePagerControls('profile-payments', pageMeta);
    return data;
}

async function loadWalletProfileSummary(account) {
    const resp = await fetch(apiUrl(`/api/v1/wallets/${account}/summary`));
    if (!resp.ok) throw new Error('Could not load wallet profile summary.');
    return resp.json();
}

async function openWalletProfile() {
    const account = connectedWallet || await connectWallet();
    if (!account) return;
    walletMenu.classList.remove('open');
    activeProfileWallet = account;
    profilePaymentsPage = 1;
    walletProfileModal.classList.add('open');
    walletProfileModal.setAttribute('aria-hidden', 'false');
    walletProfileAddress.textContent = account;
    if (profilePageLink) profilePageLink.href = '/profile';
    profileGatewayBalance.textContent = 'loading...';
    profileChainBalance.textContent = 'loading...';
    profilePayments.textContent = 'loading...';
    profileSpent.textContent = 'loading...';
    profileTokenList.innerHTML = '<span class="token-chip">Loading</span>';
    profilePaymentsBody.innerHTML = '<tr><td colspan="5" style="color: var(--text-dark);">Loading payments...</td></tr>';
    renderProfileEvents(getWalletEvents(account));

    try {
        try {
            await requestWalletProfileSession(account, { silent: true });
        } catch (err) {
            console.warn('Private wallet profile session not unlocked', err);
            showToast('Profile loaded. Sign once to unlock paid report snapshots.', 'warning');
        }
        const [metrics, walletStatus] = await Promise.all([
            loadWalletProfileSummary(account),
            getWalletStatus(account)
        ]);
        renderWalletProfileSummary(metrics, walletStatus);
        await loadProfilePaymentsPage(account, 1);
    } catch (err) {
        console.warn('Wallet profile unavailable', err);
        profileGatewayBalance.textContent = 'n/a';
        profileChainBalance.textContent = 'n/a';
        profilePayments.textContent = '0';
        profileSpent.textContent = '0.00 USDC';
        profileTokenList.innerHTML = '<span class="token-chip">Unavailable</span>';
        profilePaymentsBody.innerHTML = '<tr><td colspan="5" style="color: var(--color-danger);">Could not load wallet profile.</td></tr>';
    }
}

async function openWalletProfilePage() {
    const account = connectedWallet || await connectWallet();
    if (!account) return;
    walletMenu.classList.remove('open');
    window.location.href = '/profile';
}

function setLiveRefreshState(label, tone = '') {
    if (!liveRefreshPill) return;
    liveRefreshPill.textContent = label;
    liveRefreshPill.classList.toggle('is-refreshing', tone === 'refreshing');
    liveRefreshPill.classList.toggle('is-error', tone === 'error');
}

// Load Live Feed
async function loadLiveAnomalies(options = {}) {
    const { silent = false, preserveSelection = false } = options;
    if (liveFeedRefreshInFlight) return;
    liveFeedRefreshInFlight = true;
    const activeCard = preserveSelection ? anomaliesContainer?.querySelector('.anomaly-card.active') : null;
    const activeSummary = activeCard?.dataset?.signalSummary || null;
    const activeSymbol = activeCard?.dataset?.symbol || null;
    try {
        setLiveRefreshState('Refreshing', 'refreshing');
        if (!silent) {
            anomaliesContainer.innerHTML = `
                    <div style="text-align: center; color: var(--text-dark); margin-top: 40px;">
                        <div class="spinner" style="margin: 0 auto 12px;"></div>
                        Scanning live exchanges...
                    </div>
                `;
        }
        const resp = await fetch(apiUrl('/api/v1/live-anomalies'));
        const data = await resp.json();

        if (data.anomalies && data.anomalies.length > 0) {
            anomaliesContainer.innerHTML = '';
            let restoredSelection = false;
            data.anomalies.forEach((item, index) => {
                const card = document.createElement('div');

                const fundingPercent = (item.fundingRate * 100).toFixed(3);
                const mcapMillions = (item.marketCap / 1000000).toFixed(1);
                const volMillions = (item.volume24h / 1000000).toFixed(1);
                const signal = formSignalFromAnomaly(item);
                const signalSummaryText = signalSummary(signal);
                const shouldRestore = preserveSelection
                    && ((activeSummary && activeSummary === signalSummaryText)
                        || (activeSymbol && activeSymbol === signal.symbol));
                const shouldAutoSelect = !preserveSelection && index === 0;
                card.className = `anomaly-card ${shouldRestore || shouldAutoSelect ? 'active' : ''}`;
                if (shouldRestore) restoredSelection = true;
                card.dataset.symbol = signal.symbol;
                card.dataset.signalSummary = signalSummaryText;
                const cachedEntry = getCachedReport(signal, 'full') || getCachedReport(signal, 'preview');
                const isPaid = Boolean(cachedEntry?.report);
                const historyEntries = isPaid ? [] : getCachedReportsForSymbol(signal.symbol);
                const hasHistory = historyEntries.length > 0;
                const cardSeenAt = cachedEntry?.saved_at
                    ? formatDateTime(cachedEntry.saved_at)
                    : hasHistory
                        ? `Last paid ${formatDateTime(historyEntries[0].saved_at)}`
                        : `Live ${formatDateTime(data.last_updated)}`;
                const badgeClass = isPaid ? 'paid' : hasHistory ? 'history' : 'unpaid';
                const badgeText = isPaid ? paidBadgeText(cachedEntry) : hasHistory ? 'Paid History' : 'Pay to Unlock';

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
                                <span data-card-paid-at>${escapeHtml(cardSeenAt)}</span>
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
                if (index === 0 && !hasUnlockedReport && !preserveSelection) {
                    loadCardIntoForm(item);
                }
            });
            if (preserveSelection && !restoredSelection && !hasUnlockedReport && data.anomalies[0]) {
                const firstCard = anomaliesContainer.querySelector('.anomaly-card');
                if (firstCard) firstCard.classList.add('active');
            }
            setLiveRefreshState(`Updated ${formatTimeOnly(data.last_updated || Date.now())}`);
        } else {
            anomaliesContainer.innerHTML = '<div style="text-align: center; color: var(--text-dark); margin-top: 40px;">No funding anomalies found (funding <= -0.25%).</div>';
            setLiveRefreshState('No signals');
        }
    } catch (err) {
        console.error(err);
        if (!silent || !anomaliesContainer.children.length) {
            anomaliesContainer.innerHTML = '<div style="text-align: center; color: var(--color-danger); margin-top: 40px;">Error scanning MEXC. Try again.</div>';
        }
        setLiveRefreshState('Refresh error', 'error');
    } finally {
        liveFeedRefreshInFlight = false;
    }
}

function setAgentRunTrace(lines = []) {
    agentRunTraceLines = lines.filter(Boolean);
    if (!agentRunTrace) return;
    agentRunTrace.innerHTML = agentRunTraceLines.map((line) => {
        const text = typeof line === 'string' ? line : line.text;
        const tone = typeof line === 'string' ? '' : line.tone || '';
        return `<div class="agent-run-line ${escapeHtml(tone)}">${escapeHtml(text)}</div>`;
    }).join('');
}

function appendAgentRunTrace(text, tone = '') {
    setAgentRunTrace([...agentRunTraceLines, { text, tone }]);
}

function openAgentRunModal() {
    if (!agentRunModal) return;
    walletMenu.classList.remove('open');
    closeFundArcModal();
    if (agentRunDismiss) agentRunDismiss.textContent = currentInvoiceBuyerType === 'agent' && currentInvoiceId
        ? 'Continue to Payment'
        : 'Close';
    agentRunModal.classList.add('open');
    agentRunModal.setAttribute('aria-hidden', 'false');
}

function closeAgentRunModal() {
    if (!agentRunModal) return;
    agentRunModal.classList.remove('open');
    agentRunModal.setAttribute('aria-hidden', 'true');
}

function formatChainLabel(chainId) {
    const normalized = normalizeChainId(chainId);
    const labels = {
        [ARC_TESTNET_HEX]: 'Arc Testnet',
        '0x1': 'Ethereum Mainnet',
        '0xaa36a7': 'Ethereum Sepolia',
        '0x2105': 'Base',
        '0x14a34': 'Base Sepolia',
        '0x89': 'Polygon',
        '0xa': 'Optimism',
        '0xa4b1': 'Arbitrum One'
    };
    return labels[normalized] ? `${labels[normalized]} (${normalized})` : normalized;
}

function normalizeChainId(chainId) {
    if (chainId === null || chainId === undefined || chainId === '') return '';
    const value = String(chainId).trim().toLowerCase();
    if (value.startsWith('0x')) return value;
    const num = Number(value);
    return Number.isFinite(num) ? `0x${num.toString(16)}` : value;
}

function formatFundingAmount(value) {
    const num = Number(value);
    if (!Number.isFinite(num)) return 'n/a';
    return `${num.toFixed(6).replace(/0+$/, '').replace(/\.$/, '')} USDC`;
}

function parseFundingAmount(value) {
    if (value === null || value === undefined || value === '') return null;
    const normalized = typeof value === 'string'
        ? value.replace(/USDC/ig, '').replace(/,/g, '').trim()
        : value;
    const num = Number(normalized);
    return Number.isFinite(num) ? num : null;
}

function getFundingRequiredAmount() {
    const paywallVisible = paywallElement && paywallElement.style.display !== 'none';
    if (paywallVisible && Number.isFinite(Number(currentInvoiceAmount)) && Number(currentInvoiceAmount) > 0) {
        return Number(currentInvoiceAmount);
    }
    const price = tierPrice(currentInvoiceTier || 'full');
    return Number.isFinite(Number(price)) && Number(price) > 0 ? Number(price) : null;
}

function setFundingPrimaryAction({ action, label, disabled = false }) {
    if (!fundPrimaryAction) return;
    fundPrimaryAction.dataset.action = action || '';
    fundPrimaryAction.textContent = label || 'Close';
    fundPrimaryAction.disabled = Boolean(disabled);
}

function setFundingPill(label, tone = '') {
    if (!fundReadinessStatus) return;
    fundReadinessStatus.textContent = label;
    fundReadinessStatus.classList.remove('ready', 'warn');
    if (tone) fundReadinessStatus.classList.add(tone);
}

function renderFundingReadiness(state = {}) {
    const required = state.requiredAmount;
    const walletBalance = state.walletBalance;
    const gatewayBalance = state.gatewayBalance;
    const requiredLabel = formatFundingAmount(required);

    if (fundWalletStatus) {
        fundWalletStatus.textContent = state.account ? shortAddress(state.account) : 'Not connected';
        fundWalletStatus.title = state.account || '';
    }
    if (fundProviderStatus) fundProviderStatus.textContent = state.providerLabel || 'n/a';
    if (fundChainStatus) fundChainStatus.textContent = state.chainLabel || 'n/a';
    if (fundArcStatus) {
        fundArcStatus.textContent = state.isArc
            ? 'Arc Testnet'
            : (state.account ? 'Wrong network' : 'Unknown');
    }
    if (fundWalletUsdc) fundWalletUsdc.textContent = formatFundingAmount(walletBalance);
    if (fundGatewayBalance) fundGatewayBalance.textContent = formatFundingAmount(gatewayBalance);
    if (fundRequiredAmount) fundRequiredAmount.textContent = requiredLabel;

    if (!state.account) {
        setFundingPill('Wallet needed', 'warn');
        if (fundNextStep) fundNextStep.textContent = 'Connect wallet first';
        setFundingPrimaryAction({ action: 'connect', label: 'Connect wallet first' });
        return;
    }

    // Wrong-chain check: covers Ethereum mainnet, BNB, any non-Arc network.
    // Uses the fresh eth_chainId RPC result; sentinel '__chain_error__' also falls here
    // so a provider failure surfaces as "Wrong chain / retry" instead of silently passing.
    if (state.chainId && normalizeChainId(state.chainId) !== ARC_TESTNET_HEX) {
        setFundingPill('Wrong chain', 'warn');
        if (fundNextStep) fundNextStep.textContent = 'Add or switch to Arc Testnet. Your wallet will show the network details for approval.';
        setFundingPrimaryAction({ action: 'switch', label: 'Add / Switch Arc Testnet' });
        return;
    }

    if (state.error) {
        setFundingPill('Check failed', 'warn');
        if (fundNextStep) fundNextStep.textContent = 'Funding status is unavailable. Retry or continue to payment.';
        setFundingPrimaryAction({ action: 'refresh', label: 'Retry readiness check' });
        return;
    }

    if (required == null) {
        setFundingPill('Ready check', '');
        if (fundNextStep) fundNextStep.textContent = 'Select a report first, then QMA can estimate the required amount.';
        setFundingPrimaryAction({ action: 'close', label: 'Close' });
        return;
    }

    if (gatewayBalance != null && gatewayBalance + 1e-9 >= required) {
        setFundingPill('Ready', 'ready');
        if (fundNextStep) fundNextStep.textContent = 'Gateway balance is ready for the selected report.';
        setFundingPrimaryAction({ action: 'close', label: 'Continue to payment' });
        return;
    }

    const availableWallet = walletBalance || 0;
    const availableGateway = gatewayBalance || 0;
    if (availableWallet + availableGateway + 1e-9 >= required) {
        setFundingPill('Gateway low', 'warn');
        if (fundNextStep) fundNextStep.textContent = 'Continue to payment; QMA will prompt Gateway Deposit';
        setFundingPrimaryAction({ action: 'close', label: 'Continue to payment' });
        return;
    }

    setFundingPill('Funding needed', 'warn');
    if (fundNextStep) fundNextStep.textContent = 'Use Faucet or CCTP/App Kit, then retry. Arc uses USDC for gas and payment funding.';
    setFundingPrimaryAction({ action: 'faucet', label: 'Open Circle Faucet' });
}

async function refreshFundingReadiness() {
    const account = connectedWallet;
    const requiredAmount = getFundingRequiredAmount();
    const state = {
        account,
        requiredAmount,
        chainId: null,
        chainLabel: 'n/a',
        providerLabel: 'n/a',
        isArc: false,
        walletBalance: null,
        gatewayBalance: null,
        error: null
    };

    if (!account) {
        renderFundingReadiness(state);
        return;
    }

    // Step 1: chain detection — separate try/catch so a provider error sets chainId
    // to a known-bad value rather than silently leaving it null and skipping wrong-chain check.
    let provider = null;
    try {
        provider = await getWalletProvider();
        state.providerLabel = getWalletProviderLabel(provider);
        if (provider?.request) {
            const rawChainId = await withTimeout(
                provider.request({ method: 'eth_chainId' }),
                15000,
                'Funding chain check'
            );
            state.chainId = rawChainId;
            const chainHex = normalizeChainId(rawChainId);
            state.isArc = chainHex === ARC_TESTNET_HEX;
            state.chainLabel = formatChainLabel(rawChainId);
        } else {
            state.chainLabel = 'No wallet provider';
        }
    } catch (err) {
        console.warn('Funding chain check failed', err);
        // Mark as chain error so renderFundingReadiness shows the right pill
        // instead of falling through to balance checks with stale/null chainId.
        state.chainId = '__chain_error__';
        state.chainLabel = 'Chain detection failed';
        state.error = err;
    }

    // Step 2: balance checks — only run when on the right chain, avoid unnecessary
    // RPC calls and confusing balance numbers when the wallet is on the wrong network.
    if (!state.error && state.isArc) {
        try {
            const [walletStatus, gatewayBalance] = await Promise.all([
                getWalletStatus(account),
                checkGatewayBalance(account)
            ]);
            state.walletBalance = parseFundingAmount(getOnChainUsdcBalance(walletStatus));
            state.gatewayBalance = gatewayBalance;
        } catch (err) {
            console.warn('Funding balance check failed', err);
            state.error = err;
        }
    }

    renderFundingReadiness(state);
}

function openFundArcModal() {
    if (!fundArcModal) return;
    walletMenu.classList.remove('open');
    closeAgentRunModal();
    fundArcModal.classList.add('open');
    fundArcModal.setAttribute('aria-hidden', 'false');
    refreshFundingReadiness();
}

function closeFundArcModal() {
    if (!fundArcModal) return;
    fundArcModal.classList.remove('open');
    fundArcModal.setAttribute('aria-hidden', 'true');
}

function recommendationTierPrice(pick = {}, tier = 'preview', pricing = {}) {
    const normalizedTier = normalizeTier(tier);
    if (normalizeTier(pick.suggested_tier || 'preview') === normalizedTier
        && pick.suggested_price_usdc != null
        && Number.isFinite(Number(pick.suggested_price_usdc))) {
        return Number(pick.suggested_price_usdc);
    }
    const pricingKeys = normalizedTier === 'preview'
        ? ['preview_base_usdc', 'preview_usdc']
        : ['full_base_usdc', 'full_usdc'];
    for (const key of pricingKeys) {
        if (pricing?.[key] != null && Number.isFinite(Number(pricing[key]))) {
            return Number(pricing[key]);
        }
    }
    const providerPrice = providerCatalog[pick.provider_id || currentProviderId]?.pricing?.[normalizedTier]?.amount_usdc;
    if (providerPrice != null && Number.isFinite(Number(providerPrice))) {
        return Number(providerPrice);
    }
    const configuredPrice = pricingConfig[normalizedTier];
    if (configuredPrice != null && Number.isFinite(Number(configuredPrice))) {
        return Number(configuredPrice);
    }
    return tierPrice(normalizedTier) || 0;
}

function agentPendingInvoiceFor(signal, tier) {
    if (!currentInvoiceId || currentInvoiceBuyerType !== 'agent' || paymentSuccessReady) return false;
    if (normalizeTier(currentInvoiceTier) !== normalizeTier(tier)) return false;
    if (!activeQuery?.symbol) return false;
    return signalSummary(activeQuery) === signalSummary(signal);
}

function agentPolicyPick(recommendations = [], budget = 0.01, maxPrice = 0.005, pricing = {}) {
    const audit = [];
    const candidates = recommendations
        .map((pick) => {
            let tier = normalizeTier(pick.suggested_tier || 'preview');
            const signal = normalizeSignalPayload(pick.query || { symbol: pick.symbol });
            const providerId = pick.provider_id || currentProviderId || 'funding_memory';
            const fullEntry = getCachedReport(signal, 'full', providerId);
            const exactPreviewEntry = fullEntry ? null : getCachedReport(signal, 'preview', providerId);
            const symbolPreviewEntry = exactPreviewEntry || getLatestCachedReportForSymbolTier(signal.symbol, 'preview', providerId);
            const shouldUpgrade = tier === 'preview' && symbolPreviewEntry?.report && !fullEntry?.report;
            if (shouldUpgrade) {
                tier = 'full';
            }
            const price = recommendationTierPrice(pick, tier, pricing);
            const pendingInvoice = agentPendingInvoiceFor(signal, tier);
            let skippedReason = '';
            if (price <= 0) {
                skippedReason = 'missing price';
            } else if (fullEntry?.report) {
                skippedReason = 'Full Report already purchased';
            } else if (pendingInvoice) {
                skippedReason = `invoice ${shortAddress(currentInvoiceId)} is already waiting for payment`;
            } else if (price > budget) {
                skippedReason = `over budget (${price.toFixed(3)} > ${budget.toFixed(3)})`;
            } else if (price > maxPrice) {
                skippedReason = `over max/report (${price.toFixed(3)} > ${maxPrice.toFixed(3)})`;
            }
            return {
                ...pick,
                agent_tier: tier,
                agent_price: price,
                agent_signal: signal,
                agent_upgrade_from_preview: shouldUpgrade,
                agent_upgrade_match: exactPreviewEntry?.report ? 'exact Preview snapshot' : 'previous Preview for same symbol',
                agent_skipped_reason: skippedReason,
                agent_value_density: price > 0 ? Number(pick.score || 0) / price : 0,
            };
        });
    candidates.slice(0, 5).forEach((pick) => {
        if (pick.agent_skipped_reason) {
            audit.push({ text: `Skipped ${pick.symbol}: ${pick.agent_skipped_reason}.`, tone: 'muted' });
        } else if (pick.agent_upgrade_from_preview) {
            audit.push({ text: `Candidate ${pick.symbol}: ${pick.agent_upgrade_match} already paid, evaluating Full Report upgrade at ${pick.agent_price.toFixed(3)} USDC.`, tone: 'active' });
        } else {
            audit.push({ text: `Candidate ${pick.symbol}: score ${Number(pick.score || 0).toFixed(1)}, value density ${pick.agent_value_density.toFixed(1)}.`, tone: 'active' });
        }
    });
    const selected = candidates
        .filter((pick) => !pick.agent_skipped_reason)
        .sort((a, b) => {
            const upgradeDiff = Number(Boolean(b.agent_upgrade_from_preview)) - Number(Boolean(a.agent_upgrade_from_preview));
            if (upgradeDiff) return upgradeDiff;
            const valueDiff = Number(b.agent_value_density || 0) - Number(a.agent_value_density || 0);
            return valueDiff || Number(b.score || 0) - Number(a.score || 0);
        })[0] || null;
    return { selected, audit };
}

async function runAgentDecision() {
    if (!agentRunBtn) return;
    const budget = Number(agentRunBudgetInput?.value || 0.01);
    const maxPrice = Number(agentRunMaxPriceInput?.value || 0.005);
    if (!Number.isFinite(budget) || budget <= 0 || !Number.isFinite(maxPrice) || maxPrice <= 0) {
        showToast('Agent policy needs a positive budget and max price.', 'warning');
        return;
    }

    agentRunBtn.disabled = true;
    agentRunBtn.textContent = 'Agent running...';
    setAgentRunTrace([
        { text: `Policy loaded: budget ${budget.toFixed(3)} USDC, max/report ${maxPrice.toFixed(3)} USDC.`, tone: 'active' },
        'Fetching live paid opportunities from /api/v1/agent/recommendations...'
    ]);

    try {
        const resp = await fetch(apiUrl('/api/v1/agent/recommendations?limit=8'));
        if (!resp.ok) throw new Error(`Agent endpoint returned ${resp.status}`);
        const data = await resp.json();
        const picks = data.recommendations || [];
        appendAgentRunTrace(`Scanned ${picks.length} ranked opportunities.`);
        const { selected, audit } = agentPolicyPick(picks, budget, maxPrice, data.pricing || {});
        audit.forEach((line) => appendAgentRunTrace(line.text, line.tone));
        if (!selected) {
            appendAgentRunTrace('No affordable report matched the current budget policy.', 'warning');
            showToast('Agent found no affordable report under this policy.', 'warning');
            return;
        }

        const signal = selected.agent_signal || normalizeSignalPayload(selected.query || { symbol: selected.symbol });
        appendAgentRunTrace(`Selected ${selected.symbol}: score ${Number(selected.score || 0).toFixed(1)}, ${tierLabel(selected.agent_tier)}, ${selected.agent_price.toFixed(3)} USDC.`, 'success');
        if (selected.agent_upgrade_from_preview) {
            appendAgentRunTrace('Upgrade rule: paid Preview exists, so agent is buying the Full Report instead of paying for Preview again.', 'success');
        }
        appendAgentRunTrace(`Decision rule: complete paid Preview snapshots first, then choose highest value density under budget.`);
        appendAgentRunTrace(`Reasoning: ${(selected.reasons || ['fresh live anomaly']).join(' | ')}`);
        appendAgentRunTrace('Creating provider-bound invoice with buyer_type=agent...');

        applySignalToState(signal);
        currentProviderId = selected.provider_id || 'funding_memory';
        if (providerSelect && providerCatalog[currentProviderId]) {
            providerSelect.value = currentProviderId;
        }
        currentInvoiceTier = normalizeTier(selected.agent_tier);
        currentInvoiceAmount = selected.agent_price;
        nextInvoiceBuyerType = 'agent';

        const cachedEntry = getCachedReport(signal, currentInvoiceTier);
        if (cachedEntry?.report) {
            appendAgentRunTrace(`Wallet already has this paid ${tierLabel(currentInvoiceTier)} snapshot. Opening cached report instead.`, 'success');
            if (normalizeTier(cachedEntry.tier || cachedEntry.report?.tier) === 'preview') {
                renderPreviewReport(cachedEntry.report, cachedEntry);
            } else {
                renderReport(cachedEntry.report, cachedEntry);
            }
            return;
        }

        const submitBtn = queryForm.querySelector(`button[type="submit"][data-tier="${currentInvoiceTier}"]`)
            || queryForm.querySelector('button[type="submit"][data-tier="full"]');
        if (!submitBtn) throw new Error(`No submit button found for ${currentInvoiceTier} tier.`);
        queryForm.requestSubmit(submitBtn);
    } catch (err) {
        console.warn('Agent run failed', err);
        appendAgentRunTrace(`Agent run failed: ${err.message || err}`, 'error');
        showToast(`Agent run failed: ${err.message || err}`, 'error');
    } finally {
        agentRunBtn.disabled = false;
        agentRunBtn.textContent = 'Run Agent Decision';
    }
}

async function loadAgentRecommendations(options = {}) {
    if (!agentPicksContainer) return;
    const { silent = false } = options;
    if (agentRecommendationsInFlight) return;
    agentRecommendationsInFlight = true;
    if (!silent) {
        agentPicksContainer.innerHTML = '<div class="agent-empty">Ranking live signals...</div>';
    }
    try {
        const resp = await fetch(apiUrl('/api/v1/agent/recommendations'));
        if (!resp.ok) throw new Error(`Agent endpoint returned ${resp.status}`);
        const data = await resp.json();
        const picks = data.recommendations || [];
        if (!picks.length) {
            agentPicksContainer.innerHTML = '<div class="agent-empty">No paid opportunities ranked yet.</div>';
            return;
        }
        agentPicksContainer.innerHTML = picks.slice(0, 5).map((pick) => {
            const signal = normalizeSignalPayload(pick.query || { symbol: pick.symbol });
            const entitlement = entitlementBadgeForSignal(signal);
            const cardSeenAt = entitlement.cachedEntry?.saved_at
                ? formatDateTime(entitlement.cachedEntry.saved_at)
                : entitlement.hasHistory
                    ? `Last paid ${formatDateTime(entitlement.historyEntries[0].saved_at)}`
                    : 'Agent recommendation';
            return `
            <div class="agent-pick-card" data-symbol="${escapeHtml(pick.symbol)}" data-tier="${escapeHtml(pick.suggested_tier)}" data-signal-summary="${escapeHtml(signalSummary(signal))}">
                <div class="agent-pick-top">
                    <span class="agent-pick-symbol">${escapeHtml(pick.symbol || 'n/a')}</span>
                    <span class="agent-pick-score">${Number(pick.score || 0).toFixed(1)}</span>
                </div>
                <div class="agent-pick-meta">
                    <span class="agent-tier-pill">${escapeHtml(tierLabel(pick.suggested_tier))} ${Number(pick.suggested_price_usdc || tierPrice(pick.suggested_tier)).toFixed(3)}</span>
                    <span class="agent-pick-value" style="color:var(--t3); font-size:0.64rem;">${escapeHtml(pick.provider_id || 'provider')}</span>
                </div>
                <div class="agent-pick-reasons">${escapeHtml((pick.reasons || []).join(' | '))}</div>
                <div class="card-meta-row agent-pick-meta-row">
                    <span data-pick-paid-at>${escapeHtml(cardSeenAt)}</span>
                    <span class="signal-badge ${entitlement.badgeClass}">${escapeHtml(entitlement.badgeText)}</span>
                </div>
            </div>
        `;
        }).join('');

        agentPicksContainer.querySelectorAll('.agent-pick-card').forEach((card, index) => {
            card.addEventListener('click', () => {
                const pick = picks[index];
                if (!pick?.query) return;
                const signal = normalizeSignalPayload(pick.query);
                applySignalToState(signal);
                currentProviderId = pick.provider_id || 'funding_memory';
                if (providerSelect && providerCatalog[currentProviderId]) {
                    providerSelect.value = currentProviderId;
                }
                currentInvoiceTier = normalizeTier(pick.suggested_tier);
                currentInvoiceAmount = Number(pick.suggested_price_usdc || tierPrice(currentInvoiceTier));

                if (isBasicView()) {
                    const cachedEntry = getCachedReport(signal, currentInvoiceTier);
                    if (cachedEntry?.report) {
                        if (normalizeTier(cachedEntry.tier || cachedEntry.report?.tier) === 'preview') {
                            renderPreviewReport(cachedEntry.report, cachedEntry);
                        } else {
                            renderReport(cachedEntry.report, cachedEntry);
                        }
                        showToast(`Loaded paid ${pick.symbol} from ${formatDateTime(cachedEntry.saved_at)}.`, 'success');
                        return;
                    }
                    showSignalPaywall(signal, {
                        tier: currentInvoiceTier,
                        title: 'Unlock Historical Comparison',
                        description: `Choose Summary or Full Report below to compare ${pick.symbol} with similar past events.`,
                    });
                    showToast(`Selected ${pick.symbol}: ${pick.reasons?.[0] || 'ranked opportunity'}.`, 'info');
                    return;
                }

                const submitBtn = queryForm.querySelector(`button[type="submit"][data-tier="${currentInvoiceTier}"]`)
                    || queryForm.querySelector('button[type="submit"][data-tier="full"]');
                if (!submitBtn) {
                    showToast(`No submit button found for ${tierLabel(currentInvoiceTier)}.`, 'error');
                    return;
                }
                showToast(`Agent selected ${pick.symbol} via ${currentProviderId}: ${pick.reasons?.[0] || 'ranked opportunity'}. Creating ${tierLabel(currentInvoiceTier)} invoice.`, 'info');
                queryForm.requestSubmit(submitBtn);
            });
        });
    } catch (err) {
        console.warn('Agent recommendations unavailable', err);
        if (!silent || !agentPicksContainer.children.length) {
            agentPicksContainer.innerHTML = '<div class="agent-empty">Agent ranking unavailable.</div>';
        }
    } finally {
        agentRecommendationsInFlight = false;
    }
}

async function loadProviders() {
    if (providerMarketplaceContainer) {
        providerMarketplaceContainer.innerHTML = '<div class="agent-empty">Loading providers...</div>';
    }
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
            if (providerMarketplaceContainer) {
                providerMarketplaceContainer.innerHTML = '<div class="agent-empty">No providers registered.</div>';
            }
            return;
        }
        if (providerSelect) {
            providerSelect.innerHTML = providers.map((provider) => {
                const status = provider.enabled === false
                    ? ' (disabled)'
                    : provider.status && provider.status !== 'approved'
                        ? ` (${provider.status})`
                        : '';
                return `<option value="${escapeHtml(provider.provider_id)}" ${provider.enabled === false ? 'disabled' : ''}>${escapeHtml(provider.provider_id)}${escapeHtml(status)}</option>`;
            }).join('');
            const enabledProviders = providers.filter(provider => provider.enabled !== false);
            const currentProviderAvailable = providerCatalog[currentProviderId]?.enabled !== false
                && Boolean(providerCatalog[currentProviderId]);
            providerSelect.value = currentProviderAvailable
                ? currentProviderId
                : enabledProviders[0]?.provider_id || providers[0].provider_id;
            currentProviderId = providerSelect.value || currentProviderId;
            providerSelect.addEventListener('change', () => {
                currentProviderId = providerSelect.value || 'funding_memory';
                quotedPrices = { preview: null, full: null };
                scheduleQuotedPriceRefresh();
                showToast(`Provider selected: ${providerCatalog[currentProviderId]?.provider_name || currentProviderId}`, 'info');
            });
        }
        if (!providerMarketplaceContainer) return;
        providerMarketplaceContainer.innerHTML = providers.map((provider) => {
            const preview = provider.pricing?.preview?.amount_usdc;
            const full = provider.pricing?.full?.amount_usdc;
            return `
                <button type="button" class="provider-card ${provider.provider_id === currentProviderId ? 'active' : ''}" data-provider-id="${escapeHtml(provider.provider_id)}">
                    <div class="provider-card-top">
                        <span class="provider-name">${escapeHtml(provider.provider_name || provider.provider_id)}</span>
                        <span class="provider-id">${escapeHtml(provider.provider_id)}</span>
                    </div>
                    <div class="provider-desc">${escapeHtml(provider.description || '')}</div>
                    <div class="provider-meta">
                        <span class="provider-meta-item">Preview ${preview != null ? Number(preview).toFixed(3) : '—'}</span>
                        <span class="provider-meta-item">Full ${full != null ? Number(full).toFixed(3) : '—'}</span>
                    </div>
                    <div class="provider-owner" title="${escapeHtml(provider.owner_wallet || '')}">Owner ${shortAddress(provider.owner_wallet)}${provider.enabled === false ? ' · Disabled' : ''}</div>
                </button>
            `;
        }).join('');
        providerMarketplaceContainer.querySelectorAll('.provider-card').forEach((card) => {
            card.addEventListener('click', () => {
                currentProviderId = card.dataset.providerId || 'funding_memory';
                if (providerCatalog[currentProviderId]?.enabled === false) {
                    showToast(`${currentProviderId} is currently disabled by admin.`, 'warning');
                    return;
                }
                if (providerSelect) providerSelect.value = currentProviderId;
                providerMarketplaceContainer.querySelectorAll('.provider-card').forEach((el) => el.classList.remove('active'));
                card.classList.add('active');
                quotedPrices = { preview: null, full: null };
                scheduleQuotedPriceRefresh();
                showToast(`Provider selected: ${providerCatalog[currentProviderId]?.provider_name || currentProviderId}`, 'info');
            });
        });
        updateTierPriceLabels();
        await refreshQuotedPrices();
    } catch (err) {
        console.warn('Provider marketplace unavailable', err);
        if (providerMarketplaceContainer) {
            providerMarketplaceContainer.innerHTML = '<div class="agent-empty">Provider marketplace unavailable.</div>';
        }
    }
}

const metricsPendingEl = document.getElementById('metrics-balance-pending');

async function loadPlatformPayments(page = paymentActivityPage) {
    try {
        const params = new URLSearchParams({
            page: String(page),
            page_size: String(PAYMENT_ACTIVITY_PAGE_SIZE)
        });
        const resp = await fetch(apiUrl(`/api/v1/platform/payments?${params.toString()}`));
        if (!resp.ok) return;
        const data = await resp.json();
        renderPaymentActivity(data.recent_payments || []);
        const paymentMeta = fallbackPageMeta(
            data.recent_payments_page,
            page,
            PAYMENT_ACTIVITY_PAGE_SIZE,
            (data.recent_payments || []).length,
            (data.recent_payments || []).length
        );
        paymentActivityPage = Number(paymentMeta.page || page || 1);
        paymentActivityTotalPages = Number(paymentMeta.total_pages || 1);
        updatePagerControls('payment', paymentMeta);
    } catch (err) {
        console.warn('Platform payments unavailable', err);
    }
}

async function loadPlatformPayers(page = payerBreakdownPage) {
    try {
        const params = new URLSearchParams({
            page: String(page),
            page_size: String(PAYER_BREAKDOWN_PAGE_SIZE)
        });
        const resp = await fetch(apiUrl(`/api/v1/platform/payers?${params.toString()}`));
        if (!resp.ok) return;
        const data = await resp.json();
        renderPayerBreakdown(data.payer_breakdown || []);
        const payerMeta = fallbackPageMeta(
            data.payer_breakdown_page,
            page,
            PAYER_BREAKDOWN_PAGE_SIZE,
            (data.payer_breakdown || []).length,
            (data.payer_breakdown || []).length
        );
        payerBreakdownPage = Number(payerMeta.page || page || 1);
        payerBreakdownTotalPages = Number(payerMeta.total_pages || 1);
        updatePagerControls('payer', payerMeta);
    } catch (err) {
        console.warn('Platform payer breakdown unavailable', err);
    }
}

async function loadMetrics() {
    try {
        const resp = await fetch(apiUrl('/api/v1/platform/summary'));
        if (!resp.ok) return;
        const data = await resp.json();
        const tierCounts = data.tier_counts || {};
        const legacyCount = Number(tierCounts.legacy || 0);
        const currentPaid = data.current_paid_count ?? data.paid_count ?? 0;
        metricsPayments.textContent = `Paid: ${currentPaid} (P:${tierCounts.preview || 0} F:${tierCounts.full || 0}${legacyCount ? ` L:${legacyCount}` : ''})`;
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

        const paymentChanged = data.last_payment_key && data.last_payment_key !== lastPlatformPaymentKey;
        const shouldRefreshTables = !platformTablesLoaded || (paymentChanged && paymentActivityPage === 1);
        lastPlatformPaymentKey = data.last_payment_key || lastPlatformPaymentKey;
        if (shouldRefreshTables) {
            await Promise.all([
                loadPlatformPayments(paymentActivityPage),
                loadPlatformPayers(payerBreakdownPage)
            ]);
            platformTablesLoaded = true;
        }
    } catch (err) {
        console.warn('Metrics unavailable', err);
    }
}

async function loadHealthInfo() {
    try {
        const resp = await fetch(apiUrl('/api/v1/config'));
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
                    preview: Number(data.pricing.preview_base_usdc ?? data.pricing.preview_usdc ?? pricingConfig.preview),
                    full: Number(data.pricing.full_base_usdc ?? data.pricing.full_usdc ?? pricingConfig.full),
                };
            }
            if (data.gateway_deposit) {
                gatewayDepositConfig = {
                    default_usdc: Number(data.gateway_deposit.default_usdc ?? gatewayDepositConfig.default_usdc),
                    default_approve_usdc: Number(data.gateway_deposit.default_approve_usdc ?? gatewayDepositConfig.default_approve_usdc),
                };
            }
            updateTierPriceLabels();
            await refreshQuotedPrices();
            if (gatewayContractAddress) {
                setPaymentDetailValue('pf-gateway-contract', gatewayContractAddress);
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
        const metricsResp = await fetch(apiUrl(`/api/v1/wallets/${connectedWallet}/summary`));
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

            const signature = await walletRequest(
                {
                    method: 'eth_signTypedData_v4',
                    params: [connectedWallet, msgParams]
                },
                'Gateway withdrawal signature'
            );

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

            const txHash = await walletRequest(
                {
                    method: 'eth_sendTransaction',
                    params: [{
                        from: connectedWallet,
                        to: gatewayMinter,
                        data: mintCalldata,
                        gas: '0x493e0'
                    }]
                },
                'Gateway withdrawal mint'
            );

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
        const isFinalStatus = ['completed', 'confirmed'].includes(String(event.gateway_status || '').toLowerCase());
        const missingTxLabel = isFinalStatus ? 'Arcscan tx unavailable' : 'Arcscan tx pending';
        const missingTxColor = isFinalStatus ? 'var(--text-dark)' : '#f59e0b';
        const ref = event.explorer_url && event.transaction_hash
            ? `<a class="tx-link" href="${event.explorer_url}" target="_blank" rel="noreferrer" title="Settlement: ${escapeHtml(event.settlement_id || '')}">${shortAddress(event.transaction_hash)}</a>`
            : event.settlement_id
                ? `<span class="mono-td" title="Settlement ID: ${escapeHtml(event.settlement_id)}">${shortAddress(event.settlement_id)}</span><div style="color:${missingTxColor}; font-size:0.72rem; margin-top:2px;">${escapeHtml(missingTxLabel)}</div>`
                : '<span style="color: var(--text-dark);">n/a</span>';
        return `
                    <tr>
                        <td class="mono-td">${escapeHtml(event.symbol || 'n/a')}<div style="color:var(--t3); font-size:0.66rem; margin-top:2px;">${escapeHtml(formatDateTime(event.paid_at))}</div></td>
                        <td title="${escapeHtml(event.payer_address || '')}">${shortAddress(event.payer_address)}</td>
                        <td>${Number(event.amount_usdc || 0).toFixed(3)} USDC<div style="color:var(--t3); font-size:0.66rem;">${escapeHtml(tierLabel(event.tier_category || event.tier || 'legacy'))}</div></td>
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

function resolveActiveQuery() {
    if (isBasicView() && activeQuery) {
        return normalizeSignalPayload(activeQuery);
    }
    return normalizeSignalPayload(getFormQuery());
}

function syncFormFromSignal(signal) {
    const payload = normalizeSignalPayload(signal);
    fSymbol.value = payload.symbol;
    fFunding.value = Number(payload.fundingRate).toFixed(4);
    fMcap.value = Math.round(payload.marketCap);
    fFdv.value = Math.round(payload.FDV);
    fCirc.value = Number(payload.circRatio).toFixed(2);
    fAth.value = Number(payload.fromATH).toFixed(2);
    fVol.value = Math.round(payload.volume24h);
}

function applySignalToState(signal) {
    const normalized = normalizeSignalPayload(signal);
    activeQuery = normalized;
    if (!isBasicView()) {
        syncFormFromSignal(normalized);
    }
    updateBasicSignalCard(normalized);
    scheduleQuotedPriceRefresh();
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

function hidePaywall() {
    paywallElement.style.display = 'none';
    paywallElement.classList.remove('compact-paywall');
    resetPaywallSuccessState();
    currentInvoiceId = null;
    currentInvoiceSecret = null;
    currentArcGatewayUrl = null;
    currentSettlementId = null;
    currentSellerAddress = null;
    currentAccessToken = null;
    document.getElementById('inv-id-row').style.display = 'none';
    document.getElementById('payment-flow-panel').style.display = 'none';
    setPaymentDetailValue('inv-id-display', null);
    setPaymentDetailValue('pf-settlement-id', null);
    setPaymentDetailValue('pf-gateway-contract', null);
    setPaymentDetailValue('pf-seller-wallet-addr', null);
    setPaymentDetailValue('pf-buyer-gateway-bal', null);
    setPaymentDetailValue('pf-seller-available', null);
    setPaymentDetailValue('pf-seller-pending', null);
    setPaymentDetailValue('pf-wallet-address', null);
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
    resetPaywallSuccessState();
    resetPaymentDetailPanel();
    paywallTitle.textContent = options.title || (isBasicView() ? 'Unlock Historical Comparison' : 'USDC Micro-Payment Required');
    paywallDesc.textContent = options.description || (
        isBasicView()
            ? 'This exact live snapshot has not been purchased yet. Create an invoice to see how similar historical events performed.'
            : 'This exact signal snapshot has not been purchased. Create a paid invoice to unlock the historical analog report for these current inputs.'
    );
    invoiceSignalDisplay.textContent = displaySignalLabel(signal);
    document.getElementById('invoice-amount-display').textContent = formatTierPrice(tier);
    document.getElementById('invoice-tier-display').textContent = tierLabel(tier);
    document.getElementById('invoice-network-display').textContent = 'Arc Testnet';
    document.getElementById('inv-id-row').style.display = 'none';
    document.getElementById('payment-flow-panel').style.display = 'none';
    payButton.innerHTML = `<span>Create ${tierLabel(tier)} Invoice First</span>`;
    paywallElement.style.display = 'flex';
    paywallElement.classList.remove('compact-paywall');
    ensurePaywallTrustLayer();
}

function loadCardIntoForm(item) {
    const signal = formSignalFromAnomaly(item);
    applySignalToState(signal);
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
        showSignalPaywall(signal, {
            tier: 'full',
            title: isBasicView() ? 'Unlock Historical Comparison' : 'Signal Not Purchased',
            description: isBasicView()
                ? `This live signal has not been purchased yet. Choose Summary or Full Report below.`
                : 'This Live Anomaly snapshot is not unlocked yet. Click Retrieve Analogs to create a paid invoice for this exact signal.'
        });
    }
}

function lockViewport() {
    paywallElement.style.display = 'flex';
    paywallElement.classList.remove('compact-paywall');
    resetPaywallSuccessState();
    if (!hasUnlockedReport) {
        document.getElementById('viewport-container').classList.remove('unlocked');
    }
    currentInvoiceId = null;
    currentInvoiceSecret = null;
    currentArcGatewayUrl = null;
    currentSettlementId = null;
    currentSellerAddress = null;
    currentAccessToken = null;
    resetPaymentDetailPanel();
    invoiceSignalDisplay.textContent = activeQuery ? displaySignalLabel(activeQuery) : 'n/a';
    document.getElementById('invoice-amount-display').textContent = formatTierPrice(currentInvoiceTier);
    document.getElementById('invoice-tier-display').textContent = tierLabel(currentInvoiceTier);
    const lockPayAmount = tierPrice(currentInvoiceTier);
    payButton.innerHTML = lockPayAmount != null
        ? `<span>Pay ${lockPayAmount.toFixed(3)} USDC</span>`
        : '<span>Pay on Arc Testnet</span>';
    document.getElementById('inv-id-row').style.display = 'none';
    document.getElementById('payment-flow-panel').style.display = 'none';
}

// Trigger retrieval (Creates payment invoice)
queryForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    const invoiceBuyerType = nextInvoiceBuyerType === 'agent' ? 'agent' : 'human';
    nextInvoiceBuyerType = 'human';
    activeQuery = resolveActiveQuery();
    currentProviderId = providerSelect?.value || currentProviderId || 'funding_memory';
    currentInvoiceTier = normalizeTier(e.submitter?.dataset?.tier || 'full');
    await refreshQuotedPrices(activeQuery);
    currentInvoiceAmount = tierPrice(currentInvoiceTier);
    if (!Number.isFinite(currentInvoiceAmount) || currentInvoiceAmount <= 0) {
        showToast('Could not quote price for this signal. Check the API and retry.', 'error');
        return;
    }
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
                buyer_type: invoiceBuyerType,
                tier: currentInvoiceTier,
                resource_type: 'qma_signal_report'
            })
        });
        const invoiceData = await invoiceResp.json();
        if (!invoiceResp.ok) {
            throw new Error(apiErrorMessage(invoiceData, `Invoice endpoint returned ${invoiceResp.status}`));
        }

        currentInvoiceId = invoiceData.invoice_id;
        currentInvoiceSecret = invoiceData.invoice_secret;
        currentArcGatewayUrl = invoiceData.arc_gateway_url;
        currentInvoiceAmount = Number(invoiceData.amount);
        currentInvoiceTier = normalizeTier(invoiceData.tier || currentInvoiceTier);
        currentProviderId = invoiceData.provider_id || currentProviderId;
        currentInvoiceBuyerType = invoiceData.buyer_type || invoiceBuyerType;
        currentSellerAddress = invoiceData.wallet_address;
        if (currentInvoiceBuyerType === 'agent') {
            appendAgentRunTrace(`Invoice ${shortAddress(currentInvoiceId)} ready: ${Number(invoiceData.amount).toFixed(3)} USDC via ${invoiceData.provider_id}.`, 'success');
            appendAgentRunTrace('Payment panel is ready behind this modal. Close the modal to sign x402 with the connected wallet.');
            appendAgentRunTrace('CLI live mode can run the same payment loop fully autonomously with AGENT_PRIVATE_KEY.');
            if (agentRunDismiss) agentRunDismiss.textContent = 'Continue to Payment';
        }
        setPaymentDetailValue('inv-id-display', currentInvoiceId);
        document.getElementById('inv-id-row').style.display = 'grid';
        invoiceSignalDisplay.textContent = displaySignalLabel(activeQuery);
        paywallTitle.textContent = `${tierLabel(currentInvoiceTier)} Payment Required`;
        if (isBasicView()) {
            paywallDesc.textContent = currentInvoiceTier === 'preview'
                ? `Unlock a short summary for ${activeQuery?.symbol || 'this token'} showing how similar past events performed.`
                : `Unlock the full historical comparison for ${activeQuery?.symbol || 'this token'}. Each new live snapshot needs its own purchase.`;
        } else {
            paywallDesc.textContent = currentInvoiceTier === 'preview'
                ? `Unlock a lightweight ${invoiceData.provider_name || 'QMA'} preview for this exact live signal. Upgrade to the full report for all analogs, percentiles, and diagnostics.`
                : `Unlock this exact full ${invoiceData.provider_name || 'QMA'} signal snapshot. If the token changes later, QMA treats that as a new signal and requires a new paid report.`;
        }
        document.getElementById('invoice-amount-display').textContent = `${invoiceData.amount} ${invoiceData.currency}`;
        document.getElementById('invoice-tier-display').textContent = invoiceData.tier_label || tierLabel(currentInvoiceTier);
        document.getElementById('invoice-network-display').textContent = invoiceData.network_name || invoiceData.network;
        payButton.innerHTML = `<span>Pay ${Number(invoiceData.amount).toFixed(3)} USDC</span>`;

        const pfPanel = document.getElementById('payment-flow-panel');
        if (pfPanel) {
            pfPanel.style.display = 'block';
        }
        setPaymentDetailValue('pf-seller-wallet-addr', invoiceData.wallet_address);
        // Gateway contract address
        setPaymentDetailValue('pf-gateway-contract', gatewayContractAddress || 'Circle Gateway Contract (fetching...)');
        setPaymentDetailValue('pf-wallet-address', connectedWallet);

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
        if (invoiceBuyerType === 'agent') {
            appendAgentRunTrace(`Invoice creation failed: ${err.message || err}`, 'error');
        }
        alert(`Failed to initiate micro-payment invoice: ${err.message || err}`);
    }
});

// Circle Gateway x402 payment on Arc Testnet
payButton.addEventListener('click', async () => {
    if (paymentSuccessReady) {
        hidePaywall();
        return;
    }
    if (!currentInvoiceId) {
        alert("Please submit the query first to generate an invoice.");
        return;
    }
    if (!currentArcGatewayUrl) {
        alert("Arc Gateway URL is missing. Create a new invoice.");
        return;
    }
    if (!window.ethereum) {
        if (isMobileDevice()) {
            openMobileWalletModal();
        } else {
            _showDesktopInstallPrompt();
        }
        return;
    }

    payButton.disabled = true;
    payButton.innerHTML = `
                <div class="spinner" style="width: 16px; height: 16px;"></div>
                <span>Preparing wallet...</span>
            `;

    let account = null;
    try {
        const provider = await getWalletProvider();
        const accounts = await withTimeout(
            provider.request({ method: 'eth_accounts' }),
            15000,
            'Wallet account lookup'
        );
        account = accounts && accounts[0] ? accounts[0] : connectedWallet;
        if (!account) {
            payButton.innerHTML = `
                        <div class="spinner" style="width: 16px; height: 16px;"></div>
                        <span>Open EVM wallet to connect...</span>
                    `;
            account = await connectWallet({ notify: false });
        }
        if (!account) {
            throw new Error('Connect a buyer wallet first.');
        }
        if (!sameAddress(account, connectedWallet)) {
            setConnectedWallet(account);
        }
        const currentChainId = provider?.request
            ? await withTimeout(provider.request({ method: 'eth_chainId' }), 15000, 'Payment chain check')
            : null;
        if (currentChainId && normalizeChainId(currentChainId) !== ARC_TESTNET_HEX) {
            payButton.innerHTML = `
                        <div class="spinner" style="width: 16px; height: 16px;"></div>
                        <span>Switch to Arc Testnet in your wallet...</span>
                    `;
            showToast(`Wrong network: ${formatChainLabel(currentChainId)}. Please approve the switch to Arc Testnet.`, 'info');
        }
        await ensureArcTestnet();
        await sleep(250);
        if (sameAddress(account, currentSellerAddress)) {
            throw new Error(`Connected wallet is the seller wallet (${currentSellerAddress}). Circle rejects self-transfer payments. Switch network to a buyer wallet such as acc1, or set QMA_ARC_SELLER_ADDRESS to a separate treasury wallet.`);
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
            const depositAmount = await requestDepositAmount({
                account,
                gatewayBalance,
                walletBalance: walletBal,
                requiredPayment: currentInvoiceAmount,
                walletStatus,
            });
            if (!depositAmount) {
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
        const signature = await walletRequest(
            {
                method: 'eth_signTypedData_v4',
                params: [account, JSON.stringify(typedData)]
            },
            'x402 payment authorization'
        );

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
        if (currentInvoiceBuyerType === 'agent') {
            appendAgentRunTrace(`x402 settlement accepted: ${shortAddress(currentSettlementId)}.`, 'success');
        }
        saveWalletEvent(account, {
            type: 'x402_settlement',
            amount_usdc: paidData.amount_usdc || currentInvoiceAmount,
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
            if (currentInvoiceBuyerType === 'agent') {
                appendAgentRunTrace(`QMA verified agent payment. Access token issued for ${tierLabel(currentInvoiceTier)} report.`, 'success');
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
            showPaymentUnlockingState();
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
            if (currentInvoiceBuyerType === 'agent') {
                appendAgentRunTrace(`Paid report returned for ${activeQuery.symbol}. Agent run complete.`, 'success');
            }

            if (currentInvoiceTier === 'preview') {
                renderPreviewReport(reportData);
            } else {
                renderReport(reportData);
            }
            showPaymentSuccessState();
            updateAnomalyPaidState(activeQuery);
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
                cancelMessage = "Gateway balance is insufficient. Open Funding Assistant to check Arc USDC, use Faucet or CCTP/App Kit funding if needed, then retry payment. QMA will prompt Gateway Deposit during checkout.";
            } else if (err.message?.includes('User rejected')) {
                cancelMessage = "Wallet signature rejected — no funds sent";
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
        if (!paymentSuccessReady) {
            payButton.disabled = false;
            const resetPayAmount = tierPrice(currentInvoiceTier);
            payButton.innerHTML = resetPayAmount != null
                ? `<span>Pay ${resetPayAmount.toFixed(3)} USDC</span>`
                : '<span>Pay on Arc Testnet</span>';
        }
    }
});

/**
 * updatePaymentFlowPanel — updates the 4-level payment flow panel.
 * stages: 'created' | 'checking' | 'received' | 'completed' | 'cancelled'
 */
function updatePaymentFlowPanelLegacy(opts = {}) {
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

function updatePaymentFlowPanel(opts = {}) {
    const { stage = 'created', buyerWalletBal, buyerGatewayBal, settlementId, gatewayStatus, sellerAvailable, sellerPending, sellerWallet, txHash, explorerUrl, cancelMessage } = opts;
    updatePaymentTimeline(stage, cancelMessage);
    setPaymentDetailValue('pf-wallet-address', connectedWallet);

    const pfBuyerWalletBal = document.getElementById('pf-buyer-wallet-bal');
    if (pfBuyerWalletBal) {
        if (buyerWalletBal != null) {
            pfBuyerWalletBal.textContent = `Connected - wallet balance ${Number(buyerWalletBal).toFixed(6)} USDC`;
        } else if (connectedWallet) {
            pfBuyerWalletBal.textContent = `Connected - ${shortAddress(connectedWallet)}`;
        } else {
            pfBuyerWalletBal.textContent = 'Connect wallet to continue.';
        }
    }

    if (buyerGatewayBal != null) {
        setPaymentDetailValue('pf-buyer-gateway-bal', `${Number(buyerGatewayBal).toFixed(6)} USDC`);
    } else if (stage === 'created') {
        setPaymentDetailValue('pf-buyer-gateway-bal', null);
    }

    const pfGatewayStepText = document.getElementById('pf-gateway-step-text');
    if (pfGatewayStepText) {
        if (stage === 'checking') {
            pfGatewayStepText.textContent = buyerGatewayBal != null
                ? `Gateway balance checked: ${Number(buyerGatewayBal).toFixed(6)} USDC`
                : 'Checking Gateway balance...';
        } else if (stage === 'received' || stage === 'completed') {
            pfGatewayStepText.textContent = 'USDC payment authorization accepted.';
        } else if (stage === 'cancelled') {
            pfGatewayStepText.textContent = cancelMessage || 'Payment cancelled before settlement.';
        } else {
            pfGatewayStepText.textContent = 'Gateway balance is checked when you pay.';
        }
    }

    const pfStatus = document.getElementById('pf-settlement-status');
    if (pfStatus) {
        if (stage === 'received') {
            pfStatus.textContent = 'Circle accepted payment. Waiting for on-chain batch.';
        } else if (stage === 'completed') {
            pfStatus.textContent = 'Settlement complete.';
        } else if (stage === 'checking') {
            pfStatus.textContent = 'Preparing signature and settlement.';
        } else if (stage === 'cancelled') {
            pfStatus.textContent = cancelMessage || 'Payment cancelled. No funds sent.';
        } else {
            pfStatus.textContent = 'Awaiting payment.';
        }
    }

    if (settlementId) {
        setPaymentDetailValue('pf-settlement-id', settlementId);
    } else if (stage === 'created' || stage === 'checking' || stage === 'cancelled') {
        setPaymentDetailValue('pf-settlement-id', null);
    }

    if (sellerAvailable != null) setPaymentDetailValue('pf-seller-available', `${Number(sellerAvailable).toFixed(6)} USDC`);
    if (sellerPending != null) setPaymentDetailValue('pf-seller-pending', `${Number(sellerPending).toFixed(6)} USDC`);
    if (sellerWallet) setPaymentDetailValue('pf-seller-wallet-addr', sellerWallet);

    const unlockStatus = document.getElementById('pf-unlock-status');
    if (unlockStatus && gatewayStatus && stage !== 'completed') {
        unlockStatus.textContent = `Gateway status: ${gatewayStatus}`;
    }

    const pfArcscanRow = document.getElementById('pf-arcscan-tx');
    const pfArcscanLink = document.getElementById('pf-arcscan-link');
    if (txHash && explorerUrl && pfArcscanRow && pfArcscanLink) {
        pfArcscanLink.href = explorerUrl;
        pfArcscanLink.textContent = shortAddress(txHash);
        pfArcscanLink.title = txHash;
        pfArcscanLink.dataset.fullValue = txHash;
        pfArcscanLink.dataset.hasFull = 'true';
        pfArcscanRow.style.display = 'grid';
    } else if (stage === 'created' || stage === 'checking' || stage === 'cancelled') {
        if (pfArcscanRow) pfArcscanRow.style.display = 'none';
    }
}

function normalizeEntitlementReport(entry = {}) {
    if (!entry.report) return null;
    return {
        ...entry.report,
        tier: entry.tier || entry.report.tier || entry.report.invoice?.tier || 'full',
        provider_id: entry.provider_id || entry.report.provider_id || entry.report.invoice?.provider_id || 'funding_memory',
        query: entry.query || entry.report.query,
        paid_at: entry.paid_at || entry.report.paid_at,
        invoice: {
            ...(entry.report.invoice || {}),
            tier: entry.tier || entry.report.invoice?.tier,
            provider_id: entry.provider_id || entry.report.invoice?.provider_id,
            amount_usdc: entry.amount_usdc ?? entry.report.invoice?.amount_usdc,
            settlement_id: entry.settlement_id || entry.report.invoice?.settlement_id,
            transaction_hash: entry.transaction_hash || entry.report.invoice?.transaction_hash,
            explorer_url: entry.explorer_url || entry.report.invoice?.explorer_url,
            gateway_status: entry.gateway_status || entry.report.invoice?.gateway_status,
            payer_address: entry.payer_address || entry.report.invoice?.payer_address,
        }
    };
}

function entitlementId(entry = {}) {
    return entry.entitlement_id || entry.query_hash || entry.settlement_id || `${entry.symbol || 'report'}-${entry.paid_at || entry.saved_at || ''}`;
}

function findEntitlementForPayment(payment = {}, entitlements = []) {
    if (!payment || !Array.isArray(entitlements)) return null;
    const bySettlement = payment.settlement_id
        ? entitlements.find(entry => entry.settlement_id && entry.settlement_id === payment.settlement_id)
        : null;
    if (bySettlement) return bySettlement;
    const byInvoice = payment.invoice_id
        ? entitlements.find(entry => entry.report?.invoice?.invoice_id && entry.report.invoice.invoice_id === payment.invoice_id)
        : null;
    if (byInvoice) return byInvoice;
    const byQuery = payment.query_hash
        ? entitlements.find(entry => entry.query_hash && entry.query_hash === payment.query_hash)
        : null;
    if (byQuery) return byQuery;
    const symbol = String(payment.symbol || '').toUpperCase();
    const tier = normalizeTier(payment.tier_category || payment.tier || 'full');
    return entitlements.find((entry) => (
        String(entry.symbol || entry.query?.symbol || '').toUpperCase() === symbol
        && normalizeTier(entry.tier || entry.report?.tier || 'full') === tier
        && Math.abs(Number(entry.paid_at || 0) - Number(payment.paid_at || 0)) < 10
    )) || null;
}

function openPurchasedReport(entry = {}) {
    const report = normalizeEntitlementReport(entry);
    if (!report) {
        showToast('This purchase does not include a saved report snapshot yet.', 'warning');
        return;
    }
    const previousTier = currentInvoiceTier;
    const previousProvider = currentProviderId;
    currentInvoiceTier = normalizeTier(report.tier || entry.tier || 'full');
    currentProviderId = report.provider_id || entry.provider_id || previousProvider || 'funding_memory';
    activeQuery = normalizeSignalPayload(report.query || entry.query || { symbol: entry.symbol });
    const cachedEntry = saveCachedReport(report, entry.payer_address || connectedWallet);
    walletProfileModal.classList.remove('open');
    walletProfileModal.setAttribute('aria-hidden', 'true');
    if (currentInvoiceTier === 'preview') {
        renderPreviewReport(report, cachedEntry);
    } else {
        renderReport(report, cachedEntry);
    }
    currentInvoiceTier = previousTier;
    currentProviderId = previousProvider;
    showToast(`Opened paid ${tierLabel(report.tier)} ${activeQuery.symbol} snapshot from ${formatDateTime(entry.paid_at || entry.saved_at)}.`, 'success');
}

// Render report output
function renderPreviewReport(report, cachedEntry = null) {
    if (!report.query && cachedEntry?.signal) {
        report.query = normalizeSignalPayload(cachedEntry.signal);
    } else if (!report.query && activeQuery) {
        report.query = normalizeSignalPayload(activeQuery);
    }
    if (!cachedEntry) {
        cachedEntry = saveCachedReport(report);
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
        div.innerHTML = `<span style="color:var(--green);">Paid preview snapshot:</span> ${escapeHtml(displaySignalLabel(paidMeta.signal || activeQuery || report.query || { symbol: report.query_symbol }))} <span style="color:var(--t3);">- bought ${escapeHtml(formatDateTime(paidMeta.saved_at))}</span>`;
        riskList.appendChild(div);
    }
    const cta = document.createElement('div');
    cta.className = 'risk-item';
    cta.innerHTML = `<span style="color:#f59e0b;">Upgrade:</span> ${escapeHtml(report.upgrade_cta || 'Buy the full report for complete analog evidence.')}`;
    riskList.appendChild(cta);
    if (paidMeta?.previous_snapshot_for) {
        const div = document.createElement('div');
        div.className = 'risk-item';
        div.innerHTML = `<span style="color:#f59e0b;">Current live snapshot is different:</span> ${escapeHtml(displaySignalLabel(paidMeta.previous_snapshot_for))}`;
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
    updatePlainSummary(report, { preview: true });
}

function renderReport(report, cachedEntry = null) {
    if (!report.query && cachedEntry?.signal) {
        report.query = normalizeSignalPayload(cachedEntry.signal);
    } else if (!report.query && activeQuery) {
        report.query = normalizeSignalPayload(activeQuery);
    }
    if (!cachedEntry) {
        cachedEntry = saveCachedReport(report);
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
        div.innerHTML = `<span style="color:var(--green);">Paid signal snapshot:</span> ${escapeHtml(displaySignalLabel(paidMeta.signal || activeQuery || report.query || { symbol: report.query_symbol }))} <span style="color:var(--t3);">· bought ${escapeHtml(formatDateTime(paidMeta.saved_at))}</span>`;
        riskList.appendChild(div);
    }
    if (paidMeta?.previous_snapshot_for) {
        const div = document.createElement('div');
        div.className = 'risk-item';
        div.innerHTML = `<span style="color:#f59e0b;">Current live snapshot is different:</span> ${escapeHtml(displaySignalLabel(paidMeta.previous_snapshot_for))} <span style="color:var(--t3);">- click Retrieve Analogs to buy and unlock this current signal.</span>`;
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
    updatePlainSummary(report, { preview: false });
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
        handleConnectWalletClick();
        return;
    }
    walletMenu.classList.toggle('open');
});
walletProfileBtn.addEventListener('click', openWalletProfilePage);
if (walletQuickProfileBtn) walletQuickProfileBtn.addEventListener('click', openWalletProfile);
if (walletAgentRunBtn) walletAgentRunBtn.addEventListener('click', openAgentRunModal);
if (walletFundArcBtn) walletFundArcBtn.addEventListener('click', openFundArcModal);
walletDisconnectBtn.addEventListener('click', disconnectWallet);
paywallClose.addEventListener('click', () => {
    hidePaywall();
    showToast('Payment panel closed. Select another signal or click Retrieve to reopen it.', 'info');
});
if (paywallFundingAssistantBtn) paywallFundingAssistantBtn.addEventListener('click', openFundArcModal);
setupPaywallCopyButtons();

const copyBtn = document.getElementById('wallet-copy-btn');
if (copyBtn) {
    copyBtn.addEventListener('click', async () => {
        if (!connectedWallet) return;
        try {
            await navigator.clipboard.writeText(connectedWallet);
            copyBtn.classList.add('copied');
            copyBtn.title = 'Copied!';
            setTimeout(() => {
                copyBtn.classList.remove('copied');
                copyBtn.title = 'Copy address';
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
if (paymentPrevBtn) {
    paymentPrevBtn.addEventListener('click', () => {
        if (paymentActivityPage <= 1) return;
        paymentActivityPage -= 1;
        loadPlatformPayments(paymentActivityPage);
    });
}
if (paymentNextBtn) {
    paymentNextBtn.addEventListener('click', () => {
        if (paymentActivityPage >= paymentActivityTotalPages) return;
        paymentActivityPage += 1;
        loadPlatformPayments(paymentActivityPage);
    });
}
if (payerPrevBtn) {
    payerPrevBtn.addEventListener('click', () => {
        if (payerBreakdownPage <= 1) return;
        payerBreakdownPage -= 1;
        loadPlatformPayers(payerBreakdownPage);
    });
}
if (payerNextBtn) {
    payerNextBtn.addEventListener('click', () => {
        if (payerBreakdownPage >= payerBreakdownTotalPages) return;
        payerBreakdownPage += 1;
        loadPlatformPayers(payerBreakdownPage);
    });
}
if (profilePaymentsPrevBtn) {
    profilePaymentsPrevBtn.addEventListener('click', () => {
        if (!activeProfileWallet || profilePaymentsPage <= 1) return;
        loadProfilePaymentsPage(activeProfileWallet, profilePaymentsPage - 1);
    });
}
if (profilePaymentsNextBtn) {
    profilePaymentsNextBtn.addEventListener('click', () => {
        if (!activeProfileWallet || profilePaymentsPage >= profilePaymentsTotalPages) return;
        loadProfilePaymentsPage(activeProfileWallet, profilePaymentsPage + 1);
    });
}
document.querySelectorAll('[data-sidebar-panel] .sidebar-panel-toggle').forEach((header) => {
    const toggle = () => header.closest('[data-sidebar-panel]')?.classList.toggle('is-collapsed');
    header.addEventListener('click', toggle);
    header.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            toggle();
        }
    });
});
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
getInjectedProviderCandidates().forEach(({ provider }) => {
    if (!provider?.on) return;
    provider.on('accountsChanged', async (accounts) => {
        clearWalletProfileSession(connectedWallet);
        const account = accounts && accounts[0] ? accounts[0] : null;
        setConnectedWallet(account);
        hasUnlockedReport = false;
        document.getElementById('viewport-container').classList.remove('unlocked');
        loadLiveAnomalies();
    });
    provider.on('chainChanged', () => {
        updateWalletUi();
        if (fundArcModal?.classList.contains('open')) {
            refreshFundingReadiness();
        }
    });
});
restoreWalletSession();
loadProviders();
loadLiveAnomalies();
loadAgentRecommendations();
loadMetrics();
loadHealthInfo();
if (queryForm) {
    queryForm.addEventListener('input', () => {
        if (isBasicView() && document.body.classList.contains('basic-show-fields')) {
            try {
                activeQuery = normalizeSignalPayload(getFormQuery());
                updateBasicSignalCard(activeQuery);
            } catch (err) {
                /* ignore invalid partial input */
            }
        }
        scheduleQuotedPriceRefresh();
    });
    queryForm.addEventListener('change', () => {
        if (isBasicView() && document.body.classList.contains('basic-show-fields')) {
            try {
                activeQuery = normalizeSignalPayload(getFormQuery());
                updateBasicSignalCard(activeQuery);
            } catch (err) {
                /* ignore */
            }
        }
        scheduleQuotedPriceRefresh();
    });
}
setInterval(() => {
    if (document.hidden) return;
    loadMetrics();
}, 15000);
function refreshLiveWorkspace(options = {}) {
    loadLiveAnomalies(options);
    loadAgentRecommendations({ silent: options.silent });
}
if (refreshBtn) {
    refreshBtn.addEventListener('click', () => {
        refreshLiveWorkspace({ silent: false, preserveSelection: true });
    });
}
setInterval(() => {
    if (document.hidden) return;
    refreshLiveWorkspace({ silent: true, preserveSelection: true });
}, LIVE_FEED_REFRESH_MS);
if (agentRunBtn) {
    agentRunBtn.addEventListener('click', runAgentDecision);
}
if (agentRunClose) agentRunClose.addEventListener('click', closeAgentRunModal);
if (agentRunDismiss) agentRunDismiss.addEventListener('click', closeAgentRunModal);
if (agentRunModal) {
    agentRunModal.addEventListener('click', (event) => {
        if (event.target === agentRunModal) {
            closeAgentRunModal();
        }
    });
}
if (fundArcClose) fundArcClose.addEventListener('click', closeFundArcModal);
if (fundArcDismiss) fundArcDismiss.addEventListener('click', closeFundArcModal);
if (fundArcModal) {
    fundArcModal.addEventListener('click', (event) => {
        if (event.target === fundArcModal) {
            closeFundArcModal();
        }
    });
}
if (fundPrimaryAction) {
    fundPrimaryAction.addEventListener('click', async () => {
        const action = fundPrimaryAction.dataset.action;
        if (action === 'connect') {
            handleConnectWalletClick();
            setTimeout(refreshFundingReadiness, 900);
            return;
        }
        if (action === 'switch') {
            try {
                fundPrimaryAction.disabled = true;
                fundPrimaryAction.textContent = 'Switching...';
                await ensureArcTestnet();
                showToast('Arc Testnet selected. Refreshing funding readiness.', 'success');
                await refreshFundingReadiness();
            } catch (err) {
                console.warn('Arc switch failed', err);
                showToast(describeWalletError(err), 'error');
                await refreshFundingReadiness();
            }
            return;
        }
        if (action === 'refresh') {
            await refreshFundingReadiness();
            return;
        }
        if (action === 'faucet') {
            window.open('https://faucet.circle.com/', '_blank', 'noopener,noreferrer');
            return;
        }
        closeFundArcModal();
    });
}

const basicToggleFieldsBtn = document.getElementById('basic-toggle-fields-btn');
if (basicToggleFieldsBtn) {
    basicToggleFieldsBtn.addEventListener('click', () => {
        const expanded = document.body.classList.toggle('basic-show-fields');
        basicToggleFieldsBtn.textContent = expanded ? 'Hide technical fields' : 'Edit technical fields';
        if (expanded && activeQuery) {
            syncFormFromSignal(activeQuery);
        }
    });
}

viewModeButtons.forEach((button) => {
    button.addEventListener('click', () => setViewMode(button.dataset.viewMode));
});
try {
    const savedViewMode = localStorage.getItem('qma_view_mode');
    setViewMode(savedViewMode === 'advanced' ? 'advanced' : 'basic');
} catch (err) {
    setViewMode('basic');
}
updateBasicSignalCard();
