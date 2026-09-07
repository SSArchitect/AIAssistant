'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const appSource = fs.readFileSync(path.join(root, 'web/static/js/app.js'), 'utf8');
const htmlSource = fs.readFileSync(path.join(root, 'web/index.html'), 'utf8');
const cssSource = fs.readFileSync(path.join(root, 'web/static/css/style.css'), 'utf8');

test('chat entrypoint invalidates scripts cached before MiniMax thinking support', () => {
    const script = htmlSource.match(/<script src="(\/static\/js\/app\.js\?v=[^"]+)"/);
    assert.ok(script, 'app.js must have a versioned URL');
    assert.notEqual(script[1], '/static/js/app.js?v=158-task-drag');
    assert.ok(fs.existsSync(path.join(root, 'web', script[1].split('?')[0])));
});

test('DGX model exposes a persisted thinking parameter switch', () => {
    assert.match(htmlSource, /id="btn-thinking-toggle"/);
    assert.match(appSource, /thinking_enabled:\s*Boolean\(thinkingEnabled\)/);
    assert.match(appSource, /\.\.\.thinkingRequestPayload\(\)/);
    assert.match(appSource, /saveThinkingEnabled\(\)/);
    assert.match(cssSource, /\.thinking-toggle\[hidden\]\s*\{\s*display:\s*none;/);
    assert.match(cssSource, /\.thinking-toggle\s*\{\s*width:\s*auto;\s*min-width:\s*68px;\s*flex:\s*0 0 auto;/);
    assert.match(cssSource, /\.thinking-toggle\s*\{[^}]*white-space:\s*nowrap;/);
    assert.doesNotMatch(cssSource, /\.thinking-toggle span\s*\{\s*display:\s*none;/);
});

function thinkingContext(value, settings = {}) {
    const storage = new Map();
    const attributes = {};
    const context = vm.createContext({
        modelSelect: { value }, settings, thinkingEnabled: false,
        currentConversationId: 'conversation-a', THINKING_STORAGE_KEY: 'thinking',
        accountStorageKey: key => `account:${key}`,
        localStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value) },
        t: key => key,
        btnThinkingToggle: {
            hidden: true, classList: { toggle() {} },
            setAttribute: (key, value) => { attributes[key] = value; },
        },
    });
    vm.runInContext(appSource.slice(appSource.indexOf('function thinkingStorageKey('),
        appSource.indexOf('function setSelectedModesForConversation(')), context);
    const start = appSource.indexOf('if (btnThinkingToggle) {');
    context.btnThinkingToggle.addEventListener = (event, handler) => { context.click = handler; };
    vm.runInContext(appSource.slice(start, appSource.indexOf('\nif (agentSelect)', start)), context);
    return { context, attributes };
}

test('thinking button supports DGX and MiniMax M3 including the configured default', () => {
    for (const [value, settings, supported] of [
        ['dgx:spark', {}, true],
        ['minimax:MiniMax-M3', {}, true],
        ['minimax:MiniMax-M2.7-highspeed', {}, false],
        ['minimax:MiniMax-M2.5-highspeed', {}, false],
        ['openai:MiniMax-M3', {}, false],
        ['', { 'llm.default_provider': 'minimax', 'llm.minimax.model': 'MiniMax-M3' }, true],
        ['', { 'llm.default_provider': 'minimax', 'llm.minimax.model': 'MiniMax-M2.7-highspeed' }, false],
        ['', { 'llm.default_provider': 'dgx' }, true],
        ['', {}, false],
    ]) {
        const { context } = thinkingContext(value, settings);
        context.renderThinkingToggle();
        assert.equal(context.btnThinkingToggle.hidden, !supported, value);
        assert.equal(JSON.stringify(context.thinkingRequestPayload()), supported ? '{"thinking_enabled":false}' : '{}');
    }
});

test('MiniMax M3 thinking clicks toggle the request and persist per conversation', () => {
    const { context, attributes } = thinkingContext('minimax:MiniMax-M3');
    context.click();
    assert.equal(attributes['aria-pressed'], 'true');
    assert.equal(JSON.stringify(context.thinkingRequestPayload()), '{"thinking_enabled":true}');
    context.setThinkingForConversation('conversation-b');
    assert.equal(context.thinkingEnabled, false);
    context.setThinkingForConversation('conversation-a');
    assert.equal(context.thinkingEnabled, true);
    context.modelSelect.value = 'minimax:MiniMax-M2.7-highspeed';
    assert.equal(JSON.stringify(context.thinkingRequestPayload()), '{}');
    context.click();
    assert.equal(context.thinkingEnabled, true);
    context.modelSelect.value = 'minimax:MiniMax-M3';
    context.click();
    assert.equal(attributes['aria-pressed'], 'false');
    context.setThinkingForConversation('conversation-a');
    assert.equal(context.thinkingEnabled, false);
});

test('reasoning SSE is merged into the execution process and restored from saved messages', () => {
    assert.match(appSource, /event === 'reasoning'/);
    assert.match(appSource, /streamView\.enqueueReasoning\(chunk, data\)/);
    assert.match(appSource, /streamView\.finishReasoning/);
    assert.match(appSource, /renderProcessPanel\(traceEvents, \{ expanded: false, reasoning \}\)/);
    assert.match(appSource, /type === 'model\.reasoning'\) return 'reasoning'/);
    assert.match(appSource, /msg\.reasoning \|\| ''/);
    assert.match(cssSource, /\.process-item\.reasoning/);
    assert.doesNotMatch(appSource, /renderReasoningPanel/);
});

test('intermediate model output is moved from answer text into the execution process', () => {
    assert.match(appSource, /event === 'provisional_token'/);
    assert.match(appSource, /streamView\.noteProvisional\(data\.text \|\| ''\)/);
    assert.match(appSource, /event === 'intermediate'/);
    assert.match(appSource, /streamView\.moveContentToProcess\(data\)/);
    assert.match(appSource, /type === 'model\.intermediate'/);
    const provisionalBranch = appSource.slice(
        appSource.indexOf("event === 'provisional_token'"),
        appSource.indexOf("event === 'intermediate'"),
    );
    assert.doesNotMatch(provisionalBranch, /enqueueContent/);
});
