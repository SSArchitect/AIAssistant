'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../web/static/js/admin.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../web/admin.html'), 'utf8');

function fixture() {
    const elements = Object.fromEntries(['activity-metrics', 'activity-as-of', 'activity-account-rows'].map(id => [id, { innerHTML: '', textContent: '' }]));
    const escapeHtml = value => String(value).replaceAll('<', '&lt;').replaceAll('>', '&gt;');
    const context = vm.createContext({
        document: { getElementById: id => elements[id] },
        t: key => key, escapeHtml,
        formatNumber: n => String(n || 0), formatDateTime: value => value || '-',
        renderAccountCell: (name, id) => `${escapeHtml(name)} (${escapeHtml(id)})`,
        emptyCostRow: (n, message) => `<tr><td colspan="${n}">${escapeHtml(message)}</td></tr>`,
    });
    vm.runInContext(source.slice(source.indexOf('function renderAccountActivity('), source.indexOf('function renderCostAccuracy(')), context);
    return { elements, context };
}

test('admin shows page-only activity, paused accounts and background costs separately', () => {
    const f = fixture();
    f.context.renderAccountActivity([
        { id: 'viewer', name: '<Viewer>', exists: true, last_active_at: 'visit-time', automatic_generation_eligible: true, user_messages_7d: 0 },
        { id: 'inactive', name: 'Inactive', exists: true, last_active_at: 'old-visit', automatic_generation_eligible: false, last_background_at: 'background-time', background_cost: { request_count: 4, total_tokens: 12345 } },
        { id: 'never', name: 'Never used', exists: true, automatic_generation_eligible: false },
        { id: 'deleted', name: 'Deleted account', exists: false },
    ], { as_of: 'now', active_accounts: 1, inactive_accounts: 2, messaging_accounts: 0 });
    const rows = f.elements['activity-account-rows'].innerHTML;
    assert.match(rows, /&lt;Viewer&gt;/);
    assert.match(rows, /visit-time/);
    assert.match(rows, /activity.enabled/);
    assert.match(rows, /activity.paused/);
    assert.match(rows, /activity.unknown/);
    assert.match(rows, /background-time/);
    assert.match(rows, /12345/);
    assert.doesNotMatch(rows, /Deleted account|<Viewer>/);
    assert.equal(f.elements['activity-as-of'].textContent, 'now');
    assert.match(f.elements['activity-metrics'].innerHTML, /activity.messaging/);
});

test('empty activity reports have an eight-column empty state', () => {
    const f = fixture();
    f.context.renderAccountActivity([], {});
    assert.match(f.elements['activity-account-rows'].innerHTML, /colspan="8"/);
    assert.equal(f.elements['activity-as-of'].textContent, '-');
});

test('activity panel distinguishes its rolling window from filtered consumption', () => {
    assert.match(html, /id="activity-account-rows"/);
    assert.match(html, /不受成本日期筛选影响/);
    assert.match(source, /renderAccountActivity\(costReport\?\.accounts/);
    assert.match(source, /lastUsed: '最近模型消耗'/);
    assert.match(source, /activeUsers: '有模型消耗的账号'/);
    assert.doesNotMatch(source, /lastUsed: '最近使用'/);
    assert.match(source, /activityMetrics\) activityMetrics\.innerHTML = ''/);
});
