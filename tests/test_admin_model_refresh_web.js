'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const adminHtml = fs.readFileSync(
    path.resolve(__dirname, '../web/admin.html'),
    'utf8',
);
const adminSource = fs.readFileSync(
    path.resolve(__dirname, '../web/static/js/admin.js'),
    'utf8',
);

function loadNormalizeFetchedModels() {
    const match = adminSource.match(/function normalizeFetchedModels[\s\S]*?^}/m);
    assert.ok(match, 'normalizeFetchedModels should exist');
    const context = {};
    vm.runInNewContext(`${match[0]}; globalThis.normalizeFetchedModels = normalizeFetchedModels;`, context);
    return context.normalizeFetchedModels;
}

test('provider model refresh normalizes the remote list and preserves a valid default', () => {
    const normalizeFetchedModels = loadNormalizeFetchedModels();

    assert.deepEqual(
        Array.from(normalizeFetchedModels([
            { id: 'model-b' },
            { id: ' model-a ' },
            { id: 'model-b' },
            { name: 'missing-id' },
        ], 'model-a')),
        ['model-a', 'model-b'],
    );
    assert.deepEqual(
        Array.from(normalizeFetchedModels([{ id: 'new-model' }], 'retired-model')),
        ['new-model'],
    );
});

test('refresh models replaces and persists the provider model snapshot', () => {
    assert.match(adminHtml, /admin\.css\?v=13/);
    assert.match(adminHtml, /admin\.js\?v=18/);
    assert.match(adminSource, /fetchModels: '刷新模型'/);
    assert.match(adminSource, /const refreshedModels = normalizeFetchedModels\(result\.models, currentDefault\)/);
    assert.match(adminSource, /refreshedSettings\[`llm\.\$\{provider\}\.models`\] = JSON\.stringify\(refreshedModels\)/);
    assert.match(adminSource, /refreshedSettings\[`llm\.\$\{provider\}\.model`\] = refreshedModels\[0\]/);
    assert.match(adminSource, /await apiCall\('PUT', '\/api\/admin\/settings', \{ settings: refreshedSettings \}\)/);
    assert.match(adminSource, /providerModels\[provider\] = refreshedModels/);
    assert.match(adminSource, /renderModelList\(provider\)/);
});
