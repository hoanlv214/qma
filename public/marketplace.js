const API_BASE_URL = String(window.QMA_API_BASE_URL || '').replace(/\/$/, '');
let connectedMarketWallet = '';
let adminPublicConfig = null;
let adminProviders = [];
let adminApplications = [];

const APPLICATION_STATUS_COPY = {
    pending: 'Waiting for admin review.',
    approved: 'Approved for marketplace review. Runtime integration pending.',
    needs_changes: 'Admin requested changes.',
    rejected: 'Not approved.',
};

function apiUrl(path) {
    return `${API_BASE_URL}${path}`;
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
    const str = String(value || '');
    if (str.length <= 12) return str || 'n/a';
    return `${str.slice(0, 6)}...${str.slice(-4)}`;
}

function money(value) {
    if (value == null || !Number.isFinite(Number(value))) return '— USDC';
    return `${Number(value).toFixed(3)} USDC`;
}

function apiErrorMessage(data, fallback = 'Request failed') {
    const detail = data?.detail ?? data?.error ?? data?.message;
    if (Array.isArray(detail)) {
        return detail.map((item) => {
            const path = Array.isArray(item?.loc) ? item.loc.filter(part => part !== 'body').join('.') : '';
            const msg = item?.msg || item?.message || JSON.stringify(item);
            return path ? `${path}: ${msg}` : msg;
        }).join('; ');
    }
    if (detail && typeof detail === 'object') {
        return detail.msg || detail.message || JSON.stringify(detail);
    }
    return detail || fallback;
}

function normalizeAddress(value) {
    return String(value || '').trim().toLowerCase();
}

function apiFieldErrors(data) {
    const detail = data?.detail;
    if (!Array.isArray(detail)) return [];
    return detail.map((item) => {
        const loc = Array.isArray(item?.loc) ? item.loc.filter(part => part !== 'body') : [];
        return {
            field: loc[0] ? String(loc[0]) : '',
            message: item?.msg || item?.message || JSON.stringify(item),
        };
    }).filter(item => item.field && item.message);
}

function applicationStatusCopy(status) {
    return APPLICATION_STATUS_COPY[status] || APPLICATION_STATUS_COPY.pending;
}

function renderProviders(providers) {
    const container = document.getElementById('marketplace-provider-list');
    if (!container) return;
    const enabledProviders = (providers || []).filter((provider) => provider.enabled !== false);
    if (!enabledProviders.length) {
        container.innerHTML = '<div class="agent-empty">No providers registered yet.</div>';
        return;
    }
    container.innerHTML = enabledProviders.map((provider) => {
        const stats = provider.stats || {};
        const preview = provider.pricing?.preview?.amount_usdc;
        const full = provider.pricing?.full?.amount_usdc;
        const creatorShare = Number(provider.revenue_share_bps || stats.creator_share_bps || 8000) / 100;
        const status = provider.status || 'approved';
        const selectHref = `/app?provider=${encodeURIComponent(provider.provider_id)}`;
        return `
            <article class="marketplace-provider-card">
                <div class="marketplace-provider-top">
                    <div>
                        <span class="provider-status ${escapeHtml(status)}">${escapeHtml(status)}</span>
                        <h2>${escapeHtml(provider.provider_name || provider.provider_id)}</h2>
                        <p class="provider-id-line">${escapeHtml(provider.provider_id)}</p>
                    </div>
                    <a class="landing-secondary" href="${escapeHtml(selectHref)}">Select</a>
                </div>
                <p class="marketplace-provider-desc">${escapeHtml(provider.description || '')}</p>
                <div class="marketplace-stats-grid">
                    <div><span>Preview</span><strong>${money(preview)}</strong></div>
                    <div><span>Full</span><strong>${money(full)}</strong></div>
                    <div><span>Sales</span><strong>${Number(stats.payments || 0)}</strong></div>
                    <div><span>Revenue</span><strong>${money(stats.revenue_usdc)}</strong></div>
                    <div><span>Creator Earned</span><strong>${money(stats.creator_earned_usdc)}</strong></div>
                    <div><span>Creator Share</span><strong>${creatorShare.toFixed(0)}%</strong></div>
                </div>
                <div class="provider-owner marketplace-owner" title="${escapeHtml(provider.owner_wallet || '')}">
                    Owner wallet ${shortAddress(provider.owner_wallet)}
                </div>
                <div class="marketplace-symbols">
                    ${(stats.top_symbols || []).length
                        ? stats.top_symbols.map(item => `<span>${escapeHtml(item.symbol)} x${Number(item.payments || 0)}</span>`).join('')
                        : '<span>No sales yet</span>'}
                </div>
            </article>
        `;
    }).join('');
}

async function loadProviders() {
    const container = document.getElementById('marketplace-provider-list');
    if (container) container.innerHTML = '<div class="agent-empty">Loading providers...</div>';
    try {
        const resp = await fetch(apiUrl('/api/v1/providers'));
        const data = await resp.json();
        if (!resp.ok) throw new Error(apiErrorMessage(data, `API returned ${resp.status}`));
        renderProviders(data.providers || []);
    } catch (err) {
        if (container) {
            container.innerHTML = `<div class="agent-empty">Provider marketplace unavailable: ${escapeHtml(err.message || err)}</div>`;
        }
    }
}

async function connectCreatorWallet() {
    if (!window.ethereum?.request) {
        alert('EVM is required to connect a creator wallet.');
        return null;
    }
    const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' });
    const wallet = accounts && accounts[0] ? accounts[0] : null;
    setConnectedMarketWallet(wallet);
    return wallet;
}

function setConnectedMarketWallet(wallet) {
    connectedMarketWallet = wallet || '';
    const connectBtn = document.getElementById('market-connect-btn');
    const creatorWalletInput = document.getElementById('creator-wallet');
    if (connectBtn) {
        connectBtn.textContent = wallet ? shortAddress(wallet) : 'Connect Wallet';
    }
    if (wallet && creatorWalletInput && !creatorWalletInput.value) {
        creatorWalletInput.value = wallet;
    }
    updateAdminVisibility();
    loadCreatorApplications();
}

async function initConnectedMarketWallet() {
    if (!window.ethereum?.request) {
        updateAdminVisibility();
        return;
    }
    try {
        const accounts = await window.ethereum.request({ method: 'eth_accounts' });
        setConnectedMarketWallet(accounts && accounts[0] ? accounts[0] : '');
    } catch (err) {
        console.warn('Could not read connected marketplace wallet', err);
        updateAdminVisibility();
    }
}

function openCreatorApplicationModal() {
    const modal = document.getElementById('creator-application-modal');
    if (!modal) return;
    closeCreatorApplicationsModal();
    if (connectedMarketWallet) {
        const creatorWalletInput = document.getElementById('creator-wallet');
        if (creatorWalletInput && !creatorWalletInput.value) creatorWalletInput.value = connectedMarketWallet;
    }
    modal.hidden = false;
    document.body.classList.add('marketplace-modal-open');
    setTimeout(() => document.getElementById('creator-wallet')?.focus(), 0);
}

function closeCreatorApplicationModal() {
    const modal = document.getElementById('creator-application-modal');
    if (!modal) return;
    modal.hidden = true;
    document.body.classList.remove('marketplace-modal-open');
}

function openCreatorApplicationsModal() {
    const modal = document.getElementById('creator-applications-modal');
    if (!modal) return;
    closeCreatorApplicationModal();
    modal.hidden = false;
    document.body.classList.add('marketplace-modal-open');
    loadCreatorApplications();
}

function closeCreatorApplicationsModal() {
    const modal = document.getElementById('creator-applications-modal');
    if (!modal) return;
    modal.hidden = true;
    document.body.classList.remove('marketplace-modal-open');
}

function renderCreatorApplications(applications = []) {
    const container = document.getElementById('creator-applications-list');
    if (!container) return;
    if (!connectedMarketWallet) {
        container.innerHTML = '<div class="agent-empty">Connect wallet to view your creator applications.</div>';
        return;
    }
    if (!applications.length) {
        container.innerHTML = '<div class="agent-empty">No creator applications for this wallet yet.</div>';
        return;
    }
    container.innerHTML = applications.map((application) => {
        const status = application.status || 'pending';
        const runtimeStatus = application.runtime_status || 'application_only';
        return `
            <article class="creator-application-card">
                <div class="creator-application-card-top">
                    <div>
                        <h3>${escapeHtml(application.provider_name || application.provider_id)}</h3>
                        <div class="creator-application-meta">${escapeHtml(application.provider_id)} · ${escapeHtml(application.data_source || 'data source n/a')}</div>
                    </div>
                    <span class="provider-status ${escapeHtml(status)}">${escapeHtml(status)}</span>
                </div>
                <div class="creator-application-copy">${escapeHtml(applicationStatusCopy(status))}</div>
                <div class="creator-application-meta">Runtime: ${escapeHtml(runtimeStatus)} · Revenue wallet ${shortAddress(application.revenue_wallet || application.creator_wallet)}</div>
                ${application.admin_note ? `<div class="creator-application-meta">Admin note: ${escapeHtml(application.admin_note)}</div>` : ''}
            </article>
        `;
    }).join('');
}

async function loadCreatorApplications() {
    const container = document.getElementById('creator-applications-list');
    if (!container) return;
    if (!connectedMarketWallet) {
        renderCreatorApplications([]);
        return;
    }
    container.innerHTML = '<div class="agent-empty">Loading your creator applications...</div>';
    try {
        const params = new URLSearchParams({ wallet: connectedMarketWallet });
        const resp = await fetch(apiUrl(`/api/v1/creators/applications?${params.toString()}`));
        const data = await resp.json();
        if (!resp.ok) throw new Error(apiErrorMessage(data, `API returned ${resp.status}`));
        renderCreatorApplications(data.applications || []);
    } catch (err) {
        container.innerHTML = `<div class="agent-empty">Could not load creator applications: ${escapeHtml(err.message || err)}</div>`;
    }
}

function formValue(form, name) {
    return String(new FormData(form).get(name) || '').trim();
}

function clearCreatorFieldErrors(form) {
    form.querySelectorAll('.form-input.field-invalid').forEach((input) => input.classList.remove('field-invalid'));
    form.querySelectorAll('.field-error.is-visible').forEach((el) => {
        el.classList.remove('is-visible');
        if (el.dataset.dynamicError === 'true') {
            el.textContent = '';
        }
    });
}

function showCreatorFieldError(form, field, message) {
    const input = form.elements[field];
    const errorEl = form.querySelector(`[data-error-for="${field}"]`);
    if (input?.classList) input.classList.add('field-invalid');
    if (errorEl) {
        errorEl.textContent = message;
        errorEl.dataset.dynamicError = 'true';
        errorEl.classList.add('is-visible');
    }
    return input || null;
}

function showCreatorFieldErrors(form, errors = []) {
    let firstInput = null;
    errors.forEach(({ field, message }) => {
        const input = showCreatorFieldError(form, field, message);
        if (!firstInput && input?.focus) firstInput = input;
    });
    if (firstInput) firstInput.focus();
}

function validateCreatorPayload(payload) {
    if (!payload.creator_wallet || payload.creator_wallet.length < 8) {
        return { field: 'creator_wallet', message: 'Creator wallet is required.' };
    }
    if (!payload.provider_id || payload.provider_id.length < 3) {
        return { field: 'provider_id', message: 'Provider ID must be at least 3 characters after normalization.' };
    }
    if (!payload.provider_name || payload.provider_name.length < 3) {
        return { field: 'provider_name', message: 'Provider name must be at least 3 characters.' };
    }
    if (!payload.contact || payload.contact.length < 3) {
        return { field: 'contact', message: 'Contact must be at least 3 characters.' };
    }
    if (!payload.data_source || payload.data_source.length < 3) {
        return { field: 'data_source', message: 'Data source must be at least 3 characters.' };
    }
    if (!payload.description || payload.description.length < 20) {
        return { field: 'description', message: 'Description must be at least 20 characters. Explain what paid data or report this provider sells.' };
    }
    if (!Number.isFinite(payload.revenue_share_bps) || payload.revenue_share_bps < 1000 || payload.revenue_share_bps > 9500) {
        return { field: 'revenue_share_bps', message: 'Creator share must be between 10% and 95%.' };
    }
    return null;
}

async function submitCreatorApplication(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const statusEl = document.getElementById('creator-form-status');
    const submitBtn = form.querySelector('button[type="submit"]');
    clearCreatorFieldErrors(form);
    statusEl.textContent = 'Submitting creator application...';
    statusEl.className = 'creator-form-status';
    const payload = {
        creator_wallet: formValue(form, 'creator_wallet'),
        provider_id: formValue(form, 'provider_id').toLowerCase().replace(/[^a-z0-9_-]/g, '_'),
        provider_name: formValue(form, 'provider_name'),
        contact: formValue(form, 'contact'),
        category: 'market_memory',
        description: formValue(form, 'description'),
        data_source: formValue(form, 'data_source'),
        api_base_url: formValue(form, 'api_base_url') || null,
        sample_schema: formValue(form, 'sample_schema') || null,
        revenue_wallet: formValue(form, 'creator_wallet'),
        revenue_share_bps: Number(formValue(form, 'revenue_share_bps') || 8000),
    };
    const validationError = validateCreatorPayload(payload);
    if (validationError) {
        showCreatorFieldErrors(form, [validationError]);
        statusEl.classList.add('error');
        statusEl.textContent = validationError.message;
        return;
    }
    try {
        if (submitBtn) submitBtn.disabled = true;
        const resp = await fetch(apiUrl('/api/v1/creators/apply'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (!resp.ok) {
            const fieldErrors = apiFieldErrors(data);
            if (fieldErrors.length) {
                showCreatorFieldErrors(form, fieldErrors);
            }
            throw new Error(apiErrorMessage(data, `API returned ${resp.status}`));
        }
        statusEl.classList.add('success');
        statusEl.innerHTML = `Submitted. Application <strong>${escapeHtml(data.application.application_id)}</strong> is pending admin review.`;
        form.reset();
        if (payload.creator_wallet) document.getElementById('creator-wallet').value = payload.creator_wallet;
        if (normalizeAddress(payload.creator_wallet) === normalizeAddress(connectedMarketWallet)) {
            await loadCreatorApplications();
        }
    } catch (err) {
        statusEl.classList.add('error');
        statusEl.textContent = `Submission failed: ${err.message || err}`;
    } finally {
        if (submitBtn) submitBtn.disabled = false;
    }
}

function adminToken() {
    return String(document.getElementById('admin-token-input')?.value || sessionStorage.getItem('qma_admin_token') || '').trim();
}

function setAdminStatus(message, type = '') {
    const el = document.getElementById('admin-status');
    if (!el) return;
    el.className = `creator-form-status ${type}`.trim();
    el.textContent = message || '';
}

function isConnectedAdminWallet() {
    const connected = normalizeAddress(connectedMarketWallet);
    if (!connected || !adminPublicConfig) return false;
    return connected === normalizeAddress(adminPublicConfig.seller_wallet)
        || connected === normalizeAddress(adminPublicConfig.admin_wallet);
}

function hasAdminWriteAccess() {
    return isConnectedAdminWallet() && (!adminPublicConfig?.admin_token_required || Boolean(adminToken()));
}

async function loadAdminPublicConfig() {
    try {
        const resp = await fetch(apiUrl('/api/v1/admin/public-config'));
        const data = await resp.json();
        if (!resp.ok) {
            if (resp.status === 404) {
                const fallbackResp = await fetch(apiUrl('/api/v1/config'));
                const fallbackData = await fallbackResp.json();
                if (!fallbackResp.ok) throw new Error(apiErrorMessage(fallbackData, `API returned ${fallbackResp.status}`));
                adminPublicConfig = {
                    status: 'success',
                    seller_wallet: fallbackData.seller_wallet,
                    admin_wallet: fallbackData.seller_wallet,
                    admin_token_required: true,
                    fallback: true,
                };
                updateAdminVisibility();
                return;
            }
            throw new Error(apiErrorMessage(data, `API returned ${resp.status}`));
        }
        adminPublicConfig = data;
    } catch (err) {
        console.warn('Admin public config unavailable', err);
        adminPublicConfig = null;
    }
    updateAdminVisibility();
}

function updateAdminVisibility() {
    const section = document.getElementById('marketplace-admin-section');
    const gate = document.getElementById('marketplace-admin-gate');
    if (!section) return;
    const shouldShow = isConnectedAdminWallet();
    section.hidden = !shouldShow;
    if (gate) gate.hidden = true;
    if (shouldShow) {
        const fallbackNote = adminPublicConfig?.fallback
            ? ' Admin config route is missing; restart/redeploy the backend before review/toggle actions.'
            : '';
        const tokenNote = adminPublicConfig?.admin_token_configured === false
            ? ' QMA_ADMIN_TOKEN is not configured on the backend, so admin writes are disabled.'
            : ' Provider state is viewable; enter admin token to enable review/toggle actions.';
        setAdminStatus(`Seller/admin wallet connected.${tokenNote}${fallbackNote}`);
    }
}

function renderAdminProviders(providers = []) {
    const container = document.getElementById('admin-provider-list');
    if (!container) return;
    const canWrite = hasAdminWriteAccess();
    if (!providers.length) {
        container.innerHTML = '<div class="agent-empty">No providers found.</div>';
        return;
    }
    container.innerHTML = providers.map((provider) => {
        const enabled = provider.enabled !== false;
        const status = enabled ? 'enabled' : 'disabled';
        const buttonLabel = enabled ? 'Disable plugin' : 'Enable plugin';
        return `
            <article class="admin-card" data-admin-provider-id="${escapeHtml(provider.provider_id)}">
                <div class="admin-card-top">
                    <div>
                        <h3 class="admin-card-title">${escapeHtml(provider.provider_name || provider.provider_id)}</h3>
                        <div class="admin-card-meta">${escapeHtml(provider.provider_id)} · ${escapeHtml(provider.plugin_type || 'builtin')}</div>
                    </div>
                    <span class="provider-status ${enabled ? 'approved' : 'rejected'}">${status}</span>
                </div>
                <div class="admin-card-desc">${escapeHtml(provider.description || '')}</div>
                <div class="admin-card-meta">Owner ${shortAddress(provider.owner_wallet)} · Preview ${money(provider.pricing?.preview?.amount_usdc)} · Full ${money(provider.pricing?.full?.amount_usdc)}</div>
                <input class="admin-note-input" data-provider-note placeholder="${canWrite ? 'Admin note for this toggle' : 'Enter admin token to write'}" ${canWrite ? '' : 'disabled'}>
                <div class="admin-actions">
                    <button type="button" class="admin-action-btn ${enabled ? 'danger' : 'success'}" data-toggle-provider="${escapeHtml(provider.provider_id)}" data-next-enabled="${enabled ? 'false' : 'true'}" ${canWrite ? '' : 'disabled title="Admin token required"'}>${buttonLabel}</button>
                </div>
            </article>
        `;
    }).join('');
    container.querySelectorAll('[data-toggle-provider]').forEach((button) => {
        button.addEventListener('click', () => toggleProviderPlugin(button));
    });
}

function renderAdminApplications(applications = []) {
    const container = document.getElementById('admin-application-list');
    if (!container) return;
    const canWrite = hasAdminWriteAccess();
    if (!applications.length) {
        container.innerHTML = adminPublicConfig?.admin_token_required && !adminToken()
            ? '<div class="agent-empty">Enter admin token to load creator applications.</div>'
            : '<div class="agent-empty">No creator applications yet.</div>';
        return;
    }
    container.innerHTML = applications.map((application) => {
        const status = application.status || 'pending';
        return `
            <article class="admin-card" data-application-id="${escapeHtml(application.application_id)}">
                <div class="admin-card-top">
                    <div>
                        <h3 class="admin-card-title">${escapeHtml(application.provider_name || application.provider_id)}</h3>
                <div class="admin-card-meta">${escapeHtml(application.provider_id)} · ${escapeHtml(application.data_source || 'data source n/a')}</div>
                    </div>
                    <span class="provider-status ${escapeHtml(status)}">${escapeHtml(status)}</span>
                </div>
                <div class="admin-card-desc">${escapeHtml(application.description || '')}</div>
                <div class="admin-card-desc">${escapeHtml(applicationStatusCopy(status))}</div>
                <div class="admin-card-meta">Creator ${shortAddress(application.creator_wallet)} · Share ${Number(application.revenue_share_bps || 8000) / 100}% · Runtime ${escapeHtml(application.runtime_status || 'application_only')} · Contact ${escapeHtml(application.contact || 'n/a')}</div>
                <input class="admin-note-input" data-application-note placeholder="${canWrite ? 'Admin note' : 'Enter admin token to write'}" ${canWrite ? '' : 'disabled'}>
                <div class="admin-actions">
                    <button type="button" class="admin-action-btn success" data-review-status="approved" ${canWrite ? '' : 'disabled title="Admin token required"'}>Approve</button>
                    <button type="button" class="admin-action-btn" data-review-status="needs_changes" ${canWrite ? '' : 'disabled title="Admin token required"'}>Needs changes</button>
                    <button type="button" class="admin-action-btn danger" data-review-status="rejected" ${canWrite ? '' : 'disabled title="Admin token required"'}>Reject</button>
                </div>
            </article>
        `;
    }).join('');
    container.querySelectorAll('[data-review-status]').forEach((button) => {
        button.addEventListener('click', () => reviewCreatorApplication(button));
    });
}

async function loadAdminData() {
    const token = adminToken();
    const tokenInput = document.getElementById('admin-token-input');
    if (tokenInput && token) tokenInput.value = token;
    if (!isConnectedAdminWallet()) {
        setAdminStatus('Connect the seller/admin wallet first.', 'error');
        return;
    }
    if (token) sessionStorage.setItem('qma_admin_token', token);
    setAdminStatus('Loading admin data...');
    try {
        const headers = token ? { 'X-QMA-Admin-Token': token } : {};
        const canLoadApplications = !adminPublicConfig?.admin_token_required || Boolean(token);
        const providerPath = canLoadApplications
            ? '/api/v1/providers?include_disabled=true'
            : '/api/v1/providers';
        const [providerResp, appResp] = await Promise.all([
            fetch(apiUrl(providerPath), { headers }),
            canLoadApplications
                ? fetch(apiUrl('/api/v1/creators/applications'), { headers })
                : Promise.resolve(null),
        ]);
        const providerData = await providerResp.json();
        const appData = appResp ? await appResp.json() : { applications: [] };
        if (!providerResp.ok) throw new Error(apiErrorMessage(providerData, `Providers returned ${providerResp.status}`));
        if (appResp && !appResp.ok) throw new Error(apiErrorMessage(appData, `Applications returned ${appResp.status}`));
        adminProviders = providerData.providers || [];
        adminApplications = appData.applications || [];
        renderAdminProviders(adminProviders);
        renderAdminApplications(adminApplications);
        const readOnlyNote = canLoadApplications
            ? ''
            : adminPublicConfig?.admin_token_configured === false
                ? ' Configure QMA_ADMIN_TOKEN on the backend to load applications and write actions.'
                : ' Enter admin token to load applications and write actions.';
        setAdminStatus(`Loaded ${adminProviders.length} providers and ${adminApplications.length} applications.${readOnlyNote}`, canLoadApplications ? 'success' : '');
    } catch (err) {
        setAdminStatus(`Admin load failed: ${err.message || err}`, 'error');
    }
}

async function toggleProviderPlugin(button) {
    const providerId = button.dataset.toggleProvider;
    const enabled = button.dataset.nextEnabled === 'true';
    const card = button.closest('.admin-card');
    const admin_note = card?.querySelector('[data-provider-note]')?.value || null;
    try {
        button.disabled = true;
        const resp = await fetch(apiUrl(`/api/v1/providers/${encodeURIComponent(providerId)}/toggle`), {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-QMA-Admin-Token': adminToken(),
            },
            body: JSON.stringify({ enabled, admin_note }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(apiErrorMessage(data, `API returned ${resp.status}`));
        setAdminStatus(`${providerId} is now ${enabled ? 'enabled' : 'disabled'}.`, 'success');
        await loadProviders();
        await loadAdminData();
    } catch (err) {
        setAdminStatus(`Provider toggle failed: ${err.message || err}`, 'error');
    } finally {
        button.disabled = false;
    }
}

async function reviewCreatorApplication(button) {
    const card = button.closest('.admin-card');
    const applicationId = card?.dataset.applicationId;
    const status = button.dataset.reviewStatus;
    const admin_note = card?.querySelector('[data-application-note]')?.value || null;
    try {
        button.disabled = true;
        const resp = await fetch(apiUrl(`/api/v1/creators/applications/${encodeURIComponent(applicationId)}/review`), {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-QMA-Admin-Token': adminToken(),
            },
            body: JSON.stringify({ status, admin_note }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(apiErrorMessage(data, `API returned ${resp.status}`));
        setAdminStatus(`${data.application.provider_id} marked ${status}.`, 'success');
        await loadAdminData();
    } catch (err) {
        setAdminStatus(`Review failed: ${err.message || err}`, 'error');
    } finally {
        button.disabled = false;
    }
}

document.getElementById('market-connect-btn')?.addEventListener('click', connectCreatorWallet);
document.getElementById('admin-gate-connect-btn')?.addEventListener('click', connectCreatorWallet);
document.getElementById('creator-application-form')?.addEventListener('submit', submitCreatorApplication);
document.getElementById('open-creator-application-btn')?.addEventListener('click', openCreatorApplicationModal);
document.getElementById('open-creator-applications-btn')?.addEventListener('click', openCreatorApplicationsModal);
document.getElementById('creator-application-close')?.addEventListener('click', closeCreatorApplicationModal);
document.getElementById('creator-applications-close')?.addEventListener('click', closeCreatorApplicationsModal);
document.getElementById('creator-applications-refresh-btn')?.addEventListener('click', loadCreatorApplications);
document.getElementById('admin-load-btn')?.addEventListener('click', loadAdminData);
document.getElementById('admin-refresh-btn')?.addEventListener('click', loadAdminData);
document.getElementById('admin-token-input')?.addEventListener('input', () => {
    renderAdminProviders(adminProviders);
    renderAdminApplications(adminApplications);
});
document.getElementById('creator-application-modal')?.addEventListener('click', (event) => {
    if (event.target?.id === 'creator-application-modal') {
        closeCreatorApplicationModal();
    }
});
document.getElementById('creator-applications-modal')?.addEventListener('click', (event) => {
    if (event.target?.id === 'creator-applications-modal') {
        closeCreatorApplicationsModal();
    }
});
document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
        closeCreatorApplicationModal();
        closeCreatorApplicationsModal();
    }
});
window.ethereum?.on?.('accountsChanged', (accounts) => {
    setConnectedMarketWallet(accounts && accounts[0] ? accounts[0] : '');
});
const savedAdminToken = sessionStorage.getItem('qma_admin_token');
if (savedAdminToken && document.getElementById('admin-token-input')) {
    document.getElementById('admin-token-input').value = savedAdminToken;
}
loadAdminPublicConfig();
initConnectedMarketWallet();
loadProviders();
loadCreatorApplications();
