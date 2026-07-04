const API_BASE = '';
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
        admin: { title: '配置', back: '返回聊天' },
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
                ollama: '本地 Ollama 服务配置',
            },
        },
        fields: {
            apiKey: 'API Key',
            baseUrl: 'Base URL',
            timeoutSeconds: 'LLM 超时秒数',
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
        cost: {
            title: '成本管理',
            desc: '账号密码和 token 开销总览。',
            refresh: '刷新',
            updated: '已更新',
            loadFailed: '加载失败',
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
            modules: '账号 x 模块',
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
        roles: {
            title: '角色人设',
            desc: '配置角色名、工作方式、习惯偏好和长期记忆范围。',
            new: '新建角色',
            id: '角色 ID',
            name: '角色名',
            namePlaceholder: '角色名称',
            description: '描述',
            descPlaceholder: '一句话描述',
            basePersona: '基础 Persona',
            instructions: '指令',
            instructionsPlaceholder: '每行一条指令',
            preferences: '习惯 / 偏好',
            preferencesPlaceholder: '每行一条，例如：回答先给结论；默认用中文；复杂任务先列计划',
            examplesTitle: '常用模板',
            applyExample: '套用',
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
            builtInHint: '内置角色不可编辑或删除，可以新建自定义角色。',
            customHint: '自定义角色可保存，也可以在左侧或下方删除。',
            deleteConfirm: '确定删除角色「{name}」吗？',
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
            adminPassword: '管理员密码',
        },
        common: { optional: '可选', showHide: '显示/隐藏' },
    },
    en: {
        admin: { title: 'Settings', back: 'Back to Chat' },
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
                ollama: 'Local Ollama service configuration',
            },
        },
        fields: {
            apiKey: 'API Key',
            baseUrl: 'Base URL',
            timeoutSeconds: 'LLM timeout seconds',
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
        cost: {
            title: 'Cost',
            desc: 'Account passwords and token usage.',
            refresh: 'Refresh',
            updated: 'Updated',
            loadFailed: 'Load failed',
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
            modules: 'Account x Module',
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
        roles: {
            title: 'Personas',
            desc: 'Configure persona names, working style, habits, preferences, and memory scope.',
            new: 'New Persona',
            id: 'Role ID',
            name: 'Persona Name',
            namePlaceholder: 'Persona name',
            description: 'Description',
            descPlaceholder: 'Short description',
            basePersona: 'Base Persona',
            instructions: 'Instructions',
            instructionsPlaceholder: 'One instruction per line',
            preferences: 'Habits / Preferences',
            preferencesPlaceholder: 'One per line, e.g. answer with conclusion first; use English by default; plan before complex tasks',
            examplesTitle: 'Templates',
            applyExample: 'Use',
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
            builtInHint: 'Built-in personas cannot be edited or deleted. Create a custom persona instead.',
            customHint: 'Custom personas can be saved here and deleted from the left list or the button below.',
            deleteConfirm: 'Delete persona "{name}"?',
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
            adminPassword: 'Admin Password',
        },
        common: { optional: 'optional', showHide: 'Show/Hide' },
    },
};

const ROLE_EXAMPLES = [
    {
        id: 'personal_operator',
        name: { zh: '私人执行助理', en: 'Personal Operator' },
        description: {
            zh: '帮我拆任务、跟进事项、整理日程和推动个人项目。',
            en: 'Helps break down tasks, track follow-ups, organize schedules, and move personal projects forward.',
        },
        basePersona: {
            zh: '你是一位靠谱、细致、有推进感的私人执行助理。你会把模糊想法整理成清晰行动，并帮用户减少拖延和遗漏。',
            en: 'You are a reliable, detail-oriented personal operator. You turn fuzzy ideas into clear actions and help the user avoid procrastination and missed details.',
        },
        instructions: {
            zh: ['先确认目标和截止时间。', '复杂事项拆成今天、这周、之后三层。', '输出尽量能直接变成待办或日程。'],
            en: ['Clarify the goal and deadline first.', 'Split complex work into today, this week, and later.', 'Make outputs easy to turn into tasks or calendar items.'],
        },
        preferences: {
            zh: ['默认用中文。', '回答先给结论，再给行动清单。', '提醒我哪些事需要主动推进。'],
            en: ['Use English by default.', 'Answer with the conclusion first, then action items.', 'Call out items that need proactive follow-up.'],
        },
    },
    {
        id: 'engineering_partner',
        name: { zh: '工程搭档', en: 'Engineering Partner' },
        description: {
            zh: '一起设计、实现、排查和复盘代码项目。',
            en: 'Collaborates on design, implementation, debugging, and review for engineering projects.',
        },
        basePersona: {
            zh: '你是一位资深工程搭档。你会先读懂现有系统，再提出保守、清晰、可验证的实现方案。',
            en: 'You are a senior engineering partner. You understand the existing system first, then suggest conservative, clear, verifiable implementation paths.',
        },
        instructions: {
            zh: ['先确认代码边界和现有约定。', '优先给可测试、可回滚的小步改动。', '发现风险时直接指出具体文件或行为。'],
            en: ['Confirm code boundaries and existing conventions first.', 'Prefer small changes that can be tested and rolled back.', 'Point to concrete files or behavior when identifying risks.'],
        },
        preferences: {
            zh: ['不要空泛重构。', '解释时带上验证方式。', '遇到不确定先查代码。'],
            en: ['Avoid vague refactors.', 'Include verification steps when explaining.', 'Inspect the code before assuming.'],
        },
    },
    {
        id: 'writing_editor_custom',
        name: { zh: '写作编辑', en: 'Writing Editor' },
        description: {
            zh: '帮我写作、润色、改标题、调整语气和结构。',
            en: 'Helps draft, polish, title, tune tone, and structure writing.',
        },
        basePersona: {
            zh: '你是一位克制但有审美的写作编辑。你会保留用户原意，让表达更准确、有节奏、有辨识度。',
            en: 'You are a restrained editor with taste. You preserve the user intent while making the writing clearer, sharper, and more distinctive.',
        },
        instructions: {
            zh: ['先判断文本目标和读者。', '给少量高质量版本，不堆砌选项。', '修改时说明关键取舍。'],
            en: ['Identify the goal and audience first.', 'Offer a few high-quality versions instead of many options.', 'Explain the key editorial tradeoffs.'],
        },
        preferences: {
            zh: ['偏好自然、克制、不过度营销。', '标题要短、有力、具体。', '保留我原来的语气底色。'],
            en: ['Prefer natural, restrained language over hype.', 'Titles should be short, strong, and specific.', 'Preserve my underlying voice.'],
        },
    },
];

let currentLanguage = localStorage.getItem(LANGUAGE_KEY) || 'zh';
let roles = [];
let selectedRoleId = 'default';
let activeProvider = localStorage.getItem('admin_active_provider') || 'claude';
let settingsCache = {};
let costReport = null;
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
    renderRoleExamples();
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

function localizedRoleText(role, field) {
    const localized = role?.metadata?.localized || {};
    const candidates = [
        localized[currentLanguage]?.[field],
        localized.zh?.[field],
        localized.en?.[field],
        role?.[field],
    ];
    const match = candidates.find((item) => typeof item === 'string' && item.trim());
    return match || '';
}

function localizedExampleText(example, field) {
    const value = example?.[field];
    if (typeof value === 'string') return value;
    return value?.[currentLanguage] || value?.zh || value?.en || '';
}

function localizedExampleList(example, field) {
    const value = example?.[field];
    const list = Array.isArray(value?.[currentLanguage])
        ? value[currentLanguage]
        : (Array.isArray(value?.zh) ? value.zh : value?.en);
    return Array.isArray(list) ? list : [];
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
    renderRoleExamples();
    renderCostReport();
    await loadSettings();
    await loadCosts();
    await loadRoles();
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
        costReport = await apiCall('GET', '/api/admin/costs');
        renderCostReport();
    } catch (e) {
        if (handleAdminAuthError(e)) return;
        renderCostError(e.message);
    } finally {
        if (button) button.disabled = false;
    }
}

function renderCostReport() {
    renderCostMetrics(costReport?.summary || {});
    renderCostAccuracy(costReport?.summary || {});
    renderCostAccounts(costReport?.accounts || []);
    renderCostModules(costReport?.modules || []);
    updateCostBadge(costReport ? t('cost.updated') : '-');
}

function renderCostMetrics(summary) {
    const container = document.getElementById('cost-metrics');
    if (!container) return;
    const metrics = [
        { label: t('cost.totalTokens'), value: formatNumber(summary.total_tokens) },
        { label: t('cost.inputTokens'), value: formatNumber(summary.input_tokens) },
        { label: t('cost.outputTokens'), value: formatNumber(summary.output_tokens) },
        { label: t('cost.cacheRead'), value: formatNumber(summary.cached_input_tokens) },
        { label: t('cost.cacheWrite'), value: formatNumber(summary.cache_creation_input_tokens) },
        { label: t('cost.requests'), value: formatNumber(summary.request_count) },
        { label: t('cost.images'), value: formatNumber(summary.image_count) },
        { label: t('cost.accountCount'), value: formatNumber(summary.total_accounts) },
        { label: t('cost.passwordCount'), value: formatNumber(summary.accounts_with_passwords) },
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

function renderCostAccounts(accounts) {
    const tbody = document.getElementById('cost-account-rows');
    if (!tbody) return;
    if (!accounts.length) {
        tbody.innerHTML = emptyCostRow(10);
        return;
    }
    tbody.innerHTML = accounts.map((account) => `
        <tr>
            <td>${renderAccountCell(account.name, account.id)}</td>
            <td>${renderPasswordCell(account)}</td>
            <td>${formatNumber(account.request_count)}</td>
            <td>${formatNumber(account.total_tokens)}</td>
            <td>${formatNumber(account.input_tokens)}</td>
            <td>${formatNumber(account.output_tokens)}</td>
            <td>${formatNumber(account.cached_input_tokens)}</td>
            <td>${formatNumber(account.cache_creation_input_tokens)}</td>
            <td>${formatNumber(account.image_count)}</td>
            <td>${escapeHtml(formatDateTime(account.last_used_at))}</td>
        </tr>
    `).join('');
}

function renderCostModules(modules) {
    const tbody = document.getElementById('cost-module-rows');
    if (!tbody) return;
    if (!modules.length) {
        tbody.innerHTML = emptyCostRow(10);
        return;
    }
    tbody.innerHTML = modules.map((module) => `
        <tr>
            <td>${renderAccountCell(module.account_name, module.account_id)}</td>
            <td>
                <div class="cost-account-cell">
                    <span>${escapeHtml(module.module_name || module.agent_id || '-')}</span>
                    <small>${escapeHtml(module.agent_id || '')}</small>
                </div>
            </td>
            <td>${escapeHtml(module.runtime || '-')}</td>
            <td>${formatNumber(module.request_count)}</td>
            <td>${formatNumber(module.total_tokens)}</td>
            <td>${formatNumber(module.input_tokens)}</td>
            <td>${formatNumber(module.output_tokens)}</td>
            <td>${formatNumber(module.cached_input_tokens)}</td>
            <td>${formatNumber(module.cache_creation_input_tokens)}</td>
            <td>${formatNumber(module.image_count)}</td>
        </tr>
    `).join('');
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
        renderCostAccounts(costReport?.accounts || []);
    } catch (e) {
        if (handleAdminAuthError(e)) return;
        visibleAccountPasswords[accountId] = e.message || t('cost.unavailable');
        renderCostAccounts(costReport?.accounts || []);
    } finally {
        if (button) button.disabled = false;
    }
}

function hideAccountPassword(accountId) {
    delete visibleAccountPasswords[accountId];
    renderCostAccounts(costReport?.accounts || []);
}

function emptyCostRow(colspan) {
    return `<tr><td class="cost-empty" colspan="${colspan}">${escapeHtml(t('cost.noUsage'))}</td></tr>`;
}

function renderCostError(message) {
    updateCostBadge(t('cost.loadFailed'), 'error');
    const rows = `<tr><td class="cost-empty error" colspan="10">${escapeHtml(message || t('cost.loadFailed'))}</td></tr>`;
    const accountRows = document.getElementById('cost-account-rows');
    const moduleRows = document.getElementById('cost-module-rows');
    if (accountRows) accountRows.innerHTML = rows;
    if (moduleRows) moduleRows.innerHTML = rows;
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

function renderRoleExamples() {
    const list = document.getElementById('role-example-list');
    if (!list) return;
    list.innerHTML = ROLE_EXAMPLES.map((example, index) => `
        <button class="role-example-button" type="button" data-role-example="${index}">
            <span>${escapeHtml(localizedExampleText(example, 'name'))}</span>
            <small>${escapeHtml(localizedExampleText(example, 'description'))}</small>
        </button>
    `).join('');
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
            <div class="role-list-item ${role.id === selectedRoleId ? 'active' : ''}">
                <button class="role-list-select" type="button" data-role-id="${escapeAttr(role.id)}">
                    <span>${escapeHtml(localizedRoleText(role, 'name') || role.id)}</span>
                    <small>${escapeHtml(localizedRoleText(role, 'description') || (builtIn ? t('roles.builtIn') : t('roles.custom')))}</small>
                </button>
                ${builtIn ? '<span class="role-list-lock"></span>' : `
                    <button class="role-list-delete" type="button"
                            data-delete-role-id="${escapeAttr(role.id)}"
                            title="${escapeAttr(t('roles.delete'))}"
                            aria-label="${escapeAttr(t('roles.delete'))}">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
                            <path d="M3 6h18M8 6V4h8v2M10 11v6M14 11v6M6 6l1 15h10l1-15"/>
                        </svg>
                    </button>
                `}
            </div>
        `;
    }).join('');
}

function renderRoleEditor() {
    const role = roles.find((item) => item.id === selectedRoleId);
    const isNew = !role;
    const builtIn = role?.metadata && role.metadata.built_in;
    setValue('role-id', role?.id || '');
    setValue('role-name', builtIn ? localizedRoleText(role, 'name') : (role?.name || ''));
    setValue('role-description', builtIn ? localizedRoleText(role, 'description') : (role?.description || ''));
    setValue('role-base-persona', role?.base_persona || '');
    setValue('role-instructions', (role?.instructions || []).join('\n'));
    setValue('role-preferences', rolePreferences(role).join('\n'));
    setChecked('role-enabled', role ? !!role.enabled : true);
    setChecked('role-memory-enabled', role ? !!role.memory_enabled : true);

    const idInput = document.getElementById('role-id');
    if (idInput) idInput.disabled = !isNew;
    setRoleEditorDisabled(Boolean(builtIn));
    const deleteButton = document.getElementById('btn-delete-role');
    if (deleteButton) {
        deleteButton.disabled = isNew || builtIn;
    }
    setRoleHint(isNew ? '' : (builtIn ? t('roles.builtInHint') : t('roles.customHint')));
}

function rolePreferences(role) {
    const value = role?.metadata?.preferences;
    if (Array.isArray(value)) {
        return value.map((item) => String(item || '').trim()).filter(Boolean);
    }
    if (typeof value === 'string') {
        return value.split('\n').map((line) => line.trim()).filter(Boolean);
    }
    return [];
}

function setRoleEditorDisabled(disabled) {
    [
        'role-name',
        'role-description',
        'role-base-persona',
        'role-instructions',
        'role-preferences',
        'role-enabled',
        'role-memory-enabled',
    ].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.disabled = disabled;
    });
    const saveButton = document.querySelector('.role-actions .btn-test');
    if (saveButton) saveButton.disabled = disabled;
}

function setRoleHint(message) {
    const hint = document.getElementById('role-editor-hint');
    if (!hint) return;
    hint.textContent = message || '';
    hint.hidden = !message;
}

function newRoleDraft() {
    selectedRoleId = '';
    renderRoles();
    renderRoleEditor();
    renderRoleExamples();
    showRoleResult('', true, false);
    const nameInput = document.getElementById('role-name');
    if (nameInput) nameInput.focus();
}

function parseRoleLines(value) {
    return String(value || '')
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean);
}

function collectRolePayload() {
    const existing = roles.find((item) => item.id === selectedRoleId);
    const metadata = { ...(existing?.metadata || {}) };
    if (!metadata.built_in) metadata.built_in = false;
    metadata.preferences = parseRoleLines(readValue('role-preferences'));
    return {
        id: readValue('role-id'),
        name: readValue('role-name'),
        description: readValue('role-description'),
        base_persona: readValue('role-base-persona'),
        instructions: parseRoleLines(readValue('role-instructions')),
        enabled: readChecked('role-enabled'),
        memory_enabled: readChecked('role-memory-enabled'),
        metadata,
    };
}

function applyRoleExample(index) {
    const example = ROLE_EXAMPLES[index];
    if (!example) return;
    selectedRoleId = '';
    renderRoles();
    renderRoleEditor();
    showRoleResult('', true, false);
    setValue('role-id', example.id);
    setValue('role-name', localizedExampleText(example, 'name'));
    setValue('role-description', localizedExampleText(example, 'description'));
    setValue('role-base-persona', localizedExampleText(example, 'basePersona'));
    setValue('role-instructions', localizedExampleList(example, 'instructions').join('\n'));
    setValue('role-preferences', localizedExampleList(example, 'preferences').join('\n'));
    setChecked('role-enabled', true);
    setChecked('role-memory-enabled', true);
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
    await deleteRoleById(selectedRoleId);
}

async function deleteRoleById(roleId) {
    if (!roleId) return;
    const role = roles.find((item) => item.id === roleId);
    if (role?.metadata?.built_in) {
        showRoleResult(t('roles.builtInHint'), false);
        return;
    }
    const name = localizedRoleText(role, 'name') || role?.name || roleId;
    if (!window.confirm(t('roles.deleteConfirm', { name }))) return;
    try {
        await apiCall('DELETE', `/api/roles/${encodeURIComponent(roleId)}`);
        selectedRoleId = 'default';
        showRoleResult(t('roles.deleted'), true);
        await loadRoles();
    } catch (e) {
        showRoleResult(t('roles.deleteFailed', { message: e.message }), false);
    }
}

function showRoleResult(message, ok, visible = true) {
    const el = document.getElementById('role-save-result');
    if (!el) return;
    el.textContent = message;
    el.className = ok ? 'test-result success' : 'test-result error';
    el.style.display = visible && message ? 'block' : 'none';
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
        if (handleAdminAuthError(e)) return;
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

    const providerTab = event.target.closest('[data-select-provider]');
    if (providerTab) {
        setActiveProvider(providerTab.dataset.selectProvider);
        return;
    }

    const roleExampleButton = event.target.closest('[data-role-example]');
    if (roleExampleButton) {
        applyRoleExample(Number(roleExampleButton.dataset.roleExample));
        return;
    }

    const roleDeleteButton = event.target.closest('[data-delete-role-id]');
    if (roleDeleteButton) {
        event.stopPropagation();
        await deleteRoleById(roleDeleteButton.dataset.deleteRoleId);
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

bootstrapAdmin();
