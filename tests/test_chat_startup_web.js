'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const appSource = fs.readFileSync(
    path.resolve(__dirname, '../web/static/js/app.js'),
    'utf8',
);
const styleSource = fs.readFileSync(
    path.resolve(__dirname, '../web/static/css/style.css'),
    'utf8',
);

function extractFunctionDeclaration(name) {
    const asyncMarker = `async function ${name}(`;
    const syncMarker = `function ${name}(`;
    const asyncStart = appSource.indexOf(asyncMarker);
    const start = asyncStart >= 0 ? asyncStart : appSource.indexOf(syncMarker);
    assert.notEqual(start, -1, `missing ${name} in app.js`);
    const parametersEnd = appSource.indexOf(')', start);
    const bodyStart = appSource.indexOf('{', parametersEnd);
    let depth = 0;
    let quote = '';
    let escaped = false;
    for (let index = bodyStart; index < appSource.length; index += 1) {
        const char = appSource[index];
        if (escaped) {
            escaped = false;
            continue;
        }
        if (quote) {
            if (char === '\\') escaped = true;
            else if (char === quote) quote = '';
            continue;
        }
        if (['"', "'", '`'].includes(char)) {
            quote = char;
            continue;
        }
        if (char === '{') depth += 1;
        if (char === '}' && --depth === 0) return appSource.slice(start, index + 1);
    }
    assert.fail(`unterminated ${name}`);
}

test('chat model selector loads public safe model settings', () => {
    const loadStart = appSource.indexOf('async function loadSettings()');
    const loadEnd = appSource.indexOf('\nasync function loadHealth()', loadStart);
    const loadSource = appSource.slice(loadStart, loadEnd);
    const configuredStart = appSource.indexOf('function isProviderConfigured(provider)');
    const configuredEnd = appSource.indexOf('\nfunction readModels(', configuredStart);
    const configuredSource = appSource.slice(configuredStart, configuredEnd);

    assert.match(loadSource, /apiCall\('GET', '\/api\/model-settings'\)/);
    assert.doesNotMatch(loadSource, /\/api\/admin\/settings/);
    assert.match(configuredSource, /llm\.\$\{provider\.key\}\.configured/);
});

test('Super Chat renders its welcome text before asynchronous startup', () => {
    const startup = appSource.slice(appSource.lastIndexOf('applyI18n();'));

    assert.match(
        startup,
        /updateSendState\(\);\s*showWelcome\(\);\s*appBootPromise = bootApp\(\)/,
    );
    assert.ok(
        startup.indexOf('showWelcome();') < startup.indexOf('bootApp()'),
        'the welcome text must render before startup begins waiting on API calls',
    );
});

test('programmatic mobile chat focus preserves native keyboard avoidance', () => {
    const focusMessageInput = Function(
        'messageInput',
        'isMobileLayout',
        `${extractFunctionDeclaration('focusMessageInput')}; return focusMessageInput;`,
    );
    const mobileCalls = [];
    const focusOnMobile = focusMessageInput(
        { focus: (...args) => mobileCalls.push(args) },
        () => true,
    );

    focusOnMobile();

    assert.deepEqual(mobileCalls, [[]]);

    const desktopCalls = [];
    const focusOnDesktop = focusMessageInput(
        { focus: (...args) => desktopCalls.push(args) },
        () => false,
    );

    focusOnDesktop();

    assert.deepEqual(desktopCalls, [[{ preventScroll: true }]]);
});

test('startup welcome is a real draft and never falls back to historical context', () => {
    const bootStart = appSource.indexOf('async function bootApp()');
    const bootEnd = appSource.indexOf('\nfunction setView(', bootStart);
    const bootSource = appSource.slice(bootStart, bootEnd);
    const restoreStart = appSource.indexOf('async function restoreInitialConversation()');
    const restoreEnd = appSource.indexOf('\nasync function startAgentTask(', restoreStart);
    const restoreSource = appSource.slice(restoreStart, restoreEnd);

    assert.match(
        bootSource,
        /currentConversationId = null;\s*saveCurrentConversationId\(null\);/,
    );
    assert.match(bootSource, /void refreshAll\(\);/);
    assert.doesNotMatch(bootSource, /await refreshAll\(\);/);
    assert.doesNotMatch(restoreSource, /conversations\[0\]/);
});

test('startup only blocks sending through the short authentication phase', () => {
    const sendStart = appSource.indexOf('async function handleSend(');
    const sendEnd = appSource.indexOf('\nasync function sendFollowUpQuestion(', sendStart);
    const sendSource = appSource.slice(sendStart, sendEnd);

    assert.match(appSource, /let appBootstrapping = true;/);
    assert.match(appSource, /if \(appBootstrapping \|\| startupSendPending\) return t\('chat\.preparingToSend'\);/);
    assert.ok(
        sendSource.indexOf('await appBootPromise;')
            < sendSource.indexOf('if (!currentConversationId)'),
        'startup must finish before the first conversation is selected or created',
    );
    const bootStart = appSource.indexOf('async function bootApp()');
    const bootEnd = appSource.indexOf('\nfunction setView(', bootStart);
    const bootSource = appSource.slice(bootStart, bootEnd);
    assert.match(bootSource, /loadAccounts\(\{ timeoutMs: STARTUP_ACCOUNT_TIMEOUT_MS \}\)/);
    assert.match(bootSource, /void refreshAll\(\);/);
    assert.doesNotMatch(bootSource, /await loadConversations|await loadPulse|await loadProjects/);
    assert.match(
        appSource,
        /appBootPromise = bootApp\(\)\.finally\(\(\) => \{\s*appBootstrapping = false;\s*updateSendState\(\);\s*\}\);/,
    );
});

test('busy send states expose a visible progress indicator and reason', () => {
    const reasonSource = extractFunctionDeclaration('sendBusyReason');
    const stateSource = extractFunctionDeclaration('updateSendState');

    assert.match(reasonSource, /chat\.preparingToSend/);
    assert.match(reasonSource, /chat\.creatingConversation/);
    assert.match(reasonSource, /chat\.conversationRunning/);
    assert.match(reasonSource, /chat\.readingAttachment/);
    assert.match(stateSource, /setAttribute\('aria-busy', busyReason \? 'true' : 'false'\)/);
    assert.match(stateSource, /btnSend\.title = busyReason \|\| t\('actions\.send'\)/);
    assert.match(styleSource, /\.btn-send\[aria-busy="true"\]::after/);
});

test('sending from the welcome page always detaches from historical context', () => {
    const guardStart = appSource.indexOf('function ensureWelcomeStartsNewTopic()');
    const guardEnd = appSource.indexOf('\nfunction ensureCurrentConversationVisible(', guardStart);
    const guardSource = appSource.slice(guardStart, guardEnd);
    const sendStart = appSource.indexOf('async function handleSend(');
    const sendEnd = appSource.indexOf('\nasync function sendFollowUpQuestion(', sendStart);
    const sendSource = appSource.slice(sendStart, sendEnd);

    assert.match(guardSource, /querySelector\('\.welcome-screen'\)/);
    assert.match(guardSource, /currentConversationId = null;\s*saveCurrentConversationId\(null\);/);
    assert.ok(
        sendSource.indexOf('ensureWelcomeStartsNewTopic();')
            < sendSource.indexOf('if (!currentConversationId)'),
        'welcome state must be detached before deciding whether to create a conversation',
    );
});

test('welcome recommendations auto-send into a lazy new topic without filling the composer', () => {
    const quickActionStart = appSource.indexOf("const quickAction = event.target.closest('[data-query]');");
    const quickActionEnd = appSource.indexOf("const startAgentButton = event.target.closest('[data-start-agent-id]');", quickActionStart);
    const quickActionSource = appSource.slice(quickActionStart, quickActionEnd);
    const newTopicStart = appSource.indexOf('async function startNewTopic()');
    const newTopicEnd = appSource.indexOf('\nfunction createChatRunId(', newTopicStart);
    const newTopicSource = appSource.slice(newTopicStart, newTopicEnd);

    assert.match(quickActionSource, /ensureWelcomeStartsNewTopic\(\);/);
    assert.match(quickActionSource, /if \(shouldQuickSend\) \{\s*messageInput\.value = '';[\s\S]*?await handleSend\(query\);/);
    assert.ok(
        quickActionSource.indexOf('await handleSend(query);')
            < quickActionSource.indexOf('messageInput.value = query;'),
        'auto-send must return before the fallback path can copy text into the composer',
    );
    assert.match(newTopicSource, /currentConversationId = null;\s*saveCurrentConversationId\(null\);/);
    assert.doesNotMatch(newTopicSource, /createConversation\(/);
});

test('concurrent first sends share one idempotent conversation creation', async () => {
    const source = [
        extractFunctionDeclaration('createConversation'),
        extractFunctionDeclaration('createClientRequestId'),
    ].join('\n');
    const result = await vm.runInNewContext(`
        (async () => {
            let conversationCreatePromise = null;
            let conversationCreateRequestId = '';
            let currentConversationId = null;
            let currentUserId = 'mobile-user';
            let currentAgentId = 'super_chat';
            let conversations = [];
            let calls = 0;
            const requestIds = [];
            const timeouts = [];
            const SUPER_CHAT_AGENT_ID = 'super_chat';
            const CONVERSATION_CREATE_TIMEOUT_MS = 8000;
            const apiCall = async (_method, _path, body, options) => {
                calls += 1;
                requestIds.push(body.request_id);
                timeouts.push(options.timeoutMs);
                await new Promise((resolve) => setTimeout(resolve, 5));
                return { id: 'conv-single-flight' };
            };
            const updateSendState = () => {};
            const saveCurrentConversationId = () => {};
            const saveSelectedModes = () => {};
            const saveThinkingEnabled = () => {};
            const renderConversationList = () => {};
            const updateTopbar = () => {};
            ${source}
            const [first, second] = await Promise.all([
                createConversation(),
                createConversation(),
            ]);
            return JSON.stringify({ calls, requestIds, timeouts, first, second, conversationCount: conversations.length });
        })();
    `, { setTimeout, Math, Date });
    const state = JSON.parse(result);

    assert.equal(state.calls, 1);
    assert.equal(state.first.id, 'conv-single-flight');
    assert.equal(state.second.id, 'conv-single-flight');
    assert.equal(state.conversationCount, 1);
    assert.match(state.requestIds[0], /^conversation_/);
    assert.deepEqual(state.timeouts, [8000]);
});

test('a timed-out first conversation attempt releases the button and safely reuses its idempotency key', async () => {
    const source = [
        extractFunctionDeclaration('createConversation'),
        extractFunctionDeclaration('createClientRequestId'),
    ].join('\n');
    const state = JSON.parse(await vm.runInNewContext(`
        (async () => {
            let conversationCreatePromise = null;
            let conversationCreateRequestId = '';
            let currentConversationId = null;
            let currentUserId = 'mobile-user';
            let currentAgentId = 'super_chat';
            let conversations = [];
            let calls = 0;
            let sendStateUpdates = 0;
            const requestIds = [];
            const SUPER_CHAT_AGENT_ID = 'super_chat';
            const CONVERSATION_CREATE_TIMEOUT_MS = 8000;
            const apiCall = async (_method, _path, body) => {
                calls += 1;
                requestIds.push(body.request_id);
                if (calls === 1) {
                    const error = new Error('timeout');
                    error.code = 'request_timeout';
                    throw error;
                }
                return { id: 'conv-after-retry' };
            };
            const updateSendState = () => { sendStateUpdates += 1; };
            const saveCurrentConversationId = () => {};
            const saveSelectedModes = () => {};
            const saveThinkingEnabled = () => {};
            const renderConversationList = () => {};
            const updateTopbar = () => {};
            ${source}
            let firstFailed = false;
            try {
                await createConversation();
            } catch (error) {
                firstFailed = error.code === 'request_timeout';
            }
            const released = conversationCreatePromise === null;
            const second = await createConversation();
            return JSON.stringify({ firstFailed, released, second, requestIds, sendStateUpdates });
        })();
    `, { Math, Date }));

    assert.equal(state.firstFailed, true);
    assert.equal(state.released, true);
    assert.equal(state.second.id, 'conv-after-retry');
    assert.equal(state.requestIds.length, 2);
    assert.equal(state.requestIds[0], state.requestIds[1]);
    assert.ok(state.sendStateUpdates >= 4);
});

test('timed API requests abort and return a typed timeout error', async () => {
    const source = [
        extractFunctionDeclaration('requestTimeoutError'),
        extractFunctionDeclaration('fetchWithTimeout'),
    ].join('\n');
    const result = await vm.runInNewContext(`
        (async () => {
            const t = (_key, values) => 'timeout-' + values.seconds;
            const fetch = (_url, options) => new Promise((_resolve, reject) => {
                options.signal.addEventListener('abort', () => reject(new Error('aborted')));
            });
            ${source}
            try {
                await fetchWithTimeout('/slow', {}, 5);
                return { timedOut: false };
            } catch (error) {
                return { timedOut: true, code: error.code, message: error.message };
            }
        })();
    `, { AbortController, setTimeout, clearTimeout });

    assert.deepEqual({ ...result }, {
        timedOut: true,
        code: 'request_timeout',
        message: 'timeout-1',
    });
});

test('background conversation refresh preserves a conversation created while it was loading', async () => {
    const source = extractFunctionDeclaration('loadConversations');
    const state = JSON.parse(await vm.runInNewContext(`
        (async () => {
            let currentConversationId = null;
            let conversations = [];
            let resolveLoad;
            const apiCall = () => new Promise((resolve) => { resolveLoad = resolve; });
            const currentConversationRecord = () => conversations.find((item) => item.id === currentConversationId) || null;
            const applyConversationAgent = () => {};
            const renderConversationList = () => {};
            const updateTopbar = () => {};
            const refreshWelcomeIfEmpty = () => {};
            ${source}
            const pending = loadConversations();
            currentConversationId = 'new-local';
            conversations.unshift({ id: 'new-local', title: 'New local conversation' });
            resolveLoad({ conversations: [{ id: 'older-server' }] });
            await pending;
            return JSON.stringify(conversations);
        })();
    `));

    assert.deepEqual(state.map((item) => item.id), ['new-local', 'older-server']);
});
