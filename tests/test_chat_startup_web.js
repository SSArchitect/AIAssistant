'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const appSource = fs.readFileSync(
    path.resolve(__dirname, '../web/static/js/app.js'),
    'utf8',
);

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
