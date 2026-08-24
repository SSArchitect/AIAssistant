'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const appSource = fs.readFileSync(
    path.resolve(__dirname, '../web/static/js/app.js'),
    'utf8',
);

test('Super Chat renders its welcome text before asynchronous startup', () => {
    const startup = appSource.slice(appSource.lastIndexOf('applyI18n();'));

    assert.match(
        startup,
        /updateSendState\(\);\s*showWelcome\(\);\s*bootApp\(\);/,
    );
    assert.ok(
        startup.indexOf('showWelcome();') < startup.indexOf('bootApp();'),
        'the welcome text must render before startup begins waiting on API calls',
    );
});
