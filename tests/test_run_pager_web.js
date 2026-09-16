'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const RunPager = require('../web/static/js/run-pager.js');

test('loads only ten runs, fetches next page on demand, and can go back', async () => {
    const calls = [];
    const pager = RunPager.create({ fetchPage: async request => {
        calls.push(request);
        return request.cursor ? { runs: [{ run_id: 'older' }], has_more: false }
            : { runs: Array.from({ length: 10 }, (_, i) => ({ run_id: `r${i}` })), has_more: true, next_cursor: 'c1' };
    } });
    await pager.refresh();
    assert.deepEqual(calls, [{ limit: 10, cursor: '' }]);
    assert.equal(pager.snapshot().items.length, 10);
    await pager.next();
    assert.deepEqual(calls[1], { limit: 10, cursor: 'c1' });
    assert.equal(pager.snapshot().page, 2);
    await pager.next();
    assert.equal(calls.length, 2);
    await pager.previous();
    assert.equal(pager.snapshot().page, 1);
    assert.equal(calls[2].cursor, '');
});

test('failed next page preserves current page and retries the same cursor', async () => {
    let fail = true;
    const pager = RunPager.create({ fetchPage: async ({ cursor }) => {
        if (!cursor) return { runs: [{ run_id: 'first' }], has_more: true, next_cursor: 'next' };
        if (fail) throw new Error('offline');
        return { runs: [{ run_id: 'second' }] };
    } });
    await pager.refresh();
    await pager.next();
    assert.equal(pager.snapshot().error, 'offline');
    assert.equal(pager.snapshot().page, 1);
    assert.equal(pager.snapshot().items[0].run_id, 'first');
    fail = false;
    await pager.refresh(); // Retry button retries the failed next-page request.
    assert.equal(pager.snapshot().page, 2);
    assert.equal(pager.snapshot().items[0].run_id, 'second');
});

test('duplicate clicks coalesce and account reset discards stale responses', async () => {
    const responses = [];
    const pager = RunPager.create({ fetchPage: () => new Promise(resolve => responses.push(resolve)) });
    const old = pager.refresh();
    assert.equal(pager.refresh(), old);
    await Promise.resolve();
    pager.reset();
    const next = pager.refresh();
    await Promise.resolve();
    responses[0]({ runs: [{ run_id: 'old-account' }] });
    await old;
    assert.equal(pager.snapshot().loading, true);
    assert.deepEqual(pager.snapshot().items, []);
    responses[1]({ runs: [{ run_id: 'new-account' }] });
    await next;
    assert.equal(pager.snapshot().items[0].run_id, 'new-account');
});

test('invalid cursor response remains retryable and empty pages end pagination', async () => {
    let invalid = true;
    const pager = RunPager.create({ fetchPage: async () => invalid ? { has_more: true } : { runs: [] } });
    await pager.refresh();
    assert.match(pager.snapshot().error, /cursor/);
    invalid = false;
    await pager.refresh();
    assert.equal(pager.snapshot().error, '');
    assert.equal(pager.snapshot().hasMore, false);
});

test('application loads pager before app and no longer requests fifty runs', () => {
    const app = fs.readFileSync(path.join(__dirname, '../web/static/js/app.js'), 'utf8');
    const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
    assert.ok(html.indexOf('/run-pager.js') < html.indexOf('/app.js'));
    assert.ok(html.includes('/run-pager.js'));
    assert.doesNotMatch(app, /\/api\/runs\?limit=50/);
    assert.match(app, /runPager\?\.reset\(\)/);
});

test('hidden trace page does no DOM work and visible list uses just the selected page', () => {
    const app = fs.readFileSync(path.join(__dirname, '../web/static/js/app.js'), 'utf8');
    const start = app.indexOf('function renderRuns()');
    const end = app.indexOf('\nfunction renderRunPagination', start);
    const source = app.slice(start, end);
    const hidden = vm.createContext({ activeView: 'chat' });
    vm.runInContext(source + '\nrenderRuns();', hidden); // No DOM or run globals needed.
    const context = vm.createContext({ activeView: 'trace', runsError: '',
        runs: [{ run_id: 'cached' }, { run_id: 'on-page' }], selectedRunId: 'on-page',
        runPager: { snapshot: () => ({ items: [{ run_id: 'on-page' }] }) },
        runList: { innerHTML: '' }, renderRunPagination: () => '<nav>pager</nav>',
        runStatusClass: () => '', runQueryText: run => run.run_id, truncateText: text => text,
        runScenarioLabel: () => '', getRunAgent: () => null, formatTime: () => '',
        escapeAttr: String, escapeHtml: String, t: String, shortRunId: String,
        renderRunDetail: () => {},
    });
    vm.runInContext(source + '\nrenderRuns();', context);
    assert.match(context.runList.innerHTML, /data-run-id="on-page"/);
    assert.doesNotMatch(context.runList.innerHTML, /cached/);
    assert.match(context.runList.innerHTML, /<nav>pager/);
});
