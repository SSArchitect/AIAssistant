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
        renderTodoMarkdown: (value) => String(value || ''),
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

function renderTodoMarkdownForTest(value, options = {}) {
    const sources = [
        extractFunctionDeclaration('normalizeTodoMarkdown'),
        extractFunctionDeclaration('renderTodoMarkdown'),
        extractFunctionDeclaration('formatContent'),
        extractFunctionDeclaration('renderInlineMarkdown'),
    ];
    const context = {
        escapeAttr: escapeHtmlForTest,
        escapeHtml: escapeHtmlForTest,
        isMarkdownTableStart: () => false,
        renderCodeCopyButton: () => '',
        renderMediaMarkdown: () => {
            throw new Error('todo markdown must not render media');
        },
        renderSafeLink: (url, label) => `<a href="${escapeHtmlForTest(url)}">${escapeHtmlForTest(label)}</a>`,
    };
    return vm.runInNewContext(
        `${sources.join('\n')}\nrenderTodoMarkdown(value, options);`,
        { ...context, value, options },
    );
}

function escapeHtmlForTest(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function renderParametersForTest(parameters) {
    const source = extractFunctionDeclaration('renderParameters');
    return vm.runInNewContext(
        `${source}\nrenderParameters(parameters);`,
        {
            escapeHtml: escapeHtmlForTest,
            parameters,
            t: (key) => ({
                'tools.markdown': 'Markdown',
                'tools.optional': 'Optional',
                'tools.required': 'Required',
            }[key] || key),
        },
    );
}

function renderTodoSidePanelForTest({ scope, items = [], suggestions = [], byDate = {}, loading = false }) {
    const sources = [
        extractFunctionDeclaration('renderTodoSidePanel'),
        extractFunctionDeclaration('renderTodoMonthDetailPanel'),
    ];
    const context = {
        escapeAttr: escapeHtmlForTest,
        escapeHtml: escapeHtmlForTest,
        formatTodoDateLabel: (dateKey) => dateKey,
        items,
        loading,
        mapTodoItemsByDate: () => byDate,
        renderTodoItem: (item, dateKey) => `<article data-todo-detail="${item.id}" data-occurrence-date="${dateKey}">${item.title}</article>`,
        renderTodoSuggestion: (suggestion) => `<article data-todo-suggestion="${suggestion.id}">${suggestion.title}</article>`,
        scope,
        suggestions,
        t: (key, values = {}) => ({
            'pulse.loading': '加载中',
            'todos.monthDayDetails': `${values.date} 的待办`,
            'todos.monthDayEmpty': '这一天没有待办',
            'todos.noSuggestions': '暂无建议',
            'todos.refreshSuggestions': '刷新建议',
            'todos.suggestions': '建议',
            'todos.suggestionsHint': '建议说明',
        }[key] || key),
        todoMonthRange: () => ({ start: '2026-09-01', end: '2026-09-30' }),
        todoSelectedMonthDate: () => '2026-09-12',
        todoState: {
            loading,
            month: '2026-09',
            suggestionRefreshing: false,
        },
    };
    return vm.runInNewContext(
        `${sources.join('\n')}\nrenderTodoSidePanel(scope, items, suggestions);`,
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

test('month view replaces suggestions with selected-date todo details', () => {
    const selectedTodo = { id: 'selected', title: '准备月度复盘' };
    const html = renderTodoSidePanelForTest({
        scope: 'month',
        items: [selectedTodo],
        suggestions: [{ id: 'suggestion', title: '不应出现的建议' }],
        byDate: { '2026-09-12': [selectedTodo] },
    });

    assert.match(html, /2026-09-12 的待办/);
    assert.match(html, /data-todo-detail="selected"/);
    assert.match(html, /data-occurrence-date="2026-09-12"/);
    assert.doesNotMatch(html, /data-todo-suggestion/);
});

test('month detail panel shows an empty state for a selected date without todos', () => {
    const html = renderTodoSidePanelForTest({
        scope: 'month',
        byDate: {},
    });

    assert.match(html, /<strong>0<\/strong>/);
    assert.match(html, /这一天没有待办/);
    assert.doesNotMatch(html, /data-todo-detail/);
});

test('non-month views keep the suggestion panel', () => {
    const html = renderTodoSidePanelForTest({
        scope: 'today',
        suggestions: [{ id: 'suggestion', title: '整理收件箱' }],
    });

    assert.match(html, /data-todo-suggestion="suggestion"/);
    assert.match(html, /刷新建议/);
    assert.doesNotMatch(html, /todo-month-detail-panel/);
});

test('todo markdown renders headings, lists, and safe inline emphasis', () => {
    const html = renderTodoMarkdownForTest([
        '# 今日菜单',
        '',
        '- **早餐**：鸡蛋三明治',
        '- 午餐：鸡胸和杂粮饭',
    ].join('\n'));

    assert.match(html, /<h1>今日菜单<\/h1>/);
    assert.match(html, /<ul>/);
    assert.match(html, /<li><strong>早餐<\/strong>：鸡蛋三明治<\/li>/);
});

test('legacy bracket sections become readable markdown blocks', () => {
    const html = renderTodoMarkdownForTest(
        '**周一减脂餐复盘** 📅 今日完整菜单 【早 400kcal】鸡蛋三明治 【午 550kcal】鸡胸和杂粮饭 【复盘要点】记录饱腹感',
        { legacySections: true },
    );

    assert.doesNotMatch(html, /【早 400kcal】/);
    assert.match(html, /<strong>早 400kcal<\/strong> 鸡蛋三明治/);
    assert.match(html, /<strong>午 550kcal<\/strong> 鸡胸和杂粮饭/);
    assert.ok((html.match(/<p>/g) || []).length >= 4);
});

test('sidebar and calendar previews keep only a clean short Markdown title', () => {
    const source = extractFunctionDeclaration('todoTitlePreview');
    const preview = vm.runInNewContext(
        `${source}\ntodoTitlePreview(value);`,
        { value: '**周一减脂餐复盘** 【早餐】鸡蛋三明治 【午餐】鸡胸饭' },
    );

    assert.equal(preview, '周一减脂餐复盘');
});

test('todo markdown escapes raw HTML and never enables media blocks', () => {
    const html = renderTodoMarkdownForTest('<img src=x onerror=alert(1)>');

    assert.doesNotMatch(html, /<img\s/);
    assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
});

test('todo editors use multiline Markdown fields with explicit submit shortcut', () => {
    assert.match(appSource, /<textarea class="todo-notes-input"[^>]*maxlength="4000"/);
    assert.match(appSource, /<textarea class="todo-edit-notes"[^>]*maxlength="4000"/);
    assert.match(
        appSource,
        /event\.target\.matches\?\.\('textarea'\) && !event\.ctrlKey && !event\.metaKey/,
    );
});

test('tool parameter details identify Markdown-capable inputs', () => {
    const html = renderParametersForTest([{
        name: 'notes',
        type: 'string',
        description: 'Todo details',
        required: false,
        input_format: 'markdown',
    }]);

    assert.match(html, /class="param-format">Markdown<\/span>/);
    assert.match(html, /class="param-name">notes<\/span>/);
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
