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
    assert.match(adminHtml, /admin\.js\?v=19/);
    assert.match(adminSource, /fetchModels: '刷新模型'/);
    assert.match(adminSource, /const refreshedModels = normalizeFetchedModels\(result\.models, currentDefault\)/);
    assert.match(adminSource, /refreshedSettings\[`llm\.\$\{provider\}\.models`\] = JSON\.stringify\(refreshedModels\)/);
    assert.match(adminSource, /refreshedSettings\[`llm\.\$\{provider\}\.model`\] = refreshedModels\[0\]/);
    assert.match(adminSource, /await apiCall\('PUT', '\/api\/admin\/settings', \{ settings: refreshedSettings \}\)/);
    assert.match(adminSource, /providerModels\[provider\] = refreshedModels/);
    assert.match(adminSource, /renderModelList\(provider\)/);
});

test('Volcengine settings expose Plan URL without changing persisted provider keys', () => {
    const config = adminSource.match(/const PROVIDER_CONFIG = ([\s\S]*?\n\]);/)[1];
    const providers = vm.runInNewContext(config);
    const volcengine = providers.find((provider) => provider.key === 'doubao');
    assert.match(volcengine.label, /Volcengine/);
    assert.equal(volcengine.fields.find((field) => field.key === 'llm.doubao.api_key').type, 'password');
    assert.equal(volcengine.fields.find((field) => field.key === 'llm.doubao.base_url').placeholder,
        'https://ark.cn-beijing.volces.com/api/plan/v3');
    assert.match(adminSource, /Plan 刷新加载官方文本模型清单/);
});

test('catalog-only validation is shown as pending rather than failed', () => {
    const element = { style: {} };
    const context = {
        document: { getElementById: () => element },
        PROVIDER_BY_KEY: { doubao: { label: 'Volcengine' } },
        t: (key) => key,
    };
    const fn = adminSource.match(/function showValidationResult[\s\S]*?^}/m)[0];
    vm.runInNewContext(fn, context);
    context.showValidationResult('doubao', { success: false, status: 'pending', message: 'Catalog loaded' });
    assert.equal(element.textContent, 'Catalog loaded');
    assert.equal(element.className, 'test-result compact');
});

test('chat settings preserve the pending status of Plan validation', async () => {
    const appSource = fs.readFileSync(path.resolve(__dirname, '../web/static/js/app.js'), 'utf8');
    const classes = new Set();
    const element = { classList: { toggle: (name, value) => value ? classes.add(name) : classes.delete(name) } };
    const context = {
        document: { getElementById: () => element }, settings: {},
        t: (key) => key, renderSettings() {},
        apiCall: async () => ({ validation: { doubao: { success: false, status: 'pending', message: 'Catalog loaded' } } }),
    };
    vm.runInNewContext(appSource.match(/async function testProvider\([\s\S]*?^}/m)[0], context);
    await context.testProvider('doubao', { textContent: 'Test' });
    assert.equal(element.textContent, 'settings.pending');
    assert.equal(element.title, 'Catalog loaded');
    assert.equal(context.settings['llm.doubao.validation_status'], 'pending');
    assert.equal(classes.has('error'), false);
    assert.equal(classes.has('ok'), false);
});
