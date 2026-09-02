'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const { AdaptiveStreamBuffer, splitGraphemes } = require('../web/static/js/stream-typewriter.js');

const appSource = fs.readFileSync(
    path.resolve(__dirname, '../web/static/js/app.js'),
    'utf8',
);

function extractFunctionDeclaration(name) {
    const marker = `function ${name}(`;
    const start = appSource.indexOf(marker);
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

function createConversationScrollHelpers({ currentConversationId, activeView = 'chat', messagesContainer }) {
    return Function(
        'currentConversationId',
        'activeView',
        'messagesContainer',
        'requestAnimationFrame',
        'CHAT_STREAM_AUTOSCROLL_THRESHOLD_PX',
        `${extractFunctionDeclaration('isConversationScrollTarget')}
        ${extractFunctionDeclaration('shouldFollowConversationStream')}
        ${extractFunctionDeclaration('scrollToBottom')}
        return { isConversationScrollTarget, shouldFollowConversationStream, scrollToBottom };`,
    )(
        currentConversationId,
        activeView,
        messagesContainer,
        (callback) => callback(),
        72,
    );
}

function createClock() {
    let now = 0;
    let nextId = 1;
    const tasks = new Map();
    return {
        now: () => now,
        schedule(callback, delay) {
            const id = nextId;
            nextId += 1;
            tasks.set(id, { callback, at: now + Math.max(0, delay) });
            return id;
        },
        cancel(id) {
            tasks.delete(id);
        },
        advance(duration) {
            const target = now + duration;
            while (tasks.size) {
                const next = [...tasks.entries()].sort((left, right) => left[1].at - right[1].at)[0];
                if (!next || next[1].at > target) break;
                tasks.delete(next[0]);
                now = next[1].at;
                next[1].callback();
            }
            now = target;
        },
    };
}

function createBuffer(clock, rendered, options = {}) {
    return new AdaptiveStreamBuffer({
        now: clock.now,
        schedule: (callback, delay) => clock.schedule(callback, delay),
        cancelSchedule: (id) => clock.cancel(id),
        onRender: (value) => rendered.push(value),
        tickMs: 20,
        prebufferChars: 6,
        prebufferMs: 60,
        initialRate: 24,
        minRate: 12,
        maxRate: 120,
        maxFinishRate: 360,
        finishWindowMs: 300,
        ...options,
    });
}

test('adaptive buffer turns a burst into bounded typewriter increments', () => {
    const clock = createClock();
    const rendered = [];
    const buffer = createBuffer(clock, rendered);

    buffer.enqueue('abcdefghijklmnopqrst');
    clock.advance(120);

    assert.ok(rendered.length >= 1);
    assert.ok(rendered.at(-1).length > 0);
    assert.ok(rendered.at(-1).length < 20);
    for (let index = 1; index < rendered.length; index += 1) {
        assert.ok(rendered[index].length - rendered[index - 1].length <= 8);
    }
});

test('arrival rate adapts the display pace while retaining a queue', () => {
    const clock = createClock();
    const rendered = [];
    const buffer = createBuffer(clock, rendered);

    buffer.enqueue('ab');
    clock.advance(200);
    buffer.enqueue('cdefghijklmnopqrstuv');
    clock.advance(120);

    const stats = buffer.getStats();
    assert.ok(stats.arrivalRate > 100);
    assert.ok(stats.displayRate > 24);
    assert.ok(stats.pending > 0);
});

test('an idle network gap is not cashed in as a display burst', () => {
    const clock = createClock();
    const rendered = [];
    const buffer = createBuffer(clock, rendered);

    buffer.enqueue('abcdef');
    clock.advance(1000);
    assert.equal(rendered.at(-1), 'abcdef');

    const rendersBeforeBurst = rendered.length;
    buffer.enqueue('ghijklmnopqrstuvwxyz');
    clock.advance(0);

    const immediateRenders = rendered.slice(rendersBeforeBurst);
    assert.ok(immediateRenders.length <= 1);
    if (immediateRenders.length) {
        assert.ok(immediateRenders[0].length - 6 <= 1);
    }
});

test('finish reconciles the canonical response and drains the tail', async () => {
    const clock = createClock();
    const rendered = [];
    const buffer = createBuffer(clock, rendered);

    buffer.enqueue('Hello wor');
    clock.advance(100);
    const finished = buffer.finish('Hello world!');
    clock.advance(1200);

    assert.equal(await finished, 'Hello world!');
    assert.equal(rendered.at(-1), 'Hello world!');
    assert.equal(buffer.getStats().pending, 0);
});

test('reset drops queued intermediate model text', () => {
    const clock = createClock();
    const rendered = [];
    const buffer = createBuffer(clock, rendered);

    buffer.enqueue('temporary tool-call prose');
    clock.advance(80);
    buffer.reset();
    clock.advance(1000);

    assert.equal(buffer.getStats().pending, 0);
    assert.equal(buffer.getStats().rendered, 0);
});

test('grapheme splitting never tears emoji or combining marks', () => {
    assert.deepEqual(splitGraphemes('A👍🏽e\u0301'), ['A', '👍🏽', 'e\u0301']);
});

test('chat stream wires tokens and reasoning through the secondary buffers', () => {
    const root = path.resolve(__dirname, '..');
    const htmlSource = fs.readFileSync(path.join(root, 'web/index.html'), 'utf8');
    assert.match(htmlSource, /stream-typewriter\.js/);
    assert.match(appSource, /streamView\.enqueueContent\(chunk\)/);
    assert.match(appSource, /streamView\.enqueueReasoning\(chunk\)/);
    assert.match(appSource, /await Promise\.all\(\[/);
    assert.match(appSource, /streamView\.finishContent/);
    assert.match(appSource, /streamView\.finishReasoning/);
});

test('background conversation streaming cannot scroll the visible conversation', () => {
    const streamMessage = { isConnected: true };
    const messagesContainer = {
        scrollTop: 180,
        scrollHeight: 1200,
        clientHeight: 500,
        contains: (element) => element === streamMessage,
    };
    const helpers = createConversationScrollHelpers({
        currentConversationId: 'visible-conversation',
        messagesContainer,
    });

    assert.equal(
        helpers.shouldFollowConversationStream('background-conversation', streamMessage),
        false,
    );
    helpers.scrollToBottom('background-conversation', streamMessage);
    assert.equal(messagesContainer.scrollTop, 180);
});

test('streaming only follows the current conversation while the user remains near the bottom', () => {
    const streamMessage = { isConnected: true };
    const messagesContainer = {
        scrollTop: 650,
        scrollHeight: 1200,
        clientHeight: 500,
        contains: (element) => element === streamMessage,
    };
    const helpers = createConversationScrollHelpers({
        currentConversationId: 'visible-conversation',
        messagesContainer,
    });

    assert.equal(
        helpers.shouldFollowConversationStream('visible-conversation', streamMessage),
        true,
    );
    helpers.scrollToBottom('visible-conversation', streamMessage);
    assert.equal(messagesContainer.scrollTop, 1200);

    messagesContainer.scrollTop = 200;
    assert.equal(
        helpers.shouldFollowConversationStream('visible-conversation', streamMessage),
        false,
    );
});
