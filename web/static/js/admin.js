const API_BASE = '';
const LANGUAGE_KEY = 'agent_assistant_language';

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
            { key: 'llm.minimax.thinking', id: 'minimax-thinking', type: 'text', labelKey: 'fields.thinkingMode', placeholder: 'disabled' },
            { key: 'aigc.minimax.image_model', id: 'minimax-image-model', type: 'text', labelKey: 'fields.imageModel', placeholder: 'image-01' },
            { key: 'aigc.minimax.speech_model', id: 'minimax-speech-model', type: 'text', labelKey: 'fields.speechModel', placeholder: 'speech-2.8-turbo' },
            { key: 'aigc.minimax.voice_id', id: 'minimax-voice-id', type: 'text', labelKey: 'fields.voiceId', placeholder: 'male-qn-qingse' },
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
        admin: { title: '配置', back: '返回聊天' },
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
                ollama: '本地 Ollama 服务配置',
            },
        },
        fields: {
            apiKey: 'API Key',
            baseUrl: 'Base URL',
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
            fetchModels: '拉取模型',
            addModel: '添加模型',
            save: '保存',
        },
        messages: {
            noModels: '还没有添加模型',
            fetchingModels: '正在拉取模型...',
            modelsAvailable: '已找到 {count} 个模型，可输入搜索后添加',
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
        roles: {
            title: '角色人设',
            desc: '配置角色提示词和长期记忆范围。',
            new: '新建角色',
            id: '角色 ID',
            name: '名称',
            namePlaceholder: '角色名称',
            description: '描述',
            descPlaceholder: '一句话描述',
            basePersona: '基础 Persona',
            instructions: '指令',
            instructionsPlaceholder: '每行一条指令',
            enabled: '启用',
            memory: '记忆',
            save: '保存角色',
            delete: '删除',
            count: '{count} 个角色',
            empty: '暂无角色',
            builtIn: '内置',
            custom: '自定义',
            nameRequired: '名称不能为空',
            saved: '角色已保存',
            deleted: '角色已删除',
            loadFailed: '加载角色失败：{message}',
            saveFailed: '保存失败：{message}',
            deleteFailed: '删除失败：{message}',
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
        },
        common: { optional: '可选', showHide: '显示/隐藏' },
    },
    en: {
        admin: { title: 'Settings', back: 'Back to Chat' },
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
                ollama: 'Local Ollama service configuration',
            },
        },
        fields: {
            apiKey: 'API Key',
            baseUrl: 'Base URL',
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
            fetchModels: 'Fetch Models',
            addModel: 'Add model',
            save: 'Save',
        },
        messages: {
            noModels: 'No models added',
            fetchingModels: 'Fetching models...',
            modelsAvailable: '{count} models available. Type to search and add one.',
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
        roles: {
            title: 'Personas',
            desc: 'Configure role prompts and long-term memory scope.',
            new: 'New Persona',
            id: 'Role ID',
            name: 'Name',
            namePlaceholder: 'Persona name',
            description: 'Description',
            descPlaceholder: 'Short description',
            basePersona: 'Base Persona',
            instructions: 'Instructions',
            instructionsPlaceholder: 'One instruction per line',
            enabled: 'Enabled',
            memory: 'Memory',
            save: 'Save Persona',
            delete: 'Delete',
            count: '{count} roles',
            empty: 'No personas',
            builtIn: 'built-in',
            custom: 'custom',
            nameRequired: 'Name is required',
            saved: 'Persona saved',
            deleted: 'Persona deleted',
            loadFailed: 'Failed to load personas: {message}',
            saveFailed: 'Failed to save: {message}',
            deleteFailed: 'Failed to delete: {message}',
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
        },
        common: { optional: 'optional', showHide: 'Show/Hide' },
    },
};

let currentLanguage = localStorage.getItem(LANGUAGE_KEY) || 'zh';
let roles = [];
let selectedRoleId = 'default';
let activeProvider = localStorage.getItem('admin_active_provider') || 'claude';
let settingsCache = {};
const providerModels = {};

async function apiCall(method, path, body = null) {
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json' },
    };
    if (body) opts.body = JSON.stringify(body);

    const resp = await fetch(API_BASE + path, opts);
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({ error: resp.statusText }));
        throw new Error(err.error || err.detail || 'Request failed');
    }
    return resp.json();
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
    renderRoles();
    renderRoleEditor();
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
        showSaveResult(t('messages.loadSettingsFailed', { message: e.message }), false);
    }
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

async function loadRoles() {
    try {
        const data = await apiCall('GET', '/api/roles');
        roles = data.roles || [];
        if (!roles.some((role) => role.id === selectedRoleId)) {
            selectedRoleId = roles.find((role) => role.id === 'default')?.id || roles[0]?.id || '';
        }
        renderRoles();
        renderRoleEditor();
    } catch (e) {
        showRoleResult(t('roles.loadFailed', { message: e.message }), false);
    }
}

function renderRoles() {
    const list = document.getElementById('role-list');
    const badge = document.getElementById('role-count-badge');
    if (badge) badge.textContent = t('roles.count', { count: roles.length });
    if (!list) return;

    if (!roles.length) {
        list.innerHTML = `<div class="role-empty">${escapeHtml(t('roles.empty'))}</div>`;
        return;
    }

    list.innerHTML = roles.map((role) => {
        const builtIn = role.metadata && role.metadata.built_in;
        return `
            <button class="role-list-item ${role.id === selectedRoleId ? 'active' : ''}"
                    type="button"
                    data-role-id="${escapeAttr(role.id)}">
                <span>${escapeHtml(role.name || role.id)}</span>
                <small>${builtIn ? t('roles.builtIn') : t('roles.custom')}</small>
            </button>
        `;
    }).join('');
}

function renderRoleEditor() {
    const role = roles.find((item) => item.id === selectedRoleId);
    const isNew = !role;
    setValue('role-id', role?.id || '');
    setValue('role-name', role?.name || '');
    setValue('role-description', role?.description || '');
    setValue('role-base-persona', role?.base_persona || '');
    setValue('role-instructions', (role?.instructions || []).join('\n'));
    setChecked('role-enabled', role ? !!role.enabled : true);
    setChecked('role-memory-enabled', role ? !!role.memory_enabled : true);

    const idInput = document.getElementById('role-id');
    if (idInput) idInput.disabled = !isNew;
    const deleteButton = document.getElementById('btn-delete-role');
    if (deleteButton) {
        const builtIn = role?.metadata && role.metadata.built_in;
        deleteButton.disabled = isNew || builtIn;
    }
}

function newRoleDraft() {
    selectedRoleId = '';
    renderRoles();
    renderRoleEditor();
    const nameInput = document.getElementById('role-name');
    if (nameInput) nameInput.focus();
}

function collectRolePayload() {
    return {
        id: readValue('role-id'),
        name: readValue('role-name'),
        description: readValue('role-description'),
        base_persona: readValue('role-base-persona'),
        instructions: readValue('role-instructions')
            .split('\n')
            .map((line) => line.trim())
            .filter(Boolean),
        enabled: readChecked('role-enabled'),
        memory_enabled: readChecked('role-memory-enabled'),
    };
}

async function saveRole() {
    const payload = collectRolePayload();
    if (!payload.name) {
        showRoleResult(t('roles.nameRequired'), false);
        return;
    }

    try {
        let role;
        if (selectedRoleId) {
            role = await apiCall('PUT', `/api/roles/${encodeURIComponent(selectedRoleId)}`, payload);
        } else {
            role = await apiCall('POST', '/api/roles', payload);
        }
        selectedRoleId = role.id;
        showRoleResult(t('roles.saved'), true);
        await loadRoles();
    } catch (e) {
        showRoleResult(t('roles.saveFailed', { message: e.message }), false);
    }
}

async function deleteSelectedRole() {
    if (!selectedRoleId) return;
    try {
        await apiCall('DELETE', `/api/roles/${encodeURIComponent(selectedRoleId)}`);
        selectedRoleId = 'default';
        showRoleResult(t('roles.deleted'), true);
        await loadRoles();
    } catch (e) {
        showRoleResult(t('roles.deleteFailed', { message: e.message }), false);
    }
}

function showRoleResult(message, ok) {
    const el = document.getElementById('role-save-result');
    if (!el) return;
    el.textContent = message;
    el.className = ok ? 'test-result success' : 'test-result error';
    el.style.display = 'block';
}

function setValue(id, value) {
    const el = document.getElementById(id);
    if (el) el.value = value || '';
}

function readValue(id) {
    const el = document.getElementById(id);
    return el ? el.value.trim() : '';
}

function setChecked(id, value) {
    const el = document.getElementById(id);
    if (el) el.checked = !!value;
}

function readChecked(id) {
    const el = document.getElementById(id);
    return el ? !!el.checked : false;
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

        const models = result.models || [];
        if (!models.length) {
            statusEl.textContent = t('messages.noModelsFound');
            statusEl.className = 'fetch-status visible error';
            return;
        }

        const datalist = document.getElementById(`model-datalist-${provider}`);
        if (datalist) {
            datalist.innerHTML = models.map((model) => `<option value="${escapeAttr(model.id)}">`).join('');
        }

        statusEl.textContent = t('messages.modelsAvailable', { count: models.length });
        statusEl.className = 'fetch-status visible';

        const input = document.getElementById(`model-input-${provider}`);
        if (input) input.focus();

        setTimeout(() => {
            statusEl.className = 'fetch-status';
        }, 5000);
    } catch (e) {
        statusEl.textContent = t('messages.fetchFailed', { message: e.message });
        statusEl.className = 'fetch-status visible error';
    } finally {
        button.disabled = false;
        button.classList.remove('loading');
    }
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

document.addEventListener('click', async (event) => {
    const languageButton = event.target.closest('#language-toggle');
    if (languageButton) {
        setLanguage(currentLanguage === 'zh' ? 'en' : 'zh');
        return;
    }

    const providerTab = event.target.closest('[data-select-provider]');
    if (providerTab) {
        setActiveProvider(providerTab.dataset.selectProvider);
        return;
    }

    const roleButton = event.target.closest('[data-role-id]');
    if (roleButton) {
        selectedRoleId = roleButton.dataset.roleId;
        renderRoles();
        renderRoleEditor();
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

document.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter') return;
    const target = event.target;
    if (target.id && target.id.startsWith('model-input-')) {
        event.preventDefault();
        addModelFromInput(target.id.replace('model-input-', ''));
    }
});

applyI18n();
renderProviderConfigurator();
loadSettings();
loadRoles();
