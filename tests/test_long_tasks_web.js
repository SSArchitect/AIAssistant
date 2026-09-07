'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { summarize, renderCard, createTracker } = require('../web/static/js/long-tasks.js');
const run = (status = 'running') => ({ run_id: 'r', conversation_id: 'c', user_id: 'a', agent_id: 'super_chat',
    input: '<img onerror=alert(1)>', status, started_at: '2026-09-06T00:00:00Z', events: [
        { type: 'media.task.progress', run_id: 'r', created_at: '2026-09-06T00:00:01Z', payload: { kind: 'video', stage: 'queued' } },
    ] });

test('card shows true phase, elapsed time, and escaped user text without fabricated percentages', () => {
    const task = summarize(run(), Date.parse('2026-09-06T00:02:00Z'));
    assert.equal(task.kind, 'video');
    assert.equal(task.stage, 'queued');
    assert.equal(task.elapsed, 120);
    assert.match(renderCard(task, 'zh'), /排队中/);
    assert.match(renderCard(task, 'zh'), /&lt;img/);
    assert.doesNotMatch(renderCard(task), /<img|\d+%/);
});

test('unknown media outcome is not reported as successful or definitely failed', () => {
    const value = run('completed');
    value.events[0].payload.stage = 'unknown';
    assert.equal(summarize(value).state, 'attention');
    assert.match(renderCard(summarize(value), 'zh'), /尚未确认/);
});

test('research stages and restart interruption are meaningful terminal states', () => {
    const value = run();
    value.events = [{ type: 'research.step_summary.started', payload: {} }];
    assert.equal(summarize(value).stage, 'summarizing');
    value.status = 'interrupted';
    assert.equal(summarize(value).state, 'interrupted');
    assert.match(renderCard(summarize(value), 'zh'), /服务重启/);
});

test('nested run completion cannot finish the parent task', () => {
    const value = run();
    value.events.push({ type: 'run.completed', run_id: 'child', payload: {} });
    assert.equal(summarize(value).state, 'running');
});

test('tracker persists completion once, respects muted tasks and isolates accounts', () => {
    const values = new Map();
    const storage = { getItem: k => values.get(k), setItem: (k, v) => values.set(k, v) };
    const tracker = createTracker(storage);
    tracker.setAccount('a');
    assert.equal(tracker.update([run()]).length, 0);
    assert.equal(tracker.update([run('completed')]).length, 1);
    assert.equal(tracker.update([run('completed')]).length, 0);
    const reloaded = createTracker(storage);
    reloaded.setAccount('a');
    assert.equal(reloaded.update([run('completed')]).length, 0);
    reloaded.setAccount('b');
    assert.equal(reloaded.update([run()]).length, 0);
    assert.equal(reloaded.tasks().length, 0);
    reloaded.setAccount('a');
    reloaded.mute('muted');
    const muted = { ...run(), run_id: 'muted' };
    reloaded.update([muted]);
    assert.equal(reloaded.update([{ ...muted, status: 'completed' }]).length, 0);
});

test('completed while away notifies on reload only if previously tracked', () => {
    const values = new Map();
    const storage = { getItem: k => values.get(k), setItem: (k,v) => values.set(k,v) };
    const first = createTracker(storage); first.setAccount('a'); first.update([run()]);
    const second = createTracker(storage); second.setAccount('a');
    assert.equal(second.update([run('completed')]).length, 1);
    const fresh = createTracker(); fresh.setAccount('a');
    assert.equal(fresh.update([run('completed')]).length, 0);
});

test('late running snapshots cannot reopen a completed task', () => {
    const tracker = createTracker(); tracker.setAccount('a');
    tracker.update([run()]); tracker.update([run('completed')]); tracker.update([run()]);
    assert.equal(tracker.tasks()[0].active, false);
});

test('submission tracked before tool discovery can notify when it finishes while away', () => {
    const values = new Map();
    const storage = { getItem: k => values.get(k), setItem: (k,v) => values.set(k,v) };
    const tracker = createTracker(storage); tracker.setAccount('a');
    const submitted = { ...run(), started_at: new Date().toISOString(), events: [] };
    tracker.update([submitted]);
    const restored = createTracker(storage); restored.setAccount('a');
    assert.equal(restored.update([run('completed')]).length, 1);
});

const fs = require('node:fs');
const vm = require('node:vm');
const appSource = fs.readFileSync(require('node:path').join(__dirname, '../web/static/js/app.js'), 'utf8');
const pollSource = appSource.slice(appSource.indexOf('async function pollLongTasks()'), appSource.indexOf('\nfunction startLongTaskPolling()'));
function pollingContext(fetch) {
    const received = [];
    const context = vm.createContext({ longTaskTracker: {}, longTaskFetch: null, longTaskAccount: 'a:token',
        currentUserId: 'a', currentAccountToken: 'token', document: { hidden: false }, navigator: { onLine: true },
        longTaskConnectionLost: false, apiCall: fetch, resetLongTasks() {}, renderLongTasks() {},
        updateLongTasks: value => received.push(value) });
    vm.runInContext(pollSource, context);
    return { context, received };
}
test('a late task response from a previous account is discarded', async () => {
    let resolve;
    const { context, received } = pollingContext(() => new Promise(done => { resolve = done; }));
    const pending = context.pollLongTasks();
    context.currentUserId = 'b'; context.currentAccountToken = 'other';
    resolve({ runs: [run()] }); await pending;
    assert.equal(received.length, 0);
    assert.equal(context.longTaskFetch, null);
});
test('temporary polling failure preserves tasks and allows the next refresh', async () => {
    let fail = true;
    const { context, received } = pollingContext(async () => {
        if (fail) throw new Error('offline');
        return { runs: [run()] };
    });
    await context.pollLongTasks();
    assert.equal(context.longTaskConnectionLost, true);
    assert.equal(received.length, 0);
    fail = false; await context.pollLongTasks();
    assert.equal(context.longTaskConnectionLost, false);
    assert.equal(received.length, 1);
});

test('reminders default on and cards expose an explicit switch without trace links', () => {
    const tracker = createTracker(); tracker.setAccount('a'); tracker.update([run()]);
    assert.equal(tracker.muted('r'), false);
    const html = renderCard(summarize(run()), 'zh');
    assert.match(html, /role="switch" aria-checked="true"/);
    assert.match(html, /提醒已开启/);
    assert.doesNotMatch(html, /data-task-detail|查看详情|Trace/);
});

test('meaningful progress produces persistent unread updates; repeated polls and time changes do not', () => {
    const values = new Map(); const storage = { getItem: k => values.get(k), setItem: (k,v) => values.set(k,v) };
    const tracker = createTracker(storage); tracker.setAccount('a'); tracker.update([run()]);
    const advanced = run(); advanced.events[0].payload.stage = 'running';
    assert.equal(tracker.update([advanced]).length, 0); // progress highlights the feed without a toast
    assert.equal(tracker.tasks()[0].unread, true);
    const reload = createTracker(storage); reload.setAccount('a'); reload.update([advanced]);
    assert.equal(reload.tasks()[0].unread, true);
    reload.markRead('r'); reload.update([advanced], Date.now() + 20000);
    assert.equal(reload.tasks()[0].unread, false);
    reload.update([run('completed')]);
    assert.equal(reload.tasks()[0].unread, true);
    reload.markAllRead(); assert.equal(reload.tasks()[0].unread, false);
});

test('muting clears highlights and suppresses later progress and completion; unmuting does not replay old updates', () => {
    const tracker = createTracker(); tracker.setAccount('a'); tracker.update([run()]);
    const advance = run(); advance.events[0].payload.stage = 'running'; tracker.update([advance]);
    tracker.mute('r'); assert.equal(tracker.tasks()[0].unread, false);
    assert.equal(tracker.update([run('completed')]).length, 0);
    tracker.mute('r'); assert.equal(tracker.tasks()[0].unread, false);
    assert.equal(tracker.update([run('completed')]).length, 0);
});

test('cards directly show reported progress and queue positions, dropping stale queue data after generation starts', () => {
    const value = run(); value.events[0].payload.queue_position = 3;
    assert.match(renderCard(summarize(value), 'zh'), /排队第 3 位/);
    value.events.push({ type: 'media.task.progress', payload: { kind: 'video', stage: 'running', progress_percent: 42 } });
    const html = renderCard(summarize(value), 'zh');
    assert.match(html, /<progress[^>]*value="42"/);
    assert.match(html, /42%/);
    assert.doesNotMatch(html, /排队第 3 位/);
    assert.match(html, /long-task-stages/);
});

test('missing, invalid or ambiguous metrics never invent a percentage or queue position', () => {
    const value = run(); Object.assign(value.events[0].payload, { progress: .5, progress_percent: '42', queue_position: -1 });
    assert.doesNotMatch(renderCard(summarize(value)), /<progress|\d+%|排队第/);
});

test('research reports completed evidence groups as stage progress, not overall completion', () => {
    const value = run(); value.events = [
        { type: 'research.step_summary.started', payload: { chunk: 1, chunk_count: 3 } },
        { type: 'research.step_summary.completed', payload: { chunk: 1 } },
        { type: 'research.step_summary.started', payload: { chunk: 2, chunk_count: 3 } },
    ];
    const html = renderCard(summarize(value), 'zh');
    assert.match(html, /已整理 1 \/ 3 组资料/);
    assert.equal(summarize(value).active, true);
});

test('folded breadcrumb surfaces active and unread counts without requiring expansion', () => {
    const { renderSummary } = require('../web/static/js/long-tasks.js');
    const html = renderSummary([{ active: true, unread: true }, { active: false, unread: true }], 'zh');
    assert.match(html, /1 项进行中/);
    assert.match(html, /2 条未读更新/);
    assert.match(html, /task-update-badge/);
    assert.doesNotMatch(renderSummary([], 'en'), /task-update-badge/);
});

test('background tasks use a floating circular launcher and region without trace interaction', () => {
    const html = fs.readFileSync(require('node:path').join(__dirname, '../web/index.html'), 'utf8');
    assert.match(html, /<section id="task-shelf"[\s\S]*?<button id="btn-tasks" class="task-launcher"/);
    assert.match(html, /id="btn-tasks"[^>]*aria-expanded="false"[^>]*aria-controls="task-shelf-body"/);
    assert.match(html, /id="task-shelf-body"[^>]*role="region"[^>]*hidden/);
    assert.doesNotMatch(html, /<details id="task-shelf"|<summary id="btn-tasks"/);
    assert.match(appSource, /getElementById\('btn-tasks'\)\?\.addEventListener\('click'/);
    assert.doesNotMatch(appSource, /data-task-detail|taskDetail/);
    const handler = appSource.slice(appSource.lastIndexOf("document.addEventListener('click', event => {"));
    assert.match(handler, /markRead\(open.dataset.taskRead\)/);
    assert.match(appSource, /markAllRead\(\)/);
});

test('unread and mute preferences never leak when switching accounts', () => {
    const tracker = createTracker(); tracker.setAccount('a'); tracker.update([run()]);
    const changed = run(); changed.events[0].payload.stage = 'running'; tracker.update([changed]);
    assert.equal(tracker.tasks()[0].unread, true);
    tracker.setAccount('b'); tracker.update([changed]);
    assert.equal(tracker.tasks().length, 0);
});

test('progress percentage updates highlight only meaningful increments, and old progress is ignored', () => {
    const tracker = createTracker(); tracker.setAccount('a');
    const value = run(); value.events[0].payload = { kind: 'video', stage: 'running', progress_percent: 20 };
    tracker.update([value]); tracker.markRead('r');
    value.events[0].payload.progress_percent = 21; tracker.update([value]);
    assert.equal(tracker.tasks()[0].unread, false);
    value.events[0].payload.progress_percent = 30;
    value.events[0].created_at = '2026-09-06T00:00:05Z'; tracker.update([value]);
    assert.equal(tracker.tasks()[0].unread, true);
    tracker.markRead('r');
    tracker.update([run()]);
    assert.equal(tracker.tasks()[0].stage, 'running');
    assert.equal(tracker.tasks()[0].unread, false);
});

function messageRenderContext(hasProcess = true) {
    const context = vm.createContext({
        currentConversationId: 'c', LongTasks: {},
        renderAssistantActions: () => '<footer>actions</footer>', renderUserMessageActions: () => '',
        renderProcessPanel: () => hasProcess ? '<details>execution</details>' : '',
        renderMessageDivider: () => '<hr>', renderInlineLongTask: () => '<section>task-card</section>',
        errorBanner: () => '<p>error-result</p>', renderApprovalPanel: () => '', renderCitationPanel: () => '',
        renderArtifactPanel: () => '', renderInputMeta: () => '', formatContent: text => `<p>${text}</p>`,
        escapeHtml: text => text, escapeAttr: text => text, t: text => text,
    });
    const source = appSource.slice(appSource.indexOf('function renderMessageHtml('), appSource.indexOf('\nfunction renderMessageDivider('));
    vm.runInContext(source, context);
    return context;
}

test('history puts the task card after execution and before success or error results', () => {
    const context = messageRenderContext();
    for (const error of ['', 'provider_error', 'rate_limit']) {
        const html = context.renderMessageHtml('assistant', 'answer', [], '', error, [], 'r');
        assert.ok(html.indexOf('execution') < html.indexOf('task-card'));
        assert.ok(html.indexOf('task-card') < html.indexOf(error ? 'error-result' : '<p>answer'));
        assert.equal((html.match(/task-card/g) || []).length, 1);
    }
});

test('task card renders without a process panel and is absent from user messages', () => {
    const context = messageRenderContext(false);
    const html = context.renderMessageHtml('assistant', 'answer', [], '', '', [], 'r');
    assert.ok(html.indexOf('task-card') < html.indexOf('<p>answer'));
    assert.doesNotMatch(context.renderMessageHtml('user', 'question', [], '', '', [], 'r'), /task-card/);
});

test('live message puts the task card below execution while keeping the result below it', () => {
    const children = {};
    const div = { dataset: {}, querySelector: selector => children[selector] ||= { addEventListener() {} } };
    const context = vm.createContext({
        currentConversationId: 'c', currentAgentId: 'super_chat', STREAM_TYPEWRITER: null,
        document: { createElement: () => div }, messagesContainer: { querySelector: () => null, appendChild() {} },
        renderAssistantActions: () => '', createAdaptiveTypingBuffer: () => ({}),
        ThinkingProcess: require('../web/static/js/thinking-process.js'),
        renderProcessPanel: () => '', renderProcessPanelInto() {},
    });
    const start = appSource.indexOf('function appendStreamingAssistantMessage(');
    const end = appSource.indexOf('\nfunction ', start + 1);
    vm.runInContext(appSource.slice(start, end), context);
    context.appendStreamingAssistantMessage('video', 'c');
    assert.ok(div.innerHTML.indexOf('streaming-trace') < div.innerHTML.indexOf('streaming-task-card'));
    assert.ok(div.innerHTML.indexOf('streaming-task-card') < div.innerHTML.indexOf('streaming-content'));
});

test('read terminal results remain read across changed snapshots and reloads', () => {
    const values = new Map();
    const storage = { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) };
    const tracker = createTracker(storage); tracker.setAccount('a');
    tracker.update([run()]); tracker.update([run('completed')]); tracker.markRead('r');
    const restored = createTracker(storage); restored.setAccount('a');
    const changed = run('completed'); changed.events[0].payload.stage = 'unknown';
    assert.equal(restored.update([changed]).length, 0);
    assert.equal(restored.tasks()[0].unread, false);
});

test('viewing a final result before task polling suppresses its later completion reminder', () => {
    const tracker = createTracker(); tracker.setAccount('a'); tracker.update([run()]);
    tracker.markResultRead('r');
    assert.equal(tracker.update([run('completed')]).length, 0);
    assert.equal(tracker.tasks()[0].unread, false);
    tracker.setAccount('b'); tracker.update([{ ...run(), user_id: 'b' }]);
    assert.equal(tracker.update([{ ...run('completed'), user_id: 'b' }]).length, 1);
});

test('reading running updates still allows a new completion reminder', () => {
    const tracker = createTracker(); tracker.setAccount('a'); tracker.update([run()]);
    tracker.markAllRead();
    assert.equal(tracker.update([run('completed')]).length, 1);
    assert.equal(tracker.tasks()[0].unread, true);
});

test('background task entry and conversation action use the new labels in both languages', () => {
    const { renderSummary } = require('../web/static/js/long-tasks.js');
    assert.match(renderSummary([], 'zh'), /后台任务/);
    assert.match(renderSummary([], 'en'), /Background tasks/);
    assert.match(renderCard(summarize(run()), 'zh'), /跳转至会话/);
    assert.match(renderCard(summarize(run()), 'en'), /Go to conversation/);
    assert.doesNotMatch(renderCard(summarize(run()), 'zh'), /查看结果与会话/);
});

function visibleResultContext() {
    const read = [];
    const rect = { top: 100, bottom: 200, width: 400 };
    const card = { dataset: { taskId: 'r', state: 'completed' },
        getBoundingClientRect: () => rect,
        closest: () => ({ getBoundingClientRect: () => rect }) };
    const context = vm.createContext({ currentUserId: 'a', currentAccountToken: 'token',
        longTaskAccount: 'a:token', activeView: 'chat', currentConversationId: 'c',
        document: { hidden: false }, window: { innerHeight: 800 },
        longTaskTracker: { markResultRead: id => read.push(id) },
        messagesContainer: { getBoundingClientRect: () => ({ top: 50, bottom: 750, width: 500 }),
            querySelectorAll: selector => { assert.match(selector, /:not\(\.streaming\)/); return [card]; } },
    });
    const start = appSource.indexOf('function markVisibleTaskResultsRead()');
    vm.runInContext(appSource.slice(start, appSource.indexOf('\nfunction ', start + 1)), context);
    return { context, card, rect, read };
}

test('visible completed conversation results acknowledge reminders; hidden and running results do not', () => {
    const { context, card, rect, read } = visibleResultContext();
    context.markVisibleTaskResultsRead(); assert.deepEqual(read, ['r']); read.length = 0;
    context.document.hidden = true; context.markVisibleTaskResultsRead();
    context.document.hidden = false; context.activeView = 'home'; context.markVisibleTaskResultsRead();
    context.activeView = 'chat'; context.longTaskAccount = 'b:other'; context.markVisibleTaskResultsRead();
    context.longTaskAccount = 'a:token'; card.dataset.state = 'running'; context.markVisibleTaskResultsRead();
    card.dataset.state = 'completed'; rect.top = 900; rect.bottom = 1000; context.markVisibleTaskResultsRead();
    assert.deepEqual(read, []);
});

test('refreshing the task UI removes read completion toasts and keeps unread toasts', () => {
    const tracker = createTracker(); tracker.setAccount('a'); tracker.update([run()]);
    tracker.update([run('completed')]);
    let removed = 0;
    const notice = { dataset: { taskRead: 'r' }, closest: () => ({ remove: () => removed++ }) };
    const context = vm.createContext({ longTaskTracker: tracker, markVisibleTaskResultsRead() {},
        document: { querySelectorAll: () => [notice], getElementById: () => null } });
    const start = appSource.indexOf('function renderLongTasks()');
    vm.runInContext(appSource.slice(start, appSource.indexOf('\nfunction ', start + 1)), context);
    context.renderLongTasks(); assert.equal(removed, 0);
    tracker.markAllRead(); context.renderLongTasks(); assert.equal(removed, 1);
    const changed = run('completed'); changed.events[0].payload.stage = 'unknown';
    tracker.update([changed]); assert.equal(tracker.tasks()[0].unread, false);
});

test('a result read before initial discovery remains quiet after discovery and stale active polls', () => {
    const tracker = createTracker(); tracker.setAccount('a'); tracker.markResultRead('r');
    tracker.update([run()]);
    assert.equal(tracker.update([run('completed')]).length, 0);
    assert.equal(tracker.tasks()[0].unread, false);
});

function taskPopoverContext() {
    const listeners = {};
    const button = { expanded: 'false', getAttribute() { return this.expanded; },
        setAttribute(key, value) { this.expanded = value; }, focus() { this.focused = true; },
        addEventListener(type, callback) { listeners['button:' + type] = callback; } };
    const body = { hidden: true };
    const shelf = { contains: target => target === button || target === body };
    const elements = { 'btn-tasks': button, 'task-shelf-body': body, 'task-shelf': shelf };
    let renders = 0, polls = 0;
    const context = vm.createContext({ document: { getElementById: id => elements[id],
        addEventListener: (type, callback) => { listeners[type] = callback; } },
        longTaskLauncher: null, renderLongTasks() { renders++; }, pollLongTasks() { polls++; } });
    const start = appSource.indexOf('function setTaskShelfOpen(');
    const end = appSource.indexOf("document.getElementById('task-mark-all-read')", start);
    vm.runInContext(appSource.slice(start, end), context);
    return { context, button, body, listeners, counts: () => ({ renders, polls }) };
}

test('floating task cards toggle without navigation and keep disclosure accessibility in sync', () => {
    const { button, body, listeners, counts } = taskPopoverContext();
    listeners['button:click']();
    assert.equal(button.expanded, 'true'); assert.equal(body.hidden, false);
    assert.deepEqual(counts(), { renders: 1, polls: 1 });
    listeners['button:click']();
    assert.equal(button.expanded, 'false'); assert.equal(body.hidden, true);
    assert.equal(counts().polls, 1);
});

test('outside click and Escape collapse floating tasks; inside interaction leaves them open', () => {
    const { context, button, body, listeners } = taskPopoverContext();
    context.setTaskShelfOpen(true);
    listeners.pointerdown({ target: body }); assert.equal(body.hidden, false);
    listeners.pointerdown({ target: {} }); assert.equal(body.hidden, true);
    context.setTaskShelfOpen(true);
    listeners.keydown({ key: 'Escape', preventDefault() {} });
    assert.equal(body.hidden, true); assert.equal(button.focused, true);
    assert.equal(button.expanded, 'false');
});

test('floating task cards close when keyboard focus leaves, without trapping focus', () => {
    const { context, body, listeners } = taskPopoverContext();
    context.setTaskShelfOpen(true);
    listeners.focusin({ target: body }); assert.equal(body.hidden, false);
    listeners.focusin({ target: {} }); assert.equal(body.hidden, true);
});


test('circular launcher shows unread first, active count otherwise, and an accessible background task label', () => {
    const { renderLauncher } = require('../web/static/js/long-tasks.js');
    const tasks = [{ active: true, unread: true }, { active: true, unread: false }];
    const html = renderLauncher(tasks, 'zh');
    assert.match(html, /后台任务，2 项进行中，1 条未读更新/);
    assert.match(html, /task-launcher-count is-unread[^>]*>1</);
    assert.match(html, /<svg[^>]*aria-hidden="true"/);
    assert.doesNotMatch(html, /task-crumb|task-breadcrumb/);
    assert.match(renderLauncher([{ active: true, unread: false }]), /task-launcher-count"[^>]*>1</);
    assert.doesNotMatch(renderLauncher([], 'en'), /task-launcher-count/);
    assert.match(renderLauncher([], 'en'), /Background tasks/);
    assert.match(renderLauncher(Array.from({ length: 100 }, () => ({ unread: true }))), />99\+</);
});

test('launcher visibility follows active and unread work, including queued and approval tasks', () => {
    const { shouldShowLauncher } = require('../web/static/js/long-tasks.js');
    assert.equal(shouldShowLauncher([]), false);
    assert.equal(shouldShowLauncher([{ active: false, unread: false }]), false);
    for (const state of ['queued', 'running', 'approval']) {
        assert.equal(shouldShowLauncher([{ active: true, unread: false, state }]), true);
    }
    assert.equal(shouldShowLauncher([{ active: false, unread: true }]), true);
    const tracker = createTracker(); tracker.setAccount('a'); tracker.update([run()]);
    tracker.update([run('completed')]); assert.equal(shouldShowLauncher(tracker.tasks()), true);
    tracker.markAllRead(); assert.equal(shouldShowLauncher(tracker.tasks()), false);
});

function movableLauncher(saved = null) {
    const { createLauncherController } = require('../web/static/js/long-tasks.js');
    const listeners = {}, values = new Map(saved ? [['long-task-launcher-position', JSON.stringify(saved)]] : []);
    const button = { style: {}, addEventListener: (type, fn) => { listeners[type] = fn; },
        setPointerCapture() {}, hasPointerCapture: () => true, releasePointerCapture() {} };
    const shelf = { style: {}, classList: { toggle() {} } }, body = { style: {} };
    const area = { width: 800, height: 700, top: 70, bottom: 110 };
    let closed = 0;
    const controller = createLauncherController({ button, shelf, body, getArea: () => area,
        storage: { getItem: k => values.get(k), setItem: (k, v) => values.set(k, v) },
        onDragStart: () => closed++ });
    const event = (x, y, extra = {}) => ({ clientX: x, clientY: y, pointerId: 1, button: 0, isPrimary: true, preventDefault() {}, ...extra });
    return { controller, button, shelf, body, area, listeners, values, event, closed: () => closed };
}

test('drag moves the launcher, saves its position and suppresses only the drag click', () => {
    const ui = movableLauncher();
    const before = parseFloat(ui.shelf.style.left);
    ui.listeners.pointerdown(ui.event(100, 200));
    ui.listeners.pointermove(ui.event(180, 150));
    assert.equal(parseFloat(ui.shelf.style.left), before + 80);
    assert.equal(ui.closed(), 1);
    ui.listeners.pointerup(ui.event(180, 150));
    assert.equal(ui.controller.consumeClick({ detail: 1 }), true);
    assert.equal(ui.controller.consumeClick({ detail: 1 }), false);
    const saved = JSON.parse(ui.values.get('long-task-launcher-position'));
    assert.equal(movableLauncher(saved).shelf.style.left, ui.shelf.style.left);
});

test('a tap or small finger jitter opens normally; secondary pointers do not drag', () => {
    const ui = movableLauncher(); const before = ui.shelf.style.left;
    ui.listeners.pointerdown(ui.event(10, 20, { button: 2 }));
    ui.listeners.pointermove(ui.event(200, 200)); assert.equal(ui.shelf.style.left, before);
    ui.listeners.pointerdown(ui.event(10, 20));
    ui.listeners.pointermove(ui.event(13, 22)); ui.listeners.pointerup(ui.event(13, 22));
    assert.equal(ui.controller.consumeClick({ detail: 1 }), false);
    assert.equal(ui.values.size, 0);
});

test('drag bounds and popover placement stay inside the workspace after a narrow resize', () => {
    const ui = movableLauncher();
    ui.listeners.pointerdown(ui.event(100, 200)); ui.listeners.pointermove(ui.event(-2000, -2000));
    ui.listeners.pointerup(ui.event(-2000, -2000));
    assert.equal(parseFloat(ui.shelf.style.left), 8);
    assert.equal(parseFloat(ui.shelf.style.top), 70);
    assert.equal(ui.body.style.bottom, 'auto'); // near the top, open below the launcher
    ui.area.width = 320; ui.area.height = 500; ui.controller.layout();
    assert.ok(parseFloat(ui.shelf.style.left) + parseFloat(ui.body.style.left) >= 8);
    assert.ok(parseFloat(ui.body.style.width) <= 304);
});

test('cancelled drags restore the last position and do not overwrite storage', () => {
    const ui = movableLauncher({ x: .7, y: .6 }); const before = ui.shelf.style.left;
    ui.listeners.pointerdown(ui.event(100, 100)); ui.listeners.pointermove(ui.event(170, 100));
    ui.listeners.pointercancel(ui.event(170, 100));
    assert.equal(ui.shelf.style.left, before);
    assert.deepEqual(JSON.parse(ui.values.get('long-task-launcher-position')), { x: .7, y: .6 });
    assert.equal(ui.controller.consumeClick({ detail: 0 }), false); // keyboard activation remains available
});

test('invalid saved coordinates fall back to a usable default', () => {
    const ui = movableLauncher({ x: 'bad', y: 200 });
    assert.equal(Number.isFinite(parseFloat(ui.shelf.style.left)), true);
    assert.ok(parseFloat(ui.shelf.style.top) > ui.area.top);
});

test('the actual task UI hides and closes after the last result is read, and on logout', () => {
    const tracker = createTracker(); tracker.setAccount('a'); tracker.update([run()]);
    const panel = { hidden: true }; let closed = 0;
    const context = vm.createContext({ longTaskTracker: tracker, LongTasks: require('../web/static/js/long-tasks.js'),
        currentUserId: 'a', currentAccountToken: 'token', longTaskLauncher: { layout() {} },
        markVisibleTaskResultsRead() {}, closeTaskShelf() { closed++; },
        document: { querySelectorAll: () => [], getElementById: id => id === 'task-shelf' ? panel : null } });
    const start = appSource.indexOf('function renderLongTasks()');
    vm.runInContext(appSource.slice(start, appSource.indexOf('\nfunction ', start + 1)), context);
    context.renderLongTasks(); assert.equal(panel.hidden, false);
    tracker.update([run('completed')]); context.renderLongTasks(); assert.equal(panel.hidden, false);
    tracker.markAllRead(); context.renderLongTasks(); assert.equal(panel.hidden, true); assert.equal(closed, 1);
    tracker.update([{ ...run(), run_id: 'next' }]); context.renderLongTasks(); assert.equal(panel.hidden, false);
    context.currentAccountToken = ''; context.renderLongTasks(); assert.equal(panel.hidden, true);
});
