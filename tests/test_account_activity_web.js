'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../web/static/js/app.js'), 'utf8');
const activitySource = source.slice(source.indexOf('const accountActivityRequests = new Map();'),
    source.indexOf('async function refreshAll()'));

function fixture() {
    const calls = [];
    const listeners = new Map();
    let now = 100000;
    const add = (type, handler) => listeners.set(type, handler);
    const context = vm.createContext({
        currentUserId: 'alice', currentAccountToken: 'alice-token',
        document: { hidden: false, addEventListener: add },
        window: { addEventListener: add }, navigator: { onLine: true },
        Date: { now: () => now },
        apiCall: async (...args) => { calls.push(args); return { status: 'ok' }; },
    });
    vm.runInContext(activitySource, context);
    context.bindAccountActivityEvents();
    return { context, calls, listeners, advance: ms => { now += ms; } };
}

test('visible visits report activity once per minute, independently for each account', async () => {
    const f = fixture();
    await f.context.recordAccountActivity();
    assert.equal(f.calls.length, 1);
    assert.equal(f.calls[0][0], 'POST');
    assert.equal(f.calls[0][1], '/api/accounts/activity');
    await f.context.recordAccountActivity();
    assert.equal(f.calls.length, 1);
    f.advance(60000);
    await f.context.recordAccountActivity();
    assert.equal(f.calls.length, 2);
    f.context.currentUserId = 'bob';
    f.context.currentAccountToken = 'bob-token';
    await f.context.recordAccountActivity();
    assert.equal(f.calls.length, 3);
});

test('hidden, offline and unauthenticated pages do not report visits', async () => {
    for (const change of [
        c => { c.document.hidden = true; },
        c => { c.navigator.onLine = false; },
        c => { c.currentUserId = ''; },
        c => { c.currentAccountToken = ''; },
    ]) {
        const f = fixture();
        change(f.context);
        await f.context.recordAccountActivity();
        assert.equal(f.calls.length, 0);
    }
});

test('trusted gestures and foreground visits count, synthetic input and polling do not', async () => {
    for (const type of ['pointerdown', 'keydown', 'wheel', 'touchstart']) {
        const f = fixture();
        f.listeners.get(type)({ isTrusted: false });
        assert.equal(f.calls.length, 0);
        f.listeners.get(type)({ isTrusted: true });
        assert.equal(f.calls.length, 1);
    }
    const f = fixture();
    f.context.document.hidden = true;
    f.listeners.get('visibilitychange')();
    assert.equal(f.calls.length, 0);
    f.context.document.hidden = false;
    f.listeners.get('visibilitychange')();
    assert.equal(f.calls.length, 1);
    await new Promise(setImmediate);
    f.advance(7 * 24 * 60 * 60 * 1000);
    assert.equal(f.calls.length, 1, 'elapsed time alone never sends activity');
    f.listeners.get('pageshow')();
    assert.equal(f.calls.length, 2);
    const polling = source.slice(source.indexOf('async function pollLongTasks()'),
        source.indexOf('function renderInlineLongTask('));
    assert.doesNotMatch(polling, /recordAccountActivity/);
    assert.doesNotMatch(activitySource, /setInterval|setTimeout/);
});

test('in-flight requests coalesce and failed requests only retry on a later gesture', async () => {
    const f = fixture();
    let reject;
    let attempts = 0;
    f.context.apiCall = () => { attempts++; return new Promise((resolve, fail) => { reject = fail; }); };
    const first = f.context.recordAccountActivity();
    f.advance(60000);
    await f.context.recordAccountActivity();
    assert.equal(attempts, 1);
    reject(new Error('offline'));
    await first;
    const second = f.context.recordAccountActivity();
    assert.equal(attempts, 2);
    reject(new Error('server unavailable'));
    await second;
    await f.context.recordAccountActivity();
    assert.equal(attempts, 2, 'failures remain throttled');
});

test('startup and account switches report visits and bind activity listeners', () => {
    for (const name of ['bootApp', 'switchAccount']) {
        const start = source.indexOf(`async function ${name}(`);
        const end = source.indexOf('\n}\n', start);
        assert.match(source.slice(start, end), /void recordAccountActivity\(\);/);
    }
    assert.match(source, /\nbindAccountActivityEvents\(\);/);
});
