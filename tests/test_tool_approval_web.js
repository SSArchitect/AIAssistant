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
    assert.match(appSource, /type !== 'approval\.required' && type !== 'approval\.resolved'/);
    assert.match(appSource, /data-tool-approval-card/);
    assert.match(cssSource, /\.tool-approval-card/);
});

test('approval card exposes one-time, persistent, and deny decisions', () => {
    for (const decision of ['allow_once', 'allow_always', 'deny']) {
        assert.match(appSource, new RegExp(`data-approval-decision=\\"${decision}\\"`));
    }
    assert.match(appSource, /\/api\/tool-approvals\/\$\{encodeURIComponent\(approvalId\)\}/);
    assert.match(appSource, /alwaysConfirmTitle/);
});
