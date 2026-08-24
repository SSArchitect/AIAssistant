'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const appSource = fs.readFileSync(
    path.resolve(__dirname, '../web/static/js/app.js'),
    'utf8',
);
const cssSource = fs.readFileSync(
    path.resolve(__dirname, '../web/static/css/style.css'),
    'utf8',
);

test('chat renders structured tool approval events as a message card', () => {
    assert.match(appSource, /function approvalStatesFromEvents\(/);
    assert.match(appSource, /type !== 'approval\.required' && type !== 'approval\.resolving' && type !== 'approval\.resolved'/);
    assert.match(appSource, /data-tool-approval-card/);
    assert.match(cssSource, /\.tool-approval-card/);
});

test('approval card exposes one-time, conversation-scoped, and deny decisions', () => {
    for (const decision of ['allow_once', 'allow_conversation', 'deny']) {
        assert.match(appSource, new RegExp(`data-approval-decision=\\"${decision}\\"`));
    }
    assert.match(appSource, /\/api\/tool-approvals\/\$\{encodeURIComponent\(approvalId\)\}/);
    assert.match(appSource, /alwaysConfirmTitle/);
    assert.match(appSource, /此会话始终允许/);
    assert.match(appSource, /approval\.ready \|\| approval\.runFinished/);
    assert.match(appSource, /approvalsEl\.innerHTML = renderApprovalCards\(lastEvents, \{\s*interactive: true,/);
});

test('Pulse approval card hides internal topic ids from users', () => {
    assert.match(appSource, /function approvalVisibleArguments\(/);
    assert.match(appSource, /toolName === 'upsert_pulse_topic'/);
    assert.match(appSource, /toolName === 'delete_pulse_topic'/);
    assert.match(appSource, /delete args\.topic_id/);
    assert.match(appSource, /approvalVisibleArguments\(approval\.toolName, operation\.arguments\)/);
    assert.match(appSource, /toolName === 'delete_pulse_topic'[\s\S]*?'删除'/);
});
