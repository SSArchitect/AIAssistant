'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const C = require('../web/static/js/creation.js');

test('workflow templates clone nodes and remap dependencies without sharing mutations', () => {
    const t = C.builtin.find(t => t.id === 'builtin-story');
    const first = C.instantiate(t), second = C.instantiate(t);
    assert.notEqual(first.nodes[0].id, second.nodes[0].id);
    assert.deepEqual(first.nodes[1].inputs, [first.nodes[0].id]);
    first.nodes[0].prompt = 'changed';
    assert.notEqual(C.graphOf(t).nodes[0].prompt, 'changed');
    assert.equal(C.validateGraph(second), '');
});
test('node effects retain input bindings and reject incompatible kinds', () => {
    const n = { ...C.newNode(), inputs: ['previous'], asset_ids: ['asset'] };
    const result = C.applyNodeTemplate(n, C.builtin.find(t => t.id === 'builtin-anime'));
    assert.equal(result.id, n.id); assert.equal(result.character_style, 'anime');
    assert.deepEqual(result.inputs, ['previous']); assert.deepEqual(result.asset_ids, ['asset']);
    assert.throws(() => C.applyNodeTemplate(n, C.builtin.find(t => t.id === 'builtin-cinema')));
});
test('graph validation covers image to image, many images to video, forward links and input limits', () => {
    const graph = C.instantiate(C.builtin[0]);
    assert.equal(C.validateGraph(graph), '');
    graph.nodes[1].kind = 'image'; assert.match(C.validateGraph(graph), /输入图片过多/);
    graph.nodes[0].count = 1; assert.equal(C.validateGraph(graph), '');
    graph.nodes[0].inputs = [graph.nodes[1].id]; assert.match(C.validateGraph(graph), /前面/);
    graph.nodes[0].inputs = []; graph.nodes[0].prompt = ' '; assert.match(C.validateGraph(graph), /提示词/);
    assert.match(C.validateGraph({ nodes: [] }), /至少/);
});
test('removing an upstream node clears dangling edges and reusing templates removes personal assets', () => {
    const graph = C.instantiate(C.builtin[0]);
    const result = C.removeNode(graph, graph.nodes[0].id);
    assert.equal(result.nodes.length, 1); assert.deepEqual(result.nodes[0].inputs, []);
    graph.nodes[0].asset_ids = ['private'];
    assert.deepEqual(C.instantiate({ graph }).nodes[0].asset_ids, []);
});
test('editor and media rendering escape user supplied strings and render video controls', () => {
    const n = C.newNode(); n.name = '<script>bad</script>'; n.prompt = '</textarea><script>x</script>';
    const html = C.renderNode(n, 0, { nodes: [n] }, [], C.builtin);
    assert.ok(!html.includes('<script>')); assert.ok(html.includes('&lt;script&gt;'));
    const media = C.renderAsset({ id: 'id', mime_type: 'video/mp4', name: '<img>', size: 1024, source: 'generated' }, id => `/api/creation/assets/${id}/content`);
    assert.match(media, /<video controls playsinline/); assert.match(media, /&lt;img&gt;/); assert.ok(!media.includes('autoplay'));
});
test('creation navigation and controller load with authenticated API and account reset', () => {
    const html = fs.readFileSync('web/index.html', 'utf8'), app = fs.readFileSync('web/static/js/app.js', 'utf8');
    assert.match(html, /data-view="creation"/); assert.match(html, /data-view-panel="creation"/);
    assert.ok(html.indexOf('/static/js/creation.js') < html.indexOf('/static/js/app.js'));
    assert.match(app, /creationController\?\.reset\(\)/);
    assert.match(app, /else creationController\?\.setVisible\(false\)/);
    assert.match(app, /connect\\\/v1\|creation/);
});

test('late account responses cannot restore another account’s workflows after reset', async t => {
    let owner = 'alice', waiting = [];
    const runs = { innerHTML: '' };
    const body = { innerHTML: '', querySelector: () => null };
    const listeners = {};
    const element = { innerHTML: '', querySelector: selector => selector === '.creation-body' ? body : selector === '.creation-runs' ? runs : null, querySelectorAll: () => [], addEventListener(name, fn) { listeners[name] = fn; } };
    const api = (_method, url) => {
        if (owner === 'alice') return new Promise(resolve => waiting.push([url, resolve]));
        return Promise.resolve(url.endsWith('definitions') ? { definitions: [{ id: 'bob', kind: 'workflow', name: 'Bob workflow', graph: { nodes: [] } }] } : url.endsWith('assets') ? { assets: [] } : { runs: [] });
    };
    const controller = C.createController({ element, api, user: () => owner, mediaURL: () => '', openDrive() {} });
    t.after(() => controller.reset());
    const oldLoad = controller.setVisible(true);
    controller.reset(); owner = 'bob'; await controller.setVisible(true);
    listeners.click({ target: { closest: () => ({ dataset: { tab: 'workflows' } }) } });
    for (const [url, resolve] of waiting) resolve(url.endsWith('definitions') ? { definitions: [{ id: 'alice', kind: 'workflow', name: 'Alice secret', graph: { nodes: [] } }] } : {});
    await oldLoad;
    assert.match(body.innerHTML, /Bob workflow/); assert.doesNotMatch(body.innerHTML, /Alice secret/);
    await controller.setVisible(false);
});

test('a recovered refresh clears its connection error without hiding later failures', async t => {
    let offline = true;
    const status = { textContent: '' }, body = { innerHTML: '', querySelector: () => null };
    const element = { innerHTML: '', querySelector: s => s === '.creation-feedback' ? status : s === '.creation-body' ? body : null, querySelectorAll: () => [], addEventListener() {} };
    const controller = C.createController({ element, user: () => 'alice', mediaURL: () => '', openDrive() {}, api: async () => {
        if (offline) throw new Error('Failed to fetch');
        return {};
    } });
    t.after(() => controller.reset());
    await controller.setVisible(true);
    assert.equal(status.textContent, 'Failed to fetch');
    offline = false;
    await controller.setVisible(true);
    assert.equal(status.textContent, '');
    offline = true;
    await controller.setVisible(true);
    assert.equal(status.textContent, 'Failed to fetch');
});
