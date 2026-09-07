'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ThinkingProcess = require('../web/static/js/thinking-process.js');
const { createState, mergeTimeline, toolName } = ThinkingProcess;
const appSource = fs.readFileSync(path.join(__dirname, '../web/static/js/app.js'), 'utf8');

const event = (id, type, payload = {}) => ({ id, type, payload, status: 'completed' });

function rendererContext(overrides = {}) {
    const escape = value => String(value).replace(/[&<>"']/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[char]);
    const context = vm.createContext({
        ThinkingProcess, traceCopy: zh => zh, escapeHtml: escape, escapeAttr: escape,
        buildProcessTimeline: () => [], ...overrides,
    });
    for (const name of ['renderProcessPanel', 'renderProcessPanelInto', 'captureProcessScrollState',
        'restoreProcessScrollState', 'processTotalDuration', 'formatProcessDuration',
        'processIcon', 'renderProcessTimelineItem', 'processStatusLabel']) {
        const start = appSource.indexOf(`function ${name}(`);
        if (start < 0) continue;
        vm.runInContext(appSource.slice(start, appSource.indexOf('\nfunction ', start + 1)), context);
    }
    return context;
}

test('thinking header summarizes actual model rounds and tool calls without counting results twice', () => {
    const traces = [event('m1', 'model.started', { round: 1 }),
        event('r1', 'model.reasoning', { model_event_id: 'm1', round: 1 }),
        event('t1', 'tool.started'), event('tr1', 'tool.completed'),
        event('m2', 'model.started', { round: 2 })];
    assert.deepEqual(ThinkingProcess.summarize(traces), { rounds: 2, toolCalls: 1 });
    assert.deepEqual(ThinkingProcess.summarize([traces[1]]), { rounds: 1, toolCalls: 0 });
    assert.deepEqual(ThinkingProcess.summarize([]), { rounds: 0, toolCalls: 0 });
    assert.deepEqual(ThinkingProcess.summarize(null), { rounds: 0, toolCalls: 0 });
    const context = rendererContext();
    const html = context.renderProcessPanel(traces, { live: true, expanded: true });
    assert.match(html, /2 轮思考/);
    assert.match(html, /1 次工具调用/);
    assert.match(html, /class="process-summary-icon"/);
    assert.match(html, /aria-hidden="true"/);
    assert.match(html, /正在分析任务/);
    assert.doesNotMatch(context.renderProcessPanel([], { live: true }), /0 轮|0 次/);
    assert.equal(context.renderProcessPanel([], { live: false }), '');
});

test('timeline presents readable status and duration while escaping reasoning and tool result content', () => {
    const context = rendererContext();
    const item = { id: 'result-1', type: 'tool.failed', kind: 'tool', status: 'error',
        label: '结果 · calculator', detail: '<script>bad()</script>', meta: ['12ms'], links: [], result: '<img src=x onerror=bad()>' };
    const html = context.renderProcessTimelineItem(item);
    assert.match(html, /process-item-marker/);
    assert.match(html, /process-item-duration[^>]*>12ms/);
    assert.match(html, /异常/);
    assert.match(html, /&lt;script&gt;bad\(\)&lt;\/script&gt;/);
    assert.match(html, /data-process-disclosure="result-1"/);
    assert.match(html, /&lt;img src=x onerror=bad\(\)&gt;/);
    assert.doesNotMatch(html, /<script>|<img /);
    const completed = context.renderProcessTimelineItem({ ...item, status: 'completed' });
    assert.match(completed, /class="visually-hidden">完成/);
});

test('tool result disclosure stays expanded as streaming replaces timeline markup', () => {
    let replaced = false;
    const before = { dataset: { processDisclosure: 'result-1' }, open: true };
    const after = { dataset: { processDisclosure: 'result-1' }, open: false };
    const unrelated = { dataset: { processDisclosure: 'result-2' }, open: false };
    const list = { scrollTop: 24, scrollHeight: 400, clientHeight: 100 };
    const container = {
        querySelector: () => list,
        querySelectorAll: () => replaced ? [after, unrelated] : [before],
        set innerHTML(value) { replaced = true; },
    };
    rendererContext().renderProcessPanelInto(container, '<details>updated</details>');
    assert.equal(after.open, true);
    assert.equal(unrelated.open, false);
    assert.equal(list.scrollTop, 24);
});

test('thinking opens during every tool round, collapses once for the final answer, and respects later toggles', () => {
    const state = createState();
    assert.equal(state.expanded, true);
    state.setExpanded(false);
    state.resume();
    assert.equal(state.expanded, false);
    state.setExpanded(true);
    state.startAnswer();
    assert.equal(state.expanded, false);
    state.setExpanded(true);
    state.startAnswer();
    state.finish();
    assert.equal(state.expanded, true);
    assert.equal(state.live, false);
});

test('failure before an answer keeps the thinking history available', () => {
    const state = createState();
    state.finish();
    assert.equal(state.expanded, true);
    assert.equal(state.live, false);
});

test('reasoning is inserted in its own round even when traces arrive before SSE deltas', () => {
    const traces = [event('m1', 'model.started', { round: 1 }), event('t1', 'tool.started'),
        event('r1', 'tool.completed'), event('m2', 'model.started', { round: 2 }), event('done', 'run.completed')];
    const state = createState();
    state.appendReasoning('first ', { model_event_id: 'm1', round: 1 });
    state.appendReasoning('plan', { model_event_id: 'm1', round: 1 });
    state.appendReasoning('second plan', { model_event_id: 'm2', round: 2 });
    const timeline = mergeTimeline(traces, state.reasoningEvents(), 'first plansecond plan');
    assert.deepEqual(timeline.map(item => item.type), [
        'model.started', 'model.reasoning', 'tool.started', 'tool.completed',
        'model.started', 'model.reasoning', 'run.completed',
    ]);
    assert.equal(timeline[1].payload.text, 'first plan');
    assert.equal(timeline[5].payload.text, 'second plan');
});

test('persisted round reasoning replaces live text and aggregate fallback without duplication', () => {
    const traces = [event('m1', 'model.started'), event('thought', 'model.reasoning', {
        model_event_id: 'm1', text: 'complete plan', round: 1,
    }), event('tool', 'tool.completed')];
    const state = createState();
    state.appendReasoning('partial', { model_event_id: 'm1', round: 1 });
    const restored = mergeTimeline(traces, state.reasoningEvents(), 'complete plan');
    assert.equal(restored.filter(item => item.type === 'model.reasoning').length, 1);
    assert.equal(restored[1].payload.text, 'complete plan');
    assert.deepEqual(mergeTimeline(traces, [], 'complete plan'), traces);
});

test('legacy saved reasoning remains visible and empty reasoning adds no item', () => {
    const traces = [event('done', 'run.completed')];
    assert.equal(mergeTimeline(traces, [], 'old reasoning')[0].payload.text, 'old reasoning');
    assert.deepEqual(mergeTimeline(traces, [], ''), traces);
});

test('completed tool calls stop showing as running and legacy tool names remain readable', () => {
    const started = { ...event('t', 'tool.started'), status: 'running', step_id: 'call-1', title: 'Tool search' };
    const finished = { ...event('r', 'tool.completed'), step_id: 'call-1', title: 'Tool search completed' };
    assert.equal(mergeTimeline([started, finished])[0].status, 'completed');
    assert.equal(started.status, 'running');
    assert.equal(toolName(started), 'search');
    assert.equal(toolName(finished), 'search');
    assert.equal(toolName({ payload: { name: 'calculator' }, title: 'Tool old' }), 'calculator');
    assert.equal(toolName({}), '');
});

test('live component stays open with a task card, hides provisional text, and preserves manual reopening', () => {
    const children = {};
    const element = () => ({ dataset: {}, classList: { toggle() {}, remove() {} }, listeners: {},
        addEventListener(name, callback) { this.listeners[name] = callback; }, contains: () => true });
    const div = { ...element(), querySelector: selector => children[selector] ||= element() };
    const renders = [];
    const context = vm.createContext({
        ThinkingProcess: { createState, mergeTimeline }, currentConversationId: 'c', currentAgentId: 'super_chat', STREAM_TYPEWRITER: null,
        document: { createElement: () => div }, messagesContainer: { querySelector: () => null, appendChild() {} },
        renderAssistantActions: () => '', renderProcessPanel: (events, options) => ({ events, ...options }),
        renderProcessPanelInto: (container, view) => renders.push(view),
        createAdaptiveTypingBuffer: render => ({ enqueue: render, setImmediate: render, reset() {} }),
        shouldFollowConversationStream: () => false, formatContent: value => value,
        updateCopyButtonState() {}, updateAssistantActions() {}, renderApprovalCards: () => '',
        renderInlineLongTask: () => '<div>task card</div>',
    });
    const start = appSource.indexOf('function appendStreamingAssistantMessage(');
    vm.runInContext(appSource.slice(start, appSource.indexOf('\nfunction ', start + 1)), context);
    const view = context.appendStreamingAssistantMessage('question', 'c');
    view.setTrace([event('m1', 'model.started', { round: 1 })]);
    assert.equal(renders.at(-1).expanded, true);
    view.enqueueReasoning('plan', { model_event_id: 'm1', round: 1 });
    view.noteProvisional('Checking with a tool');
    assert.equal(children['.streaming-content'].innerHTML, '');
    view.moveContentToProcess();
    assert.equal(renders.at(-1).expanded, true);
    view.setContent('final answer');
    assert.equal(renders.at(-1).expanded, false);
    assert.equal(renders.at(-1).live, false);
    children['.streaming-trace'].listeners.click({ target: { closest: () => ({ closest: () => ({ open: false }) }) } });
    view.setTrace([event('done', 'run.completed')]);
    assert.equal(renders.at(-1).expanded, true);
    assert.equal(children['.streaming-content'].innerHTML, 'final answer');
});
