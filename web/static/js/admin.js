const API_BASE = String(globalThis.AGENT_ASSISTANT_CONFIG?.apiBase || '').replace(/\/+$/, '');
const LANGUAGE_KEY = 'agent_assistant_language';
const CURRENT_USER_ID_STORAGE_KEY = 'agent_assistant_current_user_id';
const ACCOUNT_SESSION_STORAGE_KEY = 'agent_assistant_account_session';
const ADMIN_SESSION_STORAGE_KEY = 'agent_assistant_admin_session';

const PROVIDER_CONFIG = [
    {
        key: 'claude',
        label: 'Claude',
        apiKeyPlaceholder: 'sk-ant-...',
        fields: [
            { key: 'llm.claude.api_key', id: 'claude-api-key', type: 'password', labelKey: 'fields.apiKey', placeholder: 'sk-ant-...' },
        ],
    },
    {
        key: 'openai',
        label: 'OpenAI',
        apiKeyPlaceholder: 'sk-...',
        fields: [
            { key: 'llm.openai.api_key', id: 'openai-api-key', type: 'password', labelKey: 'fields.apiKey', placeholder: 'sk-...' },
            { key: 'llm.openai.base_url', id: 'openai-base-url', type: 'text', labelKey: 'fields.baseUrl', placeholder: 'https://api.openai.com/v1' },
        ],
    },
    {
        key: 'gemini',
        label: 'Gemini',
        apiKeyPlaceholder: 'AIza...',
        fields: [
            { key: 'llm.gemini.api_key', id: 'gemini-api-key', type: 'password', labelKey: 'fields.apiKey', placeholder: 'AIza...' },
        ],
    },
    {
        key: 'deepseek',
        label: 'DeepSeek',
        apiKeyPlaceholder: 'sk-...',
        fields: [
            { key: 'llm.deepseek.api_key', id: 'deepseek-api-key', type: 'password', labelKey: 'fields.apiKey', placeholder: 'sk-...' },
        ],
    },
    {
        key: 'doubao',
        label: 'Doubao',
        apiKeyPlaceholder: 'ark-...',
        fields: [
            { key: 'llm.doubao.api_key', id: 'doubao-api-key', type: 'password', labelKey: 'fields.apiKey', placeholder: 'ark-...' },
        ],
    },
    {
        key: 'minimax',
        label: 'MiniMax',
        apiKeyPlaceholder: 'sk-cp-...',
        fields: [
            { key: 'llm.minimax.api_key', id: 'minimax-api-key', type: 'password', labelKey: 'fields.apiKey', placeholder: 'sk-cp-...' },
            { key: 'llm.minimax.base_url', id: 'minimax-base-url', type: 'text', labelKey: 'fields.baseUrl', placeholder: 'https://api.minimaxi.com/v1' },
            { key: 'llm.minimax.timeout', id: 'minimax-timeout', type: 'text', labelKey: 'fields.timeoutSeconds', placeholder: '60' },
            { key: 'llm.minimax.thinking', id: 'minimax-thinking', type: 'text', labelKey: 'fields.thinkingMode', placeholder: 'disabled' },
            { key: 'aigc.minimax.image_model', id: 'minimax-image-model', type: 'text', labelKey: 'fields.imageModel', placeholder: 'image-01' },
            { key: 'aigc.minimax.speech_model', id: 'minimax-speech-model', type: 'text', labelKey: 'fields.speechModel', placeholder: 'speech-2.8-turbo' },
            { key: 'aigc.minimax.voice_id', id: 'minimax-voice-id', type: 'text', labelKey: 'fields.voiceId', placeholder: 'male-qn-qingse' },
        ],
    },
    {
        key: 'dgx',
        label: 'DGX Spark',
        apiKeyPlaceholder: 'sk-dgx-...',
        fields: [
            { key: 'llm.dgx.api_key', id: 'dgx-api-key', type: 'password', labelKey: 'fields.apiKey', placeholder: 'sk-dgx-...' },
            { key: 'llm.dgx.base_url', id: 'dgx-base-url', type: 'text', labelKey: 'fields.baseUrl', placeholder: 'https://example.com/v1' },
            { key: 'llm.dgx.max_tokens', id: 'dgx-max-tokens', type: 'number', labelKey: 'fields.maxTokens', placeholder: '10000' },
            { key: 'llm.dgx.streaming', id: 'dgx-streaming', type: 'text', labelKey: 'fields.streaming', placeholder: 'true' },
            { key: 'llm.dgx.timeout', id: 'dgx-timeout', type: 'number', labelKey: 'fields.timeoutSeconds', placeholder: '1800' },
        ],
    },
    {
        key: 'ollama',
        label: 'Ollama',
        fields: [
            { key: 'llm.ollama.base_url', id: 'ollama-base-url', type: 'text', labelKey: 'fields.baseUrl', placeholder: 'http://localhost:11434' },
        ],
    },
];

const PROVIDERS = PROVIDER_CONFIG.map((provider) => provider.key);
const PROVIDER_BY_KEY = Object.fromEntries(PROVIDER_CONFIG.map((provider) => [provider.key, provider]));

const FIELD_MAP = {
    'admin.password': 'admin-password',
    'llm.default_provider': 'default-provider',
    'search.http.base_url': 'search-http-base-url',
    'search.http.api_key': 'search-http-api-key',
    'search.http.query_param': 'search-http-query-param',
    'search.minimax.enabled': 'search-minimax-enabled',
    'search.minimax.command': 'search-minimax-command',
    'search.minimax.args': 'search-minimax-args',
    'search.minimax.api_host': 'search-minimax-api-host',
    'search.minimax.timeout': 'search-minimax-timeout',
    'search.local.documents': 'search-local-documents',
    'mcp.servers': 'mcp-servers',
};

for (const provider of PROVIDER_CONFIG) {
    for (const field of provider.fields) {
        FIELD_MAP[field.key] = field.id;
    }
}

const I18N = {
    zh: {
        admin: { title: '管理员配置', back: '返回聊天' },
        auth: {
            title: '管理员验证',
            desc: '输入管理员密码后继续。',
            password: '管理员密码',
            login: '进入后台',
            loggingIn: '验证中...',
            failed: '验证失败：{message}',
            logout: '退出',
            logoutTitle: '退出管理员',
        },
        basic: {
            title: '基础配置',
            desc: '选择默认模型服务，并在下方完成密钥和模型配置。',
            defaultProvider: '默认模型服务',
            hintTitle: '配置逻辑已简化',
            hintBody: '保存后会自动检测已配置的 API key 是否生效；也可以在当前模型服务面板单独验证。',
        },
        provider: {
            title: '模型服务',
            desc: '选择一个模型服务，填写密钥、模型和兼容 API 地址。',
            descriptions: {
                claude: 'Anthropic Claude API 配置',
                openai: 'OpenAI API 配置，也支持兼容接口',
                gemini: 'Google Gemini API 配置',
                deepseek: 'DeepSeek API 配置',
                doubao: '火山方舟豆包 API 配置',
                minimax: 'MiniMax Token Plan 配置，包含文本、生图和语音默认模型',
                dgx: '通过公网 OpenAI 兼容接口访问本地 DGX Spark 模型',
                ollama: '本地 Ollama 服务配置',
            },
        },
        fields: {
            apiKey: 'API Key',
            baseUrl: 'Base URL',
            timeoutSeconds: 'LLM 超时秒数',
            maxTokens: '最大输出 Token',
            streaming: '流式输出',
            thinkingMode: 'Thinking 模式',
            imageModel: '图片模型',
            speechModel: '语音模型',
            voiceId: '默认音色',
            models: '模型',
            modelPlaceholder: '输入模型名称...',
        },
        status: {
            configured: '已配置',
            missing: '未配置',
            pending: '待检测',
            verified: '已验证',
            error: '检测失败',
        },
        actions: {
            saveAndValidate: '保存并检测',
            validate: '检测 Key',
            validating: '检测中...',
            fetchModels: '刷新模型',
            addModel: '添加模型',
            save: '保存',
        },
        messages: {
            noModels: '还没有添加模型',
            fetchingModels: '正在拉取模型...',
            modelsAvailable: '已同步并保存 {count} 个模型',
            noModelsFound: '没有找到模型',
            fetchFailed: '拉取失败：{message}',
            saving: '保存中...',
            saved: '保存成功，检测完成。',
            saveFailed: '保存失败：{message}',
            validating: '正在检测 {provider}...',
            validated: '{provider} 可用。',
            validationFailed: '{provider} 检测失败：{message}',
            validationMissing: '{provider} 尚未配置。',
            loadSettingsFailed: '加载配置失败：{message}',
        },
        members: {
            title: '用户管理',
            desc: '查看成员账号和可恢复密码，或永久删除账号及其数据。',
            created: '创建时间',
            updated: '更新时间',
            actions: '操作',
            count: '{count} 个成员',
            noAccounts: '暂无成员',
            delete: '删除',
            deleting: '删除中...',
            deleteConfirm: '确定删除账号「{name}」吗？该账号的会话、记忆、网盘、待办和其他数据将被永久删除，且无法恢复。',
            deleted: '已删除账号「{name}」。',
            deleteFailed: '删除失败：{message}',
            defaultProtected: '默认账号不可删除',
            unavailable: '账号记录不存在',
        },
        cost: {
            title: '成本管理',
            desc: '日均用户、历史用户和模块 token 开销。',
            refresh: '刷新',
            updated: '已更新',
            loadFailed: '加载失败',
            historicalTotal: '历史总 Token',
            dailyUserAverage: '用户日均 Token',
            dailyTotalAverage: '全站日均 Token',
            activeUsers: '活跃用户',
            activeDays: '活跃天',
            accountActiveDays: '用户活跃天',
            dailyAverage: '日均 Token',
            fromDate: '开始日期',
            toDate: '结束日期',
            last7Days: '近 7 天',
            last30Days: '近 30 天',
            allTime: '全部',
            trend: 'Token 趋势',
            noTrend: '暂无趋势数据',
            totalTokens: '总 Token',
            inputTokens: '输入',
            outputTokens: '输出',
            cacheRead: '缓存命中',
            cacheWrite: '缓存写入',
            requests: '请求',
            images: '图片',
            accounts: '账号',
            account: '账号',
            password: '密码',
            dailyUsers: '日均用户开销',
            historicalUsers: '历史用户开销',
            modules: '模块',
            moduleCosts: '模块级别开销',
            module: '模块',
            runtime: '运行时',
            accountCount: '账号数',
            passwordCount: '可查看密码',
            lastUsed: '最近使用',
            encrypted: '已加密',
            notSet: '未设置',
            viewPassword: '查看',
            hidePassword: '隐藏',
            unavailable: '不可查看',
            noUsage: '暂无 token 用量',
            never: '-',
        },
        advanced: {
            title: '高级工具源',
            desc: '检索服务、本地文档和 MCP 预留配置',
            searchUrl: 'Search HTTP Base URL',
            searchKey: 'Search API Key',
            queryParam: 'Search Query Param',
            minimaxSearchEnabled: 'MiniMax MCP 搜索启用',
            minimaxSearchCommand: 'MiniMax MCP 命令',
            minimaxSearchArgs: 'MiniMax MCP 参数 JSON',
            minimaxSearchHost: 'MiniMax API Host',
            minimaxSearchTimeout: 'MiniMax MCP 超时秒数',
            localDocs: 'Local Search Documents JSON',
            mcp: 'MCP Servers JSON',
            adminPassword: '管理员密码',
        },
        common: { optional: '可选', showHide: '显示/隐藏' },
    },
    en: {
        admin: { title: 'Admin Settings', back: 'Back to Chat' },
        auth: {
            title: 'Admin Check',
            desc: 'Enter the admin password to continue.',
            password: 'Admin password',
            login: 'Enter Admin',
            loggingIn: 'Checking...',
            failed: 'Login failed: {message}',
            logout: 'Log out',
            logoutTitle: 'Log out admin',
        },
        basic: {
            title: 'Basic Settings',
            desc: 'Choose the default model provider, then configure credentials and models below.',
            defaultProvider: 'Default Provider',
            hintTitle: 'Configuration is simpler now',
            hintBody: 'Saving automatically validates configured API keys. You can also validate the current provider only.',
        },
        provider: {
            title: 'Model Providers',
            desc: 'Pick a provider, then fill in credentials, models, and compatible API URLs.',
            descriptions: {
                claude: 'Anthropic Claude API configuration',
                openai: 'OpenAI API configuration, including compatible APIs',
                gemini: 'Google Gemini API configuration',
                deepseek: 'DeepSeek API configuration',
                doubao: 'Volcengine ARK Doubao API configuration',
                minimax: 'MiniMax Token Plan configuration for text, image, and speech defaults',
                dgx: 'Local DGX Spark models exposed through a public OpenAI-compatible endpoint',
                ollama: 'Local Ollama service configuration',
            },
        },
        fields: {
            apiKey: 'API Key',
            baseUrl: 'Base URL',
            timeoutSeconds: 'LLM timeout seconds',
            maxTokens: 'Max output tokens',
            streaming: 'Streaming',
            thinkingMode: 'Thinking mode',
            imageModel: 'Image model',
            speechModel: 'Speech model',
            voiceId: 'Default voice',
            models: 'Models',
            modelPlaceholder: 'Enter model name...',
        },
        status: {
            configured: 'Configured',
            missing: 'Missing',
            pending: 'Needs Check',
            verified: 'Verified',
            error: 'Failed',
        },
        actions: {
            saveAndValidate: 'Save & Validate',
            validate: 'Validate Key',
            validating: 'Validating...',
            fetchModels: 'Refresh Models',
            addModel: 'Add model',
            save: 'Save',
        },
        messages: {
            noModels: 'No models added',
            fetchingModels: 'Fetching models...',
            modelsAvailable: '{count} models synced and saved.',
            noModelsFound: 'No models found',
            fetchFailed: 'Fetch failed: {message}',
            saving: 'Saving...',
            saved: 'Saved and validation completed.',
            saveFailed: 'Save failed: {message}',
            validating: 'Validating {provider}...',
            validated: '{provider} is available.',
            validationFailed: '{provider} validation failed: {message}',
            validationMissing: '{provider} is not configured.',
            loadSettingsFailed: 'Failed to load settings: {message}',
        },
        members: {
            title: 'User Management',
            desc: 'View member accounts and recoverable passwords, or permanently delete an account and its data.',
            created: 'Created',
            updated: 'Updated',
            actions: 'Actions',
            count: '{count} members',
            noAccounts: 'No members',
            delete: 'Delete',
            deleting: 'Deleting...',
            deleteConfirm: 'Delete account “{name}”? Its conversations, memories, drive files, todos, and other data will be permanently deleted and cannot be recovered.',
            deleted: 'Deleted account “{name}”.',
            deleteFailed: 'Delete failed: {message}',
            defaultProtected: 'The default account cannot be deleted',
            unavailable: 'Account record is unavailable',
        },
        cost: {
            title: 'Cost',
            desc: 'Daily user, historical user, and module token usage.',
            refresh: 'Refresh',
            updated: 'Updated',
            loadFailed: 'Load failed',
            historicalTotal: 'Historical Tokens',
            dailyUserAverage: 'User Daily Avg',
            dailyTotalAverage: 'Site Daily Avg',
            activeUsers: 'Active Users',
            activeDays: 'Active Days',
            accountActiveDays: 'User Active Days',
            dailyAverage: 'Daily Avg',
            fromDate: 'From',
            toDate: 'To',
            last7Days: 'Last 7 days',
            last30Days: 'Last 30 days',
            allTime: 'All time',
            trend: 'Token Trend',
            noTrend: 'No trend data',
            totalTokens: 'Total Tokens',
            inputTokens: 'Input',
            outputTokens: 'Output',
            cacheRead: 'Cache Read',
            cacheWrite: 'Cache Write',
            requests: 'Requests',
            images: 'Images',
            accounts: 'Accounts',
            account: 'Account',
            password: 'Password',
            dailyUsers: 'Daily User Cost',
            historicalUsers: 'Historical User Cost',
            modules: 'Modules',
            moduleCosts: 'Module Cost',
            module: 'Module',
            runtime: 'Runtime',
            accountCount: 'Accounts',
            passwordCount: 'Visible Passwords',
            lastUsed: 'Last Used',
            encrypted: 'Encrypted',
            notSet: 'Not Set',
            viewPassword: 'View',
            hidePassword: 'Hide',
            unavailable: 'Unavailable',
            noUsage: 'No token usage',
            never: '-',
        },
        advanced: {
            title: 'Advanced Tool Sources',
            desc: 'Search service, local documents, and reserved MCP configuration',
            searchUrl: 'Search HTTP Base URL',
            searchKey: 'Search API Key',
            queryParam: 'Search Query Param',
            minimaxSearchEnabled: 'MiniMax MCP Search Enabled',
            minimaxSearchCommand: 'MiniMax MCP Command',
            minimaxSearchArgs: 'MiniMax MCP Args JSON',
            minimaxSearchHost: 'MiniMax API Host',
            minimaxSearchTimeout: 'MiniMax MCP Timeout Seconds',
            localDocs: 'Local Search Documents JSON',
            mcp: 'MCP Servers JSON',
            adminPassword: 'Admin Password',
        },
        common: { optional: 'optional', showHide: 'Show/Hide' },
    },
};

let currentLanguage = localStorage.getItem(LANGUAGE_KEY) || 'zh';
let activeProvider = localStorage.getItem('admin_active_provider') || 'claude';
let settingsCache = {};
let costReport = null;
let costFilter = { from: '', to: '' };
let adminToken = localStorage.getItem(ADMIN_SESSION_STORAGE_KEY) || '';
let adminAuthenticated = false;
const visibleAccountPasswords = {};
const providerModels = {};

async function apiCall(method, path, body = null) {
    const currentUserId = loadCurrentUserId();
    const accountToken = loadAccountSessionToken(currentUserId);
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json' },
    };
    if (accountToken) opts.headers['X-Account-Session'] = accountToken;
    if (currentUserId) opts.headers['X-User-ID'] = currentUserId;
    if (adminToken && path.startsWith('/api/admin') && path !== '/api/admin/login') {
        opts.headers['X-Admin-Session'] = adminToken;
    }
    if (body) opts.body = JSON.stringify(body);

    const resp = await fetch(API_BASE + path, opts);
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({ error: resp.statusText }));
        const error = new Error(err.error || err.detail || 'Request failed');
        error.status = resp.status;
        throw error;
    }
    return resp.json();
}

function loadCurrentUserId() {
    const value = localStorage.getItem(CURRENT_USER_ID_STORAGE_KEY);
    if (value && String(value).trim()) return String(value).trim();
    return '';
}

function loadAccountSessionToken(userId = loadCurrentUserId()) {
    const id = String(userId || '').trim();
    if (!id) return '';
    return localStorage.getItem(`${ACCOUNT_SESSION_STORAGE_KEY}:${id}`) || '';
}

function t(key, vars = {}) {
    const parts = key.split('.');
    let value = I18N[currentLanguage];
    for (const part of parts) value = value?.[part];
    if (typeof value !== 'string') return key;
    return value.replace(/\{(\w+)\}/g, (_, name) => vars[name] ?? '');
}

function applyI18n() {
    document.documentElement.lang = currentLanguage === 'zh' ? 'zh-CN' : 'en';
    document.querySelectorAll('[data-i18n]').forEach((el) => {
        el.textContent = t(el.dataset.i18n);
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach((el) => {
        el.placeholder = t(el.dataset.i18nPlaceholder);
    });
    document.querySelectorAll('[data-i18n-title]').forEach((el) => {
        el.title = t(el.dataset.i18nTitle);
    });
    const langButton = document.getElementById('language-toggle');
    if (langButton) langButton.textContent = currentLanguage === 'zh' ? 'EN' : '中';
}

function setLanguage(language) {
    settingsCache = { ...settingsCache, ...collectSettings() };
    currentLanguage = language;
    localStorage.setItem(LANGUAGE_KEY, currentLanguage);
    applyI18n();
    renderProviderConfigurator();
    applySettingsToForm(settingsCache);
    updateProviderStatuses(settingsCache);
    renderCostReport();
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
}

function escapeAttr(text) {
    return escapeHtml(text).replace(/"/g, '&quot;');
}

function toggleVisibility(inputId) {
    const input = document.getElementById(inputId);
    if (!input) return;
    input.type = input.type === 'password' ? 'text' : 'password';
}

function renderProviderConfigurator() {
    renderDefaultProviderOptions();
    renderProviderTabs();
    renderProviderPanels();
    for (const provider of PROVIDERS) renderModelList(provider);
    setActiveProvider(activeProvider, false);
}

function renderDefaultProviderOptions() {
    const select = document.getElementById('default-provider');
    if (!select) return;
    const currentValue = select.value || settingsCache['llm.default_provider'] || activeProvider || 'claude';
    select.innerHTML = PROVIDER_CONFIG.map((provider) => (
        `<option value="${escapeAttr(provider.key)}">${escapeHtml(provider.label)}</option>`
    )).join('');
    select.value = PROVIDER_BY_KEY[currentValue] ? currentValue : 'claude';
}

function renderProviderTabs() {
    const tabs = document.getElementById('provider-tabs');
    if (!tabs) return;
    tabs.innerHTML = PROVIDER_CONFIG.map((provider) => {
        const status = providerStatus(provider.key, settingsCache);
        return `
            <button class="provider-tab ${provider.key === activeProvider ? 'active' : ''}" type="button" data-select-provider="${escapeAttr(provider.key)}">
                <span>${escapeHtml(provider.label)}</span>
                <small class="provider-tab-status ${status.className}" id="tab-status-${escapeAttr(provider.key)}">${escapeHtml(status.text)}</small>
            </button>
        `;
    }).join('');
}

function renderProviderPanels() {
    const panels = document.getElementById('provider-panels');
    if (!panels) return;
    panels.innerHTML = PROVIDER_CONFIG.map((provider) => `
        <section class="provider-panel ${provider.key === activeProvider ? 'active' : ''}" id="provider-panel-${escapeAttr(provider.key)}">
            <div class="provider-panel-head">
                <div>
                    <h3>${escapeHtml(provider.label)}</h3>
                    <p>${escapeHtml(t(`provider.descriptions.${provider.key}`))}</p>
                </div>
                <span class="provider-badge ${providerStatus(provider.key, settingsCache).className}" id="badge-${escapeAttr(provider.key)}">
                    ${escapeHtml(providerStatus(provider.key, settingsCache).text)}
                </span>
            </div>
            <div class="provider-field-grid">
                ${provider.fields.map(renderProviderField).join('')}
            </div>
            <div class="form-group">
                <label>${escapeHtml(t('fields.models'))}</label>
                <div class="model-list" id="model-list-${escapeAttr(provider.key)}"></div>
                <div class="model-add-row">
                    <input type="text" id="model-input-${escapeAttr(provider.key)}" class="form-input" list="model-datalist-${escapeAttr(provider.key)}" placeholder="${escapeAttr(t('fields.modelPlaceholder'))}">
                    <datalist id="model-datalist-${escapeAttr(provider.key)}"></datalist>
                    <button class="btn-add-model" type="button" data-add-model="${escapeAttr(provider.key)}" title="${escapeAttr(t('actions.addModel'))}">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                    </button>
                    <button class="btn-fetch-models" type="button" data-fetch-models="${escapeAttr(provider.key)}" title="${escapeAttr(t('actions.fetchModels'))}">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
                        <span>${escapeHtml(t('actions.fetchModels'))}</span>
                    </button>
                </div>
                <div class="fetch-status" id="fetch-status-${escapeAttr(provider.key)}"></div>
            </div>
            <div class="provider-actions">
                <button class="btn-test" type="button" data-validate-provider="${escapeAttr(provider.key)}">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
                    <span>${escapeHtml(t('actions.validate'))}</span>
                </button>
                <div class="test-result compact" id="test-result-${escapeAttr(provider.key)}"></div>
            </div>
        </section>
    `).join('');
}

function renderProviderField(field) {
    const isSecret = field.type === 'password';
    return `
        <div class="form-group">
            <label for="${escapeAttr(field.id)}">${escapeHtml(t(field.labelKey))}</label>
            <div class="${isSecret ? 'input-with-action' : ''}">
                <input type="${escapeAttr(field.type)}" id="${escapeAttr(field.id)}" class="form-input" placeholder="${escapeAttr(field.placeholder || '')}">
                ${isSecret ? `
                    <button class="btn-toggle-vis" type="button" data-toggle-secret="${escapeAttr(field.id)}" title="${escapeAttr(t('common.showHide'))}">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                    </button>
                ` : ''}
            </div>
        </div>
    `;
}

function setActiveProvider(provider, persist = true) {
    if (!PROVIDER_BY_KEY[provider]) provider = 'claude';
    activeProvider = provider;
    if (persist) localStorage.setItem('admin_active_provider', provider);

    document.querySelectorAll('.provider-tab').forEach((tab) => {
        tab.classList.toggle('active', tab.dataset.selectProvider === provider);
    });
    document.querySelectorAll('.provider-panel').forEach((panel) => {
        panel.classList.toggle('active', panel.id === `provider-panel-${provider}`);
    });

    const badge = document.getElementById('active-provider-badge');
    if (badge) {
        const status = providerStatus(provider, settingsCache);
        badge.textContent = status.text;
        badge.className = `provider-badge ${status.className}`;
    }
}

function showAdminLogin(message = '') {
    adminAuthenticated = false;
    const loginPanel = document.getElementById('admin-login-panel');
    const app = document.getElementById('admin-app');
    if (loginPanel) loginPanel.hidden = false;
    if (app) app.hidden = true;
    showAdminLoginResult(message, false, Boolean(message));
    const input = document.getElementById('admin-login-password');
    if (input) input.focus();
}

function showAdminApp() {
    adminAuthenticated = true;
    const loginPanel = document.getElementById('admin-login-panel');
    const app = document.getElementById('admin-app');
    if (loginPanel) loginPanel.hidden = true;
    if (app) app.hidden = false;
}

function showAdminLoginResult(message, ok, visible = true) {
    const resultEl = document.getElementById('admin-login-result');
    if (!resultEl) return;
    resultEl.textContent = message;
    resultEl.className = ok ? 'save-result success' : 'save-result error';
    resultEl.style.display = visible && message ? 'block' : 'none';
}

async function loginAdmin() {
    const input = document.getElementById('admin-login-password');
    const button = document.querySelector('#admin-login-form .login-submit');
    const password = input ? input.value.trim() : '';
    if (!password) {
        showAdminLoginResult(t('auth.failed', { message: t('auth.password') }), false);
        return;
    }
    if (button) {
        button.disabled = true;
        button.textContent = t('auth.loggingIn');
    }
    try {
        const data = await apiCall('POST', '/api/admin/login', { password });
        adminToken = data.token || '';
        if (!adminToken) throw new Error('missing admin token');
        localStorage.setItem(ADMIN_SESSION_STORAGE_KEY, adminToken);
        if (input) input.value = '';
        showAdminApp();
        await loadAdminData();
    } catch (e) {
        adminToken = '';
        localStorage.removeItem(ADMIN_SESSION_STORAGE_KEY);
        showAdminLoginResult(t('auth.failed', { message: e.message }), false);
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = t('auth.login');
        }
    }
}

function logoutAdmin() {
    adminToken = '';
    localStorage.removeItem(ADMIN_SESSION_STORAGE_KEY);
    showAdminLogin();
}

function handleAdminAuthError(error) {
    if (error && error.status === 401) {
        logoutAdmin();
        showAdminLoginResult(t('auth.failed', { message: error.message }), false);
        return true;
    }
    return false;
}

async function verifyAdminSession() {
    if (!adminToken) return false;
    try {
        await apiCall('GET', '/api/admin/session');
        return true;
    } catch {
        adminToken = '';
        localStorage.removeItem(ADMIN_SESSION_STORAGE_KEY);
        return false;
    }
}

async function loadAdminData() {
    renderProviderConfigurator();
    renderCostReport();
    await loadSettings();
    await loadCosts();
}

async function bootstrapAdmin() {
    applyI18n();
    if (await verifyAdminSession()) {
        showAdminApp();
        await loadAdminData();
    } else {
        showAdminLogin();
    }
}

async function loadSettings() {
    try {
        const data = await apiCall('GET', '/api/admin/settings');
        settingsCache = data.settings || {};
        activeProvider = settingsCache['llm.default_provider'] || activeProvider;
        renderProviderConfigurator();
        applySettingsToForm(settingsCache);
        loadProviderModels(settingsCache);
        updateProviderStatuses(settingsCache);
    } catch (e) {
        if (handleAdminAuthError(e)) return;
        showSaveResult(t('messages.loadSettingsFailed', { message: e.message }), false);
    }
}

async function loadCosts(button = null) {
    if (button) button.disabled = true;
    try {
        costReport = await apiCall('GET', `/api/admin/costs${costFilterQuery()}`);
        renderCostReport();
    } catch (e) {
        if (handleAdminAuthError(e)) return;
        renderCostError(e.message);
    } finally {
        if (button) button.disabled = false;
    }
}

function costFilterQuery() {
    const params = new URLSearchParams();
    if (costFilter.from) params.set('from', costFilter.from);
    if (costFilter.to) params.set('to', costFilter.to);
    const query = params.toString();
    return query ? `?${query}` : '';
}

function syncCostFilterInputs() {
    const fromInput = document.getElementById('cost-filter-from');
    const toInput = document.getElementById('cost-filter-to');
    if (fromInput) fromInput.value = costFilter.from || '';
    if (toInput) toInput.value = costFilter.to || '';
    document.querySelectorAll('[data-cost-range]').forEach((button) => {
        button.classList.toggle('active', button.dataset.costRange === activeCostRange());
    });
}

function activeCostRange() {
    if (!costFilter.from && !costFilter.to) return 'all';
    const today = formatDateInput(new Date());
    for (const days of [7, 30]) {
        const from = new Date();
        from.setDate(from.getDate() - (days - 1));
        if (costFilter.from === formatDateInput(from) && costFilter.to === today) {
            return String(days);
        }
    }
    return '';
}

function applyCostRange(range) {
    if (range === 'all') {
        costFilter = { from: '', to: '' };
    } else {
        const days = Number(range || 0);
        if (!days) return;
        const today = new Date();
        const from = new Date();
        from.setDate(today.getDate() - (days - 1));
        costFilter = {
            from: formatDateInput(from),
            to: formatDateInput(today),
        };
    }
    syncCostFilterInputs();
}

function renderCostReport() {
    syncCostFilterInputs();
    renderCostMetrics(costReport?.summary || {});
    renderCostTrend(costReport?.daily_series || [], costReport?.filter || {});
    renderCostAccuracy(costReport?.summary || {});
    renderMemberAccounts(costReport?.accounts || []);
    renderDailyUserCosts(costReport?.daily_users || costReport?.historical_users || []);
    renderHistoricalUserCosts(costReport?.historical_users || []);
    renderCostModules(costReport?.modules || []);
    updateCostBadge(costReport ? t('cost.updated') : '-');
}

function renderCostMetrics(summary) {
    const container = document.getElementById('cost-metrics');
    if (!container) return;
    const dailyUserAverage = summary.daily_average_per_active_account || {};
    const dailyAverage = summary.daily_average || {};
    const metrics = [
        { label: t('cost.historicalTotal'), value: formatNumber(summary.total_tokens) },
        { label: t('cost.dailyUserAverage'), value: formatAverage(dailyUserAverage.total_tokens) },
        { label: t('cost.dailyTotalAverage'), value: formatAverage(dailyAverage.total_tokens) },
        { label: t('cost.activeUsers'), value: formatNumber(summary.active_accounts) },
        { label: t('cost.activeDays'), value: formatNumber(summary.active_days) },
        { label: t('cost.inputTokens'), value: formatNumber(summary.input_tokens) },
        { label: t('cost.outputTokens'), value: formatNumber(summary.output_tokens) },
        { label: t('cost.cacheRead'), value: formatNumber(summary.cached_input_tokens) },
        { label: t('cost.cacheWrite'), value: formatNumber(summary.cache_creation_input_tokens) },
        { label: t('cost.requests'), value: formatNumber(summary.request_count) },
    ];
    container.innerHTML = metrics.map((metric) => `
        <div class="cost-metric">
            <strong>${escapeHtml(metric.value)}</strong>
            <span>${escapeHtml(metric.label)}</span>
        </div>
    `).join('');
}

function renderCostAccuracy(summary) {
    const note = document.getElementById('cost-accuracy-note');
    if (!note) return;
    const parts = [];
    if (summary.accuracy_note) parts.push(summary.accuracy_note);
    const tokenUsageRecords = Number(summary.token_usage_records || 0);
    const traceFallbackRecords = Number(summary.trace_fallback_records || 0);
    if (tokenUsageRecords || traceFallbackRecords) {
        parts.push(`token_usages: ${formatNumber(tokenUsageRecords)} / trace fallback: ${formatNumber(traceFallbackRecords)}`);
    }
    note.textContent = parts.join(' ');
    note.hidden = parts.length === 0;
}

function renderCostTrend(series, filter = {}) {
    const container = document.getElementById('cost-trend-chart');
    const rangeLabel = document.getElementById('cost-chart-range');
    if (!container) return;
    const rows = (series || []).filter((item) => item && item.date);
    if (rangeLabel) rangeLabel.textContent = costChartRangeLabel(rows, filter);
    if (!rows.length) {
        container.innerHTML = `<div class="cost-chart-empty">${escapeHtml(t('cost.noTrend'))}</div>`;
        return;
    }

    const width = 820;
    const height = 240;
    const pad = { top: 18, right: 18, bottom: 34, left: 58 };
    const plotWidth = width - pad.left - pad.right;
    const plotHeight = height - pad.top - pad.bottom;
    const maxValue = Math.max(1, ...rows.flatMap((item) => [
        Number(item.total_tokens || 0),
        Number(item.input_tokens || 0),
        Number(item.output_tokens || 0),
    ]));
    const xAt = (index) => {
        if (rows.length === 1) return pad.left + plotWidth / 2;
        return pad.left + (index / (rows.length - 1)) * plotWidth;
    };
    const yAt = (value) => pad.top + plotHeight - (Number(value || 0) / maxValue) * plotHeight;
    const linePoints = (key) => rows.map((item, index) => `${xAt(index).toFixed(1)},${yAt(item[key]).toFixed(1)}`).join(' ');
    const grid = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
        const y = pad.top + plotHeight - ratio * plotHeight;
        const value = maxValue * ratio;
        return `
            <line class="cost-chart-grid" x1="${pad.left}" y1="${y.toFixed(1)}" x2="${width - pad.right}" y2="${y.toFixed(1)}"></line>
            <text class="cost-chart-y" x="${pad.left - 10}" y="${(y + 4).toFixed(1)}">${escapeHtml(formatCompactNumber(value))}</text>
        `;
    }).join('');
    const totalDots = rows.length <= 45 ? rows.map((item, index) => `
        <circle class="cost-chart-dot" cx="${xAt(index).toFixed(1)}" cy="${yAt(item.total_tokens).toFixed(1)}" r="3">
            <title>${escapeHtml(item.date)}: ${escapeHtml(formatNumber(item.total_tokens))}</title>
        </circle>
    `).join('') : '';
    const firstDate = rows[0]?.date || '';
    const lastDate = rows[rows.length - 1]?.date || '';
    container.innerHTML = `
        <svg class="cost-chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeAttr(t('cost.trend'))}">
            ${grid}
            <polyline class="cost-chart-line total" points="${linePoints('total_tokens')}"></polyline>
            <polyline class="cost-chart-line input" points="${linePoints('input_tokens')}"></polyline>
            <polyline class="cost-chart-line output" points="${linePoints('output_tokens')}"></polyline>
            ${totalDots}
            <text class="cost-chart-x" x="${pad.left}" y="${height - 10}">${escapeHtml(firstDate)}</text>
            <text class="cost-chart-x end" x="${width - pad.right}" y="${height - 10}">${escapeHtml(lastDate)}</text>
        </svg>
        <div class="cost-chart-legend">
            <span><i class="total"></i>${escapeHtml(t('cost.totalTokens'))}</span>
            <span><i class="input"></i>${escapeHtml(t('cost.inputTokens'))}</span>
            <span><i class="output"></i>${escapeHtml(t('cost.outputTokens'))}</span>
        </div>
    `;
}

function costChartRangeLabel(rows, filter = {}) {
    if (filter.from || filter.to) {
        return `${filter.from || '-'} - ${filter.to || '-'}`;
    }
    if (rows.length) {
        return `${rows[0].date} - ${rows[rows.length - 1].date}`;
    }
    return '-';
}

function renderMemberAccounts(accounts) {
    const badge = document.getElementById('member-count-badge');
    if (badge) badge.textContent = t('members.count', { count: accounts.length });
    const tbody = document.getElementById('member-account-rows');
    if (!tbody) return;
    if (!accounts.length) {
        tbody.innerHTML = emptyCostRow(5, t('members.noAccounts'));
        return;
    }
    tbody.innerHTML = accounts.map((account) => `
        <tr>
            <td>${renderAccountCell(account.name, account.id)}</td>
            <td>${renderPasswordCell(account)}</td>
            <td>${escapeHtml(formatDateTime(account.created_at))}</td>
            <td>${escapeHtml(formatDateTime(account.updated_at))}</td>
            <td>${renderAccountDeleteAction(account)}</td>
        </tr>
    `).join('');
}

function renderAccountDeleteAction(account) {
    if (account.id === '0') {
        return `<span class="cost-muted">${escapeHtml(t('members.defaultProtected'))}</span>`;
    }
    if (account.exists === false) {
        return `<span class="cost-muted">${escapeHtml(t('members.unavailable'))}</span>`;
    }
    return `<button class="member-delete-action" type="button" data-delete-account="${escapeAttr(account.id)}">${escapeHtml(t('members.delete'))}</button>`;
}

function renderDailyUserCosts(accounts) {
    const tbody = document.getElementById('cost-daily-user-rows');
    if (!tbody) return;
    if (!accounts.length) {
        tbody.innerHTML = emptyCostRow(8);
        return;
    }
    tbody.innerHTML = accounts.map((account) => {
        const average = account.daily_average || {};
        return `
        <tr>
            <td>${renderAccountCell(account.name, account.id)}</td>
            <td>${formatNumber(account.active_days)}</td>
            <td>${formatAverage(average.total_tokens)}</td>
            <td>${formatAverage(average.input_tokens)}</td>
            <td>${formatAverage(average.output_tokens)}</td>
            <td>${formatAverage(average.cached_input_tokens)}</td>
            <td>${formatAverage(average.cache_creation_input_tokens)}</td>
            <td>${formatAverage(average.request_count)}</td>
        </tr>
        `;
    }).join('');
}

function renderHistoricalUserCosts(accounts) {
    const tbody = document.getElementById('cost-historical-user-rows');
    if (!tbody) return;
    if (!accounts.length) {
        tbody.innerHTML = emptyCostRow(10);
        return;
    }
    tbody.innerHTML = accounts.map((account) => `
        <tr>
            <td>${renderAccountCell(account.name, account.id)}</td>
            <td>${formatNumber(account.request_count)}</td>
            <td>${formatNumber(account.total_tokens)}</td>
            <td>${formatNumber(account.input_tokens)}</td>
            <td>${formatNumber(account.output_tokens)}</td>
            <td>${formatNumber(account.cached_input_tokens)}</td>
            <td>${formatNumber(account.cache_creation_input_tokens)}</td>
            <td>${formatNumber(account.image_count)}</td>
            <td>${formatNumber(account.active_days)}</td>
            <td>${escapeHtml(formatDateTime(account.last_used_at))}</td>
        </tr>
    `).join('');
}

function renderCostModules(modules) {
    const tbody = document.getElementById('cost-module-rows');
    if (!tbody) return;
    if (!modules.length) {
        tbody.innerHTML = emptyCostRow(12);
        return;
    }
    tbody.innerHTML = modules.map((module) => {
        const average = module.daily_average || {};
        return `
        <tr>
            <td>
                <div class="cost-account-cell">
                    <span>${escapeHtml(module.module_name || module.agent_id || '-')}</span>
                    <small>${escapeHtml(module.agent_id || '')}</small>
                </div>
            </td>
            <td>${escapeHtml(module.runtime || '-')}</td>
            <td>${formatNumber(module.account_count)}</td>
            <td>${formatNumber(module.active_days)}</td>
            <td>${formatAverage(average.total_tokens)}</td>
            <td>${formatNumber(module.request_count)}</td>
            <td>${formatNumber(module.total_tokens)}</td>
            <td>${formatNumber(module.input_tokens)}</td>
            <td>${formatNumber(module.output_tokens)}</td>
            <td>${formatNumber(module.cached_input_tokens)}</td>
            <td>${formatNumber(module.cache_creation_input_tokens)}</td>
            <td>${formatNumber(module.image_count)}</td>
        </tr>
        `;
    }).join('');
}

function renderAccountCell(name, id) {
    return `
        <div class="cost-account-cell">
            <span>${escapeHtml(name || id || '-')}</span>
            <small>${escapeHtml(id || '')}</small>
        </div>
    `;
}

function renderPasswordCell(account) {
    if (visibleAccountPasswords[account.id]) {
        return `
            <div class="cost-password-wrap">
                <code class="cost-password">${escapeHtml(visibleAccountPasswords[account.id])}</code>
                <button class="cost-password-action" type="button" data-hide-account-password="${escapeAttr(account.id)}">${escapeHtml(t('cost.hidePassword'))}</button>
            </div>
        `;
    }
    if (account.password_available) {
        return `<button class="cost-password-action" type="button" data-view-account-password="${escapeAttr(account.id)}">${escapeHtml(t('cost.viewPassword'))}</button>`;
    }
    const label = account.password_set ? t('cost.encrypted') : t('cost.notSet');
    return `<span class="cost-muted">${escapeHtml(label)}</span>`;
}

async function viewAccountPassword(accountId, button = null) {
    if (!accountId) return;
    if (button) button.disabled = true;
    try {
        const data = await apiCall('GET', `/api/admin/accounts/${encodeURIComponent(accountId)}/password`);
        if (!data.password_available || !data.password) {
            visibleAccountPasswords[accountId] = data.password_note || t('cost.unavailable');
        } else {
            visibleAccountPasswords[accountId] = data.password;
        }
        renderMemberAccounts(costReport?.accounts || []);
    } catch (e) {
        if (handleAdminAuthError(e)) return;
        visibleAccountPasswords[accountId] = e.message || t('cost.unavailable');
        renderMemberAccounts(costReport?.accounts || []);
    } finally {
        if (button) button.disabled = false;
    }
}

function hideAccountPassword(accountId) {
    delete visibleAccountPasswords[accountId];
    renderMemberAccounts(costReport?.accounts || []);
}

function showMemberActionResult(message, ok, visible = true) {
    const resultEl = document.getElementById('member-action-result');
    if (!resultEl) return;
    resultEl.textContent = message;
    resultEl.className = ok ? 'save-result success' : 'save-result error';
    resultEl.style.display = visible && message ? 'block' : 'none';
}

async function deleteMemberAccount(accountId, button = null) {
    const account = (costReport?.accounts || []).find((item) => item.id === accountId);
    if (!account || account.id === '0' || account.exists === false) return;
    const accountName = account.name || account.id;
    if (!window.confirm(t('members.deleteConfirm', { name: accountName }))) return;

    if (button) {
        button.disabled = true;
        button.textContent = t('members.deleting');
    }
    showMemberActionResult('', true, false);
    try {
        await apiCall('DELETE', `/api/admin/accounts/${encodeURIComponent(account.id)}`);
        delete visibleAccountPasswords[account.id];
        localStorage.removeItem(`${ACCOUNT_SESSION_STORAGE_KEY}:${account.id}`);
        if (loadCurrentUserId() === account.id) {
            localStorage.removeItem(CURRENT_USER_ID_STORAGE_KEY);
        }
        await loadCosts();
        showMemberActionResult(t('members.deleted', { name: accountName }), true);
    } catch (e) {
        if (handleAdminAuthError(e)) return;
        showMemberActionResult(t('members.deleteFailed', { message: e.message }), false);
        if (button) {
            button.disabled = false;
            button.textContent = t('members.delete');
        }
    }
}

function emptyCostRow(colspan, message = t('cost.noUsage')) {
    return `<tr><td class="cost-empty" colspan="${colspan}">${escapeHtml(message)}</td></tr>`;
}

function renderCostError(message) {
    updateCostBadge(t('cost.loadFailed'), 'error');
    const accountRows = document.getElementById('member-account-rows');
    const dailyRows = document.getElementById('cost-daily-user-rows');
    const historicalRows = document.getElementById('cost-historical-user-rows');
    const moduleRows = document.getElementById('cost-module-rows');
    const chart = document.getElementById('cost-trend-chart');
    if (accountRows) accountRows.innerHTML = `<tr><td class="cost-empty error" colspan="5">${escapeHtml(message || t('cost.loadFailed'))}</td></tr>`;
    if (dailyRows) dailyRows.innerHTML = `<tr><td class="cost-empty error" colspan="8">${escapeHtml(message || t('cost.loadFailed'))}</td></tr>`;
    if (historicalRows) historicalRows.innerHTML = `<tr><td class="cost-empty error" colspan="10">${escapeHtml(message || t('cost.loadFailed'))}</td></tr>`;
    if (moduleRows) moduleRows.innerHTML = `<tr><td class="cost-empty error" colspan="12">${escapeHtml(message || t('cost.loadFailed'))}</td></tr>`;
    if (chart) chart.innerHTML = `<div class="cost-chart-empty error">${escapeHtml(message || t('cost.loadFailed'))}</div>`;
}

function updateCostBadge(text, className = 'configured') {
    const badge = document.getElementById('cost-updated-badge');
    if (!badge) return;
    badge.textContent = text;
    badge.className = `provider-badge ${className}`;
}

function formatNumber(value) {
    const number = Number(value || 0);
    return new Intl.NumberFormat(currentLanguage === 'zh' ? 'zh-CN' : 'en-US').format(number);
}

function formatCompactNumber(value) {
    const number = Number(value || 0);
    return new Intl.NumberFormat(currentLanguage === 'zh' ? 'zh-CN' : 'en-US', {
        notation: 'compact',
        maximumFractionDigits: 1,
    }).format(number);
}

function formatAverage(value) {
    const number = Number(value || 0);
    const options = Math.abs(number) >= 10
        ? { maximumFractionDigits: 1 }
        : { maximumFractionDigits: 2 };
    return new Intl.NumberFormat(currentLanguage === 'zh' ? 'zh-CN' : 'en-US', options).format(number);
}

function formatDateInput(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 10);
}

function formatDateTime(value) {
    if (!value) return t('cost.never');
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return t('cost.never');
    return new Intl.DateTimeFormat(currentLanguage === 'zh' ? 'zh-CN' : 'en-US', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    }).format(date);
}

function applySettingsToForm(settings) {
    for (const [key, elementId] of Object.entries(FIELD_MAP)) {
        const el = document.getElementById(elementId);
        if (!el) continue;
        if (settings[key] !== undefined) el.value = settings[key];
    }
    const defaultProvider = document.getElementById('default-provider');
    if (defaultProvider && !defaultProvider.value) defaultProvider.value = 'claude';
}

function loadProviderModels(settings) {
    for (const provider of PROVIDERS) {
        let models = [];
        const modelsJson = settings[`llm.${provider}.models`];
        if (modelsJson) {
            try { models = JSON.parse(modelsJson); } catch {}
        }
        if (!models.length && settings[`llm.${provider}.model`]) {
            models = [settings[`llm.${provider}.model`]];
        }
        providerModels[provider] = models;
        renderModelList(provider);
    }
}

function providerStatus(providerKey, settings) {
    const configured = isProviderConfigured(providerKey, settings);
    const status = settings[`llm.${providerKey}.validation_status`] || (configured ? 'pending' : 'missing');
    if (!configured && providerKey !== 'ollama') {
        return { status: 'missing', text: t('status.missing'), className: '' };
    }
    if (status === 'verified') return { status, text: t('status.verified'), className: 'configured' };
    if (status === 'pending') return { status, text: t('status.pending'), className: 'pending' };
    if (status === 'error') return { status, text: t('status.error'), className: 'error' };
    if (status === 'missing') return { status, text: t('status.missing'), className: '' };
    return { status: 'configured', text: t('status.configured'), className: 'configured' };
}

function isProviderConfigured(providerKey, settings = settingsCache) {
    if (providerKey === 'ollama') {
        return Boolean(settings['llm.ollama.base_url'] || settings['llm.ollama.model']);
    }
    return Boolean(settings[`llm.${providerKey}.api_key`]);
}

function updateProviderStatuses(settings) {
    for (const provider of PROVIDERS) {
        const status = providerStatus(provider, settings);
        const badge = document.getElementById(`badge-${provider}`);
        if (badge) {
            badge.textContent = status.text;
            badge.className = `provider-badge ${status.className}`;
        }
        const tabStatus = document.getElementById(`tab-status-${provider}`);
        if (tabStatus) {
            tabStatus.textContent = status.text;
            tabStatus.className = `provider-tab-status ${status.className}`;
        }
    }
    setActiveProvider(activeProvider, false);
}

function renderModelList(provider) {
    const container = document.getElementById(`model-list-${provider}`);
    if (!container) return;
    const models = providerModels[provider] || [];

    if (!models.length) {
        container.innerHTML = `<span class="no-models">${escapeHtml(t('messages.noModels'))}</span>`;
        return;
    }

    container.innerHTML = models.map((model, index) => `
        <span class="model-tag">
            <span class="model-tag-text">${escapeHtml(model)}</span>
            <button class="model-tag-remove" type="button" data-remove-model="${escapeAttr(provider)}:${index}" title="Remove">&times;</button>
        </span>
    `).join('');
}

function addModelFromInput(provider) {
    const input = document.getElementById(`model-input-${provider}`);
    if (!input) return;
    const model = input.value.trim();
    if (!model) return;

    if (!providerModels[provider]) providerModels[provider] = [];
    if (!providerModels[provider].includes(model)) {
        providerModels[provider].push(model);
        renderModelList(provider);
    }
    input.value = '';
    input.focus();
}

async function fetchModels(provider, button) {
    const statusEl = document.getElementById(`fetch-status-${provider}`);
    if (!statusEl || !button) return;

    button.disabled = true;
    button.classList.add('loading');
    statusEl.textContent = t('messages.fetchingModels');
    statusEl.className = 'fetch-status visible';

    try {
        await apiCall('PUT', '/api/admin/settings', { settings: collectSettings() });
        const result = await apiCall('POST', '/api/admin/list-models', { provider });

        if (!result.success) {
            statusEl.textContent = result.error || t('messages.noModelsFound');
            statusEl.className = 'fetch-status visible error';
            return;
        }

        const currentDefault = providerModels[provider]?.[0] || settingsCache[`llm.${provider}.model`] || '';
        const refreshedModels = normalizeFetchedModels(result.models, currentDefault);
        if (!refreshedModels.length) {
            statusEl.textContent = t('messages.noModelsFound');
            statusEl.className = 'fetch-status visible error';
            return;
        }

        const refreshedSettings = collectSettings();
        refreshedSettings[`llm.${provider}.models`] = JSON.stringify(refreshedModels);
        refreshedSettings[`llm.${provider}.model`] = refreshedModels[0];
        await apiCall('PUT', '/api/admin/settings', { settings: refreshedSettings });

        providerModels[provider] = refreshedModels;
        settingsCache = { ...settingsCache, ...refreshedSettings };
        renderModelList(provider);

        const datalist = document.getElementById(`model-datalist-${provider}`);
        if (datalist) {
            datalist.innerHTML = refreshedModels.map((model) => `<option value="${escapeAttr(model)}">`).join('');
        }

        statusEl.textContent = t('messages.modelsAvailable', { count: refreshedModels.length });
        statusEl.className = 'fetch-status visible';

        const input = document.getElementById(`model-input-${provider}`);
        if (input) input.focus();

        setTimeout(() => {
            statusEl.className = 'fetch-status';
        }, 5000);
    } catch (e) {
        if (handleAdminAuthError(e)) return;
        statusEl.textContent = t('messages.fetchFailed', { message: e.message });
        statusEl.className = 'fetch-status visible error';
    } finally {
        button.disabled = false;
        button.classList.remove('loading');
    }
}

function normalizeFetchedModels(models = [], currentDefault = '') {
    const normalized = [];
    const seen = new Set();
    const items = Array.isArray(models) ? models : [];
    items.forEach((item) => {
        const id = String(typeof item === 'string' ? item : (item?.id || '')).trim();
        if (!id || seen.has(id)) return;
        seen.add(id);
        normalized.push(id);
    });

    const preferred = String(currentDefault || '').trim();
    if (!preferred || !seen.has(preferred)) return normalized;
    return [preferred, ...normalized.filter((model) => model !== preferred)];
}

function collectSettings() {
    const settings = {};
    for (const [key, elementId] of Object.entries(FIELD_MAP)) {
        const el = document.getElementById(elementId);
        if (el) settings[key] = el.value;
    }
    for (const provider of PROVIDERS) {
        const models = providerModels[provider] || [];
        settings[`llm.${provider}.models`] = JSON.stringify(models);
        settings[`llm.${provider}.model`] = models[0] || '';
    }
    return settings;
}

async function saveSettings() {
    const btn = document.getElementById('btn-save');
    const settings = collectSettings();
    settingsCache = { ...settingsCache, ...settings };
    btn.disabled = true;
    btn.textContent = t('messages.saving');
    showSaveResult('', true, false);

    try {
        const result = await apiCall('PUT', '/api/admin/settings', {
            settings,
            validate: true,
        });
        mergeValidation(result.validation || {});
        showSaveResult(t('messages.saved'), true);
        await loadSettings();
    } catch (e) {
        if (handleAdminAuthError(e)) return;
        showSaveResult(t('messages.saveFailed', { message: e.message }), false);
    } finally {
        btn.disabled = false;
        btn.textContent = t('actions.saveAndValidate');
    }
}

async function validateProvider(provider, button) {
    const resultEl = document.getElementById(`test-result-${provider}`);
    const label = PROVIDER_BY_KEY[provider]?.label || provider;
    if (!resultEl || !button) return;

    button.disabled = true;
    const original = button.innerHTML;
    button.textContent = t('actions.validating');
    resultEl.textContent = t('messages.validating', { provider: label });
    resultEl.className = 'test-result compact';
    resultEl.style.display = 'block';

    try {
        await apiCall('PUT', '/api/admin/settings', { settings: collectSettings() });
        const result = await apiCall('POST', '/api/admin/validate-provider', { provider });
        const validation = result.validation || {};
        mergeValidation(validation);
        updateProviderStatuses(settingsCache);
        const item = validation[provider];
        showValidationResult(provider, item);
    } catch (e) {
        if (handleAdminAuthError(e)) return;
        const item = {
            success: false,
            status: 'error',
            message: e.message,
            provider,
        };
        mergeValidation({ [provider]: item });
        updateProviderStatuses(settingsCache);
        showValidationResult(provider, item);
    } finally {
        button.disabled = false;
        button.innerHTML = original;
    }
}

function showValidationResult(provider, item) {
    const resultEl = document.getElementById(`test-result-${provider}`);
    if (!resultEl || !item) return;
    const label = PROVIDER_BY_KEY[provider]?.label || provider;
    if (item.success) {
        resultEl.textContent = item.message || t('messages.validated', { provider: label });
        resultEl.className = 'test-result compact success';
    } else if (item.status === 'missing') {
        resultEl.textContent = item.message || t('messages.validationMissing', { provider: label });
        resultEl.className = 'test-result compact error';
    } else {
        resultEl.textContent = t('messages.validationFailed', { provider: label, message: item.message || '' });
        resultEl.className = 'test-result compact error';
    }
    resultEl.style.display = 'block';
}

function mergeValidation(validation) {
    for (const [provider, item] of Object.entries(validation || {})) {
        if (!item) continue;
        settingsCache[`llm.${provider}.validation_status`] = item.status || (item.success ? 'verified' : 'error');
        settingsCache[`llm.${provider}.validation_message`] = item.message || '';
        settingsCache[`llm.${provider}.validation_checked_at`] = item.validated_at || '';
        settingsCache[`llm.${provider}.validation_model_count`] = String(item.model_count ?? 0);
    }
    updateProviderStatuses(settingsCache);
}

function showSaveResult(message, ok, visible = true) {
    const resultEl = document.getElementById('save-result');
    if (!resultEl) return;
    resultEl.textContent = message;
    resultEl.className = ok ? 'save-result success' : 'save-result error';
    resultEl.style.display = visible && message ? 'block' : 'none';
}

document.addEventListener('submit', async (event) => {
    if (event.target && event.target.id === 'admin-login-form') {
        event.preventDefault();
        await loginAdmin();
    }
});

document.addEventListener('click', async (event) => {
    const languageButton = event.target.closest('#language-toggle');
    if (languageButton) {
        setLanguage(currentLanguage === 'zh' ? 'en' : 'zh');
        return;
    }

    const logoutButton = event.target.closest('#admin-logout');
    if (logoutButton) {
        logoutAdmin();
        return;
    }

    const refreshCostsButton = event.target.closest('[data-refresh-costs]');
    if (refreshCostsButton) {
        await loadCosts(refreshCostsButton);
        return;
    }

    const costRangeButton = event.target.closest('[data-cost-range]');
    if (costRangeButton) {
        applyCostRange(costRangeButton.dataset.costRange);
        await loadCosts(costRangeButton);
        return;
    }

    const viewPasswordButton = event.target.closest('[data-view-account-password]');
    if (viewPasswordButton) {
        await viewAccountPassword(viewPasswordButton.dataset.viewAccountPassword, viewPasswordButton);
        return;
    }

    const hidePasswordButton = event.target.closest('[data-hide-account-password]');
    if (hidePasswordButton) {
        hideAccountPassword(hidePasswordButton.dataset.hideAccountPassword);
        return;
    }

    const deleteAccountButton = event.target.closest('[data-delete-account]');
    if (deleteAccountButton) {
        await deleteMemberAccount(deleteAccountButton.dataset.deleteAccount, deleteAccountButton);
        return;
    }

    const providerTab = event.target.closest('[data-select-provider]');
    if (providerTab) {
        setActiveProvider(providerTab.dataset.selectProvider);
        return;
    }

    const toggleSecret = event.target.closest('[data-toggle-secret]');
    if (toggleSecret) {
        toggleVisibility(toggleSecret.dataset.toggleSecret);
        return;
    }

    const addButton = event.target.closest('[data-add-model]');
    if (addButton) {
        addModelFromInput(addButton.dataset.addModel);
        return;
    }

    const removeButton = event.target.closest('[data-remove-model]');
    if (removeButton) {
        const [provider, index] = removeButton.dataset.removeModel.split(':');
        providerModels[provider].splice(Number(index), 1);
        renderModelList(provider);
        return;
    }

    const fetchButton = event.target.closest('[data-fetch-models]');
    if (fetchButton) {
        await fetchModels(fetchButton.dataset.fetchModels, fetchButton);
        return;
    }

    const validateButton = event.target.closest('[data-validate-provider]');
    if (validateButton) {
        await validateProvider(validateButton.dataset.validateProvider, validateButton);
    }
});

document.addEventListener('change', (event) => {
    if (event.target.id === 'default-provider') {
        setActiveProvider(event.target.value);
    }
});

document.addEventListener('change', async (event) => {
    if (event.target && event.target.id === 'cost-filter-from') {
        costFilter.from = event.target.value || '';
        syncCostFilterInputs();
        await loadCosts();
        return;
    }
    if (event.target && event.target.id === 'cost-filter-to') {
        costFilter.to = event.target.value || '';
        syncCostFilterInputs();
        await loadCosts();
    }
});

document.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter') return;
    const target = event.target;
    if (target.id && target.id.startsWith('model-input-')) {
        event.preventDefault();
        addModelFromInput(target.id.replace('model-input-', ''));
    }
});

bootstrapAdmin();
