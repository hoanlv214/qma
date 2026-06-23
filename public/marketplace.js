const API_BASE_URL = String(window.QMA_API_BASE_URL || '').replace(/\/$/, '');

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

function renderProviders(providers) {
    const container = document.getElementById('marketplace-provider-list');
    if (!container) return;
    if (!providers.length) {
        container.innerHTML = '<div class="agent-empty">No providers registered yet.</div>';
        return;
    }
    container.innerHTML = providers.map((provider) => {
        const stats = provider.stats || {};
        const preview = provider.pricing?.preview?.amount_usdc;
        const full = provider.pricing?.full?.amount_usdc;
        const creatorShare = Number(provider.revenue_share_bps || stats.creator_share_bps || 8000) / 100;
        const status = provider.status || 'approved';
        return `
            <article class="marketplace-provider-card">
                <div class="marketplace-provider-top">
                    <div>
                        <span class="provider-status ${escapeHtml(status)}">${escapeHtml(status)}</span>
                        <h2>${escapeHtml(provider.provider_name || provider.provider_id)}</h2>
                        <p class="provider-id-line">${escapeHtml(provider.provider_id)}</p>
                    </div>
                    <a class="landing-secondary" href="/app?provider=${encodeURIComponent(provider.provider_id)}">Select</a>
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
        if (!resp.ok) throw new Error(data.detail || `API returned ${resp.status}`);
        renderProviders(data.providers || []);
    } catch (err) {
        if (container) {
            container.innerHTML = `<div class="agent-empty">Provider marketplace unavailable: ${escapeHtml(err.message || err)}</div>`;
        }
    }
}

async function connectCreatorWallet() {
    if (!window.ethereum?.request) {
        alert('MetaMask is required to connect a creator wallet.');
        return null;
    }
    const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' });
    const wallet = accounts && accounts[0] ? accounts[0] : null;
    if (wallet) {
        document.getElementById('market-connect-btn').textContent = shortAddress(wallet);
        document.getElementById('creator-wallet').value = wallet;
    }
    return wallet;
}

function formValue(form, name) {
    return String(new FormData(form).get(name) || '').trim();
}

async function submitCreatorApplication(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const statusEl = document.getElementById('creator-form-status');
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
    try {
        const resp = await fetch(apiUrl('/api/v1/creators/apply'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || `API returned ${resp.status}`);
        statusEl.classList.add('success');
        statusEl.innerHTML = `Submitted. Application <strong>${escapeHtml(data.application.application_id)}</strong> is pending admin review.`;
        form.reset();
        if (payload.creator_wallet) document.getElementById('creator-wallet').value = payload.creator_wallet;
    } catch (err) {
        statusEl.classList.add('error');
        statusEl.textContent = `Submission failed: ${err.message || err}`;
    }
}

document.getElementById('market-connect-btn')?.addEventListener('click', connectCreatorWallet);
document.getElementById('creator-application-form')?.addEventListener('submit', submitCreatorApplication);
loadProviders();
