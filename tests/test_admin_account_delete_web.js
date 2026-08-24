'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const adminHtml = fs.readFileSync(
    path.resolve(__dirname, '../web/admin.html'),
    'utf8',
);
const adminSource = fs.readFileSync(
    path.resolve(__dirname, '../web/static/js/admin.js'),
    'utf8',
);

test('admin member table exposes a protected account deletion action', () => {
    assert.match(adminHtml, /data-i18n="members\.actions"/);
    assert.match(adminHtml, /id="member-action-result"/);
    assert.match(adminSource, /function renderAccountDeleteAction\(account\)/);
    assert.match(adminSource, /account\.id === '0'/);
    assert.match(adminSource, /data-delete-account=/);
});

test('account deletion requires confirmation and refreshes the admin report', () => {
    assert.match(adminSource, /window\.confirm\(t\('members\.deleteConfirm'/);
    assert.match(
        adminSource,
        /apiCall\('DELETE', `\/api\/admin\/accounts\/\$\{encodeURIComponent\(account\.id\)\}`\)/,
    );
    assert.match(adminSource, /localStorage\.removeItem\(`\$\{ACCOUNT_SESSION_STORAGE_KEY\}:\$\{account\.id\}`\)/);
    assert.match(adminSource, /await loadCosts\(\)/);
    assert.match(adminSource, /deleteAccountButton\.dataset\.deleteAccount/);
});
