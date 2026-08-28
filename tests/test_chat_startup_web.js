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

test('startup welcome is a real draft and never falls back to historical context', () => {
    const bootStart = appSource.indexOf('async function bootApp()');
    const bootEnd = appSource.indexOf('\nfunction setView(', bootStart);
    const bootSource = appSource.slice(bootStart, bootEnd);
    const restoreStart = appSource.indexOf('async function restoreInitialConversation()');
    const restoreEnd = appSource.indexOf('\nasync function startAgentTask(', restoreStart);
    const restoreSource = appSource.slice(restoreStart, restoreEnd);

    assert.match(
        bootSource,
        /currentConversationId = null;\s*saveCurrentConversationId\(null\);[\s\S]*?await refreshAll\(\);/,
    );
    assert.doesNotMatch(restoreSource, /conversations\[0\]/);
});

test('an immediate startup send waits for boot before creating its conversation', () => {
    const sendStart = appSource.indexOf('async function handleSend(');
    const sendEnd = appSource.indexOf('\nasync function sendFollowUpQuestion(', sendStart);
    const sendSource = appSource.slice(sendStart, sendEnd);

    assert.match(appSource, /let appBootstrapping = true;/);
    assert.match(appSource, /btnSend\.disabled = appBootstrapping/);
    assert.ok(
        sendSource.indexOf('await appBootPromise;')
            < sendSource.indexOf('if (!currentConversationId)'),
        'startup must finish before the first conversation is selected or created',
    );
    assert.match(
        appSource,
        /appBootPromise = bootApp\(\)\.finally\(\(\) => \{\s*appBootstrapping = false;\s*updateSendState\(\);\s*\}\);/,
    );
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

test('welcome recommendations and New Topic both use the lazy new-topic draft', () => {
    const quickActionStart = appSource.indexOf("const quickAction = event.target.closest('[data-query]');");
    const quickActionEnd = appSource.indexOf("const startAgentButton = event.target.closest('[data-start-agent-id]');", quickActionStart);
    const quickActionSource = appSource.slice(quickActionStart, quickActionEnd);
    const newTopicStart = appSource.indexOf('async function startNewTopic()');
    const newTopicEnd = appSource.indexOf('\nfunction createChatRunId(', newTopicStart);
    const newTopicSource = appSource.slice(newTopicStart, newTopicEnd);

    assert.match(quickActionSource, /ensureWelcomeStartsNewTopic\(\);/);
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
            const SUPER_CHAT_AGENT_ID = 'super_chat';
            const apiCall = async (_method, _path, body) => {
                calls += 1;
                requestIds.push(body.request_id);
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
            return JSON.stringify({ calls, requestIds, first, second, conversationCount: conversations.length });
        })();
    `, { setTimeout, Math, Date });
    const state = JSON.parse(result);

    assert.equal(state.calls, 1);
    assert.equal(state.first.id, 'conv-single-flight');
    assert.equal(state.second.id, 'conv-single-flight');
    assert.equal(state.conversationCount, 1);
    assert.match(state.requestIds[0], /^conversation_/);
});
