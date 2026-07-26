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
    const marker = `function ${name}(`;
    const start = appSource.indexOf(marker);
    assert.notEqual(start, -1, `missing ${name} in app.js`);

    const remainingSource = appSource.slice(start);
    const nextFunctionOffset = remainingSource.slice(marker.length).search(/\nfunction\s+\w+\s*\(/);
    assert.notEqual(nextFunctionOffset, -1, `could not find the end of ${name}`);

    return remainingSource
        .slice(0, marker.length + nextFunctionOffset)
        .trim();
}

function renderTodayTodoList(items) {
    const renderTodoItemSource = extractFunctionDeclaration('renderTodoItem');
    const renderTodoContentSource = extractFunctionDeclaration('renderTodoContent');
    const context = {
        emptyState: () => '',
        escapeAttr: String,
        escapeHtml: String,
        formatTodoScheduleLabel: () => '',
        items,
        renderTodoEditItem: () => '',
        renderTodoMonthView: () => '',
        t: (key) => key,
        todoItemDoneForDate: () => false,
        todoItemTone: () => '',
        todoState: {
            date: '2026-07-27',
            editingId: '',
            loading: false,
        },
        todoTodayKey: () => '2026-07-27',
    };

    return vm.runInNewContext(
        `${renderTodoItemSource}\n${renderTodoContentSource}\nrenderTodoContent('today', items);`,
        context,
    );
}

const TODO_TEST_MESSAGES = {
    'todos.dateDaily': '每天',
    'todos.dateRange': '{start} - {end}',
    'todos.dateWorkdays': '每工作日',
    'todos.noDate': '待排期',
    'todos.overdue': '逾期',
    'todos.starts': '从 {date} 开始',
    'todos.todayLabel': '今天',
    'todos.tomorrow': '明天',
};

function translateTodoTestMessage(key, values = {}) {
    const template = TODO_TEST_MESSAGES[key] || key;
    return template.replace(/\{(\w+)\}/g, (_match, name) => String(values[name] ?? ''));
}

function evaluateTodoDateFormatting(expression, item = {}) {
    const sources = [
        extractFunctionDeclaration('todoItemIsOverdue'),
        extractFunctionDeclaration('formatTodoDateLabel'),
        extractFunctionDeclaration('formatTodoScheduleLabel'),
    ];
    const context = {
        item,
        t: translateTodoTestMessage,
        todoDateKey: () => '2026-07-28',
        todoTodayKey: () => '2026-07-27',
    };

    return vm.runInNewContext(`${sources.join('\n')}\n${expression}`, context);
}

function formatTodoScheduleForTest(item) {
    return evaluateTodoDateFormatting('formatTodoScheduleLabel(item);', item);
}

test('every rendered todo keeps a YYYY-MM-DD occurrence date', () => {
    const items = ['first', 'second', 'third'].map((id) => ({
        id,
        occurrence_date: '2026-07-27',
        priority: 'normal',
        title: id,
    }));

    const html = renderTodayTodoList(items);
    const occurrenceDates = Array.from(
        html.matchAll(/data-todo-occurrence-date="([^"]+)"/g),
        (match) => match[1],
    );

    assert.deepEqual(occurrenceDates, [
        '2026-07-27',
        '2026-07-27',
        '2026-07-27',
    ]);
    assert.ok(occurrenceDates.every((date) => /^\d{4}-\d{2}-\d{2}$/.test(date)));
});

test('past start dates stay neutral for recurring and ranged todos', () => {
    assert.equal(formatTodoScheduleForTest({
        repeat_rule: 'daily',
        start_date: '2026-07-11',
        status: 'open',
    }), '每天 · 从 2026-07-11 开始');

    assert.equal(formatTodoScheduleForTest({
        repeat_rule: 'workdays',
        start_date: '2026-07-11',
        status: 'open',
    }), '每工作日 · 从 2026-07-11 开始');

    assert.equal(formatTodoScheduleForTest({
        repeat_rule: 'once',
        start_date: '2026-07-11',
        due_date: '2026-08-01',
        status: 'open',
    }), '2026-07-11 - 2026-08-01');

    assert.equal(formatTodoScheduleForTest({
        repeat_rule: 'once',
        start_date: '2026-07-11',
        status: 'open',
    }), '从 2026-07-11 开始');
});

test('only unfinished one-time past deadlines are labeled overdue', () => {
    assert.equal(formatTodoScheduleForTest({
        due_date: '2026-07-26',
        repeat_rule: 'once',
        status: 'open',
    }), '逾期 2026-07-26');

    assert.equal(formatTodoScheduleForTest({
        due_date: '2026-07-26',
        repeat_rule: 'once',
        status: 'done',
    }), '2026-07-26');

    assert.equal(formatTodoScheduleForTest({
        due_date: '2026-07-11',
        repeat_rule: 'daily',
        start_date: '2026-07-01',
        status: 'open',
    }), '每天 · 2026-07-01 - 2026-07-11');
});

test('past calendar dates are not labeled overdue by the generic formatter', () => {
    assert.equal(
        evaluateTodoDateFormatting("formatTodoDateLabel('2026-07-11');"),
        '2026-07-11',
    );
});
