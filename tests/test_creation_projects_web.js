'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const C = require('../web/static/js/creation-projects.js');

function document() {
    return { asset_ids: ['role'], messages: [], states: { script: { revision: 2, approved_revision: 2 }, visual: { revision: 1, approved_revision: 1, selected_asset_id: 'image' }, video: { revision: 1, approved_revision: 1 } }, plan: { questions: [], nodes: [
        { id: 'script', kind: 'text', title: '脚本', content: '短片', depends_on: [], references: [] },
        { id: 'visual', kind: 'image', title: '主视觉', depends_on: [], references: [{ asset_id: 'role', role: 'identity', note: '保持角色外观' }] },
        { id: 'video', kind: 'video', title: '成片', depends_on: ['script', 'visual'], references: [{ node_id: 'visual', role: 'style', note: '只参考场景风格' }] },
    ] } };
}
function project(doc = document()) { return { id: 'p', name: '项目', revision: 4, document: JSON.stringify(doc), planning: false }; }
function harness(api, user = () => 'alice') {
    const handlers = {};
    const root = { innerHTML: '', querySelector: () => null, addEventListener: (name, fn) => { handlers[name] = fn; } };
    const controller = C.createController({ api, user, mediaURL: id => `/assets/${id}` }); controller.mount(root);
    return { controller, root, handlers,
        click: (action, id = '', asset = '') => handlers.click({ target: { closest: () => ({ dataset: { cpAction: action, id, asset }, disabled: false }) } }),
        input: text => handlers.input({ target: { hasAttribute: key => key === 'data-cp-draft', value: text } }),
        send: () => handlers.submit({ target: { hasAttribute: () => true }, preventDefault() {} }),
    };
}
const tick = () => new Promise(resolve => setImmediate(resolve));

test('saved positions override automatic layout without changing dependencies or content', () => {
    const doc = document(), before = JSON.stringify(doc), assets = [{id:'role',name:'角色'}];
    const initial = C.layoutGraph(doc, assets);
    const layout = C.layoutGraph(doc, assets, {script:{x:1250.5,y:900},'asset:role':{x:15,y:30},video:{x:NaN,y:5}});
    assert.equal(layout.nodes.find(n=>n.id==='script').x,1250.5);
    assert.equal(layout.nodes.find(n=>n.id==='asset:role').y,30);
    assert.deepEqual(layout.edges,initial.edges); assert.equal(JSON.stringify(doc),before);
    assert.equal(layout.nodes.find(n=>n.id==='video').x,initial.nodes.find(n=>n.id==='video').x);
    assert.ok(layout.width>=1510.5 && layout.height>=1151);
    assert.deepEqual(C.movedPosition({x:100,y:100},50,25,.5),{x:200,y:150});
    assert.deepEqual(C.movedPosition({x:100,y:100},-1000,30000,1),{x:0,y:20000});
});

function pointerHarness(api) {
    const h = harness(api), classes = {add(){},remove(){}};
    const view = {scrollLeft:0,scrollTop:0,classList:classes,setPointerCapture(){},releasePointerCapture(){}};
    const card = {dataset:{id:'script',cpAction:'select'},classList:classes,setPointerCapture(){},releasePointerCapture(){}};
    const target = {closest:selector=>selector==='[data-cp-viewport]'?view:card};
    return {...h,view,card, pointer(type,x,y,extra={}) {h.handlers[type]({target,clientX:x,clientY:y,pointerId:1,button:0,preventDefault(){},...extra});}};
}

test('dragging respects zoom, saves only on release, suppresses accidental selection, and cancels safely', async () => {
    const p=project(),calls=[];
    const h=pointerHarness(async(method,path,body)=>{calls.push({method,path,body});return method==='PATCH'?{canvas_layout:JSON.stringify(body.positions),layout_revision:1}:{project:p,projects:[p],assets:[],runs:[]};});
    await h.controller.newProject(); h.click('select','video'); await tick(); h.click('zoom-out'); await tick();
    const start=C.layoutGraph(document()).nodes.find(n=>n.id==='script');
    h.pointer('pointerdown',20,20); h.pointer('pointermove',105,62.5);
    const before=h.root.innerHTML; await h.controller.refresh(); assert.equal(h.root.innerHTML,before,'polls must not rebuild a captured node');
    assert.equal(calls.filter(c=>c.method==='PATCH').length,0);
    h.pointer('pointerup',105,62.5); h.click('select','script'); await tick();
    const saves=calls.filter(c=>c.method==='PATCH'); assert.equal(saves.length,1);
    assert.deepEqual(saves[0].body.positions.script,{x:start.x+100,y:start.y+50});
    assert.match(h.root.innerHTML,/针对：成片/); // Drag release must not select the moved script.
    h.pointer('pointerdown',0,0,{pointerType:'touch'}); h.pointer('pointermove',100,100,{pointerType:'touch'}); h.pointer('pointercancel',100,100);
    await tick(); assert.equal(calls.filter(c=>c.method==='PATCH').length,1);
    h.controller.reset();
});

test('click-sized pointer movement does not save; right click and other pointers do not drag', async () => {
    const calls=[],h=pointerHarness(async(method,path,body)=>{calls.push({method,path,body});return {project:project()};});
    await h.controller.newProject(); h.pointer('pointerdown',10,10); h.pointer('pointermove',12,11); h.pointer('pointerup',12,11);
    h.pointer('pointerdown',0,0,{button:2}); h.pointer('pointermove',100,100); h.pointer('pointerup',100,100);
    h.pointer('pointerdown',0,0); h.pointer('pointermove',100,100,{pointerId:2}); h.pointer('pointerup',0,0);
    await tick(); assert.equal(calls.filter(c=>c.method==='PATCH').length,0); h.controller.reset();
});

test('layout failures can be retried and late saves cannot restore an old account', async () => {
    let fail=true,finish; const calls=[],p=project();
    const h=pointerHarness(async(method,path,body)=>{
        calls.push({method,path,body});
        if(method==='PATCH') {if(fail)throw new Error('offline');return new Promise(resolve=>{finish=resolve;});}
        return {project:p};
    });
    await h.controller.newProject(); h.pointer('pointerdown',0,0); h.pointer('pointermove',50,50); h.pointer('pointerup',50,50); await tick();
    fail=false; h.click('retry-layout'); await tick();
    assert.equal(calls.filter(c=>c.method==='PATCH').length,2);
    assert.deepEqual(calls.at(-1).body.positions,calls.filter(c=>c.method==='PATCH')[0].body.positions);
    h.controller.reset(); finish({canvas_layout:'{"script":{"x":999,"y":999}}',layout_revision:5}); await tick();
    assert.equal(h.root.innerHTML,'');
});

test('refinement choices are contextual, plentiful, and prefer supplied node-specific directions', () => {
    const brief=C.revisionSuggestions({purpose:'brief'}),script=C.revisionSuggestions({purpose:'script'});
    assert.equal(brief.length,10); assert.equal(script.length,10);
    assert.ok(brief.some(s=>s.label==='突出故事核心')); assert.ok(script.some(s=>s.label==='运镜更流畅'));
    const supplied={label:'给白露一个回头',instruction:'在白露离开前增加一次回头，保留其余动作。'};
    assert.deepEqual(C.revisionSuggestions({purpose:'script',revision_suggestions:[supplied]})[0],supplied);
    assert.throws(()=>C.refinementMessage({title:'脚本'},[], ' '),/选择/);
});

test('multiple directions and free text submit one targeted planning request and preserve failed drafts', async () => {
    const doc=document();doc.plan.nodes[0].purpose='script'; const p=project(doc),calls=[]; let fail=true;
    const h=harness(async(method,path,body)=>{calls.push({method,path,body});if(path.endsWith('/messages')){if(fail)throw new Error('offline');return {project:{...p,planning:true}};}return {project:structuredClone(p),projects:[structuredClone(p)],assets:[],runs:[]};});
    await h.controller.newProject();
    h.click('refine-choice','0'); await tick(); h.click('refine-choice','1'); await tick();
    h.handlers.input({target:{hasAttribute:key=>key==='data-cp-refine',value:'保留结尾，不改台词。'}});
    p.revision++;
    await h.controller.refresh();
    assert.match(h.root.innerHTML,/保留结尾，不改台词。/);
    h.click('refine-submit','script'); await tick(); await tick();
    assert.match(h.root.innerHTML,/保留结尾，不改台词。/); assert.match(h.root.innerHTML,/已选 2 项/);
    fail=false; h.click('refine-submit','script'); await tick(); await tick();
    const sends=calls.filter(c=>c.path.endsWith('/messages'));assert.equal(sends.length,2);
    assert.equal(sends[0].body.request_id,sends[1].body.request_id);
    assert.equal(sends[1].body.node_id,'script'); assert.match(sends[1].body.message,/时间分配/);assert.match(sends[1].body.message,/摄影机方向/);assert.match(sends[1].body.message,/保留结尾，不改台词。/);
    assert.equal(calls.filter(c=>c.path.endsWith('/generate')||c.path.endsWith('/review')).length,0);
    h.controller.reset();
});

test('refinement text is isolated per node, supports free text alone, and escapes model suggestions', async () => {
    const doc=document(); doc.plan.nodes[0].revision_suggestions=[{label:'<img src=x>',instruction:'<script>bad()</script>'}];
    const calls=[],h=harness(async(method,path,body)=>{calls.push({method,path,body});return {project:project(doc)};});
    await h.controller.newProject(); assert.match(h.root.innerHTML,/&lt;img src=x&gt;/);assert.doesNotMatch(h.root.innerHTML,/<script>/);
    h.handlers.input({target:{hasAttribute:key=>key==='data-cp-refine',value:'只改脚本结尾'}});
    h.click('select','video'); await tick(); assert.doesNotMatch(h.root.innerHTML,/只改脚本结尾/);
    h.click('select','script');await tick();assert.match(h.root.innerHTML,/只改脚本结尾/);
    h.click('refine-submit','script');await tick();await tick();
    assert.match(calls.find(c=>c.path.endsWith('/messages')).body.message,/只改脚本结尾/);h.controller.reset();
});

test('video submission requires current approvals and is blocked by unanswered questions or active jobs', () => {
    const doc = document(), p = project(doc), node = doc.plan.nodes[2];
    assert.equal(C.generationBlock(p, node), '');
    doc.states.script.approved_revision = 1;
    assert.match(C.generationBlock(project(doc), node), /上游/);
    doc.states.script.approved_revision = 2; doc.states.video.approved_revision = 0;
    assert.match(C.generationBlock(project(doc), node), /参考/);
    doc.states.video.approved_revision = 1; doc.plan.questions = [{ question: '方向？', options: ['一', '二'] }];
    assert.match(C.generationBlock(project(doc), node), /方向/);
    doc.plan.questions = [];
    assert.match(C.generationBlock(project(doc), node, [{ status: 'running' }]), /等待/);
    assert.match(C.generationBlock({ ...project(doc), planning: true }, node), /正在/);
});
test('canvas positions follow dependencies and retain semantic source edges without overlap', () => {
    const layout = C.layoutGraph(document(), [{ id: 'role', name: '角色图' }]);
    assert.equal(layout.nodes.length, 4);
    const at = id => layout.nodes.find(n => n.id === id);
    assert.ok(at('video').x > at('script').x && at('video').x > at('visual').x);
    assert.ok(layout.edges.some(e => e.from === 'asset:role' && e.to === 'visual' && e.label === '人物身份'));
    assert.ok(layout.edges.some(e => e.from === 'visual' && e.to === 'video' && e.label === '画面风格'));
    for (let i = 0; i < layout.nodes.length; i++) for (let j = i + 1; j < layout.nodes.length; j++) {
        const a = layout.nodes[i], b = layout.nodes[j]; assert.ok(a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y);
    }
});
test('reference labels escape asset names and content; old run status remains distinct from approval', () => {
    const doc = document(), html = C.renderReferences(doc, doc.plan.nodes[1], [{ id: 'role', name: '<img src=x>' }]);
    assert.match(html, /&lt;img/); assert.doesNotMatch(html, /<img/); assert.match(html, /人物身份/);
    doc.states.video = { revision: 3, approved_revision: 0, run_id: 'old' };
    assert.equal(C.nodeStatus(doc, doc.plan.nodes[2], [{ id: 'old', status: 'completed' }]), '已完成');
    assert.equal(C.approved(doc.states.video), false);
});
test('project dialogue persists chosen assets, node context and a retry-safe request id', async () => {
    const calls = []; let failed = true;
    const api = async (method, path, body) => {
        calls.push({ method, path, body });
        if (method === 'POST' && path === '/api/creation/projects') return { project: project({ plan: { nodes: [], questions: [] }, states: {}, messages: [], asset_ids: [] }) };
        if (path.endsWith('/messages')) { if (failed) { failed = false; throw new Error('network'); } return { project: { ...project(), planning: true, revision: 5 } }; }
        return { projects: [], assets: [], runs: [] };
    };
    const h = harness(api);
    h.input('做一支短片'); h.click('attach', 'role'); await tick();
    h.send(); await tick(); await tick();
    assert.match(h.root.innerHTML, /做一支短片/); // Failed first send must not erase the idea.
    h.send(); await tick(); await tick();
    const sends = calls.filter(c => c.path.endsWith('/messages'));
    assert.equal(sends.length, 2); assert.equal(sends[0].body.request_id, sends[1].body.request_id);
    assert.deepEqual(sends[0].body.asset_ids, ['role']); assert.equal(sends[0].body.message, '做一支短片');
    assert.match(h.root.innerHTML, /正在整理方案/);
    h.controller.reset();
});
test('old account responses cannot restore dialogue or project data after reset', async () => {
    let owner = 'alice'; const pending = [];
    const api = (_method, path) => owner === 'alice' ? new Promise(resolve => pending.push([path, resolve])) : Promise.resolve({ projects: [{ id: 'bob', name: 'Bob project' }], assets: [], runs: [] });
    const h = harness(api, () => owner);
    const old = h.controller.refresh(); h.controller.reset(); owner = 'bob'; await h.controller.refresh();
    for (const [, resolve] of pending) resolve({ projects: [{ id: 'alice', name: 'Alice private' }], assets: [], runs: [] });
    await old;
    assert.match(h.root.innerHTML, /Bob project/); assert.doesNotMatch(h.root.innerHTML, /Alice private/);
    h.controller.reset();
});
test('reopening the project keeps generation disabled until backend approval and escapes chat text', async () => {
    const doc = document(); doc.messages = [{ role: 'assistant', content: '<script>bad()</script>' }]; doc.states.video.approved_revision = 0;
    const p = project(doc);
    const h = harness(async () => ({ project: p }));
    await h.controller.newProject();
    h.click('select', 'video'); await tick();
    assert.match(h.root.innerHTML, /data-cp-action="generate"[^>]*disabled/);
    assert.match(h.root.innerHTML, /&lt;script&gt;/); assert.doesNotMatch(h.root.innerHTML, /<script>/);
    h.controller.reset();
});
test('project module loads before navigation and legacy controller cannot override review gates', () => {
    const html = fs.readFileSync('web/index.html', 'utf8'), parent = fs.readFileSync('web/static/js/creation.js', 'utf8');
    assert.ok(html.indexOf('/static/js/creation-projects.js') < html.indexOf('/static/js/creation.js'));
    assert.match(parent, /tab = 'projects'/);
    assert.match(parent, /!b.closest\('\.creation-project-host'\)/);
    assert.match(parent, /projectController\?\.reset\(\)/);
});

test('planning process opens during work, folds on completion, and escapes its content', () => {
    const activity = { id: 'req', status: 'running', started_at: '2026-09-17T12:00:00Z', steps: [{ message: '<script>unsafe</script>', elapsed_ms: 0 }], output_chars: 42 };
    let html = C.renderPlanning(activity, undefined, Date.parse('2026-09-17T12:01:05Z'));
    assert.match(html, /data-cp-planning="req:running" open/);
    assert.match(html, /1分5秒/); assert.match(html, /42 字符/); assert.match(html, /&lt;script&gt;/); assert.doesNotMatch(html, /<script>/);
    html = C.renderPlanning({ ...activity, status: 'completed', elapsed_ms: 65000 });
    assert.doesNotMatch(html, / open/); assert.match(html, /规划已完成/);
    assert.match(C.renderPlanning({ ...activity, status: 'completed' }, true), / open/);
    assert.doesNotMatch(C.renderPlanning(activity, false), / open/);
    assert.match(C.renderPlanning({ ...activity, status: 'failed' }), /本次规划未完成/);
});
test('send shows immediate feedback while request is pending, prevents duplicates, then offers retry on planning failure', async () => {
    let finish; const calls = []; const doc = document(); doc.messages = [];
    const p = project(doc);
    const h = harness(async (method, path, body) => {
        calls.push({ method, path, body });
        if (path.endsWith('/messages')) return await new Promise(resolve => { finish = resolve; });
        return { project: p };
    });
    await h.controller.newProject(); h.input('我打算画e04的视频'); h.send();
    assert.match(h.root.innerHTML, /正在提交创作想法/); assert.match(h.root.innerHTML, /你 · 发送中/);
    h.send(); await tick(); assert.equal(calls.filter(c => c.path.endsWith('/messages')).length, 1);
    const failed = { ...p, error: '方案格式校验失败', document: JSON.stringify({ ...doc, messages: [{ role: 'user', content: '我打算画e04的视频' }] }) };
    finish({ project: failed }); await tick();
    assert.match(h.root.innerHTML, /role="alert"/); assert.match(h.root.innerHTML, /重试这次规划/);
    h.click('retry-plan'); await tick();
    assert.equal(calls.at(-1).body.message, '我打算画e04的视频');
    finish({ project: { ...p, planning: true } }); await tick(); h.controller.reset();
});
test('planning activity stays open across polls but automatically folds when the reply arrives', async () => {
    const doc = document(); doc.planning = { id: 'task', status: 'running', started_at: new Date().toISOString(), steps: [{ message: '正在校验' }] };
    let p = { ...project(doc), planning: true };
    const h = harness(async () => ({ project: p, projects: [p], assets: [], runs: [] }));
    await h.controller.newProject(); assert.match(h.root.innerHTML, /task:running" open/);
    await h.controller.refresh(); assert.match(h.root.innerHTML, /task:running" open/);
    doc.messages = [{ role: 'assistant', content: '请审阅', planning: { ...doc.planning, status: 'completed' } }]; delete doc.planning;
    p = { ...project(doc), revision: 6 };
    await h.controller.refresh(); assert.match(h.root.innerHTML, /task:completed/); assert.doesNotMatch(h.root.innerHTML, /task:completed" open/);
    h.controller.reset();
});

function scrollingHarness() {
    const doc = document(); doc.planning = { id: 'scroll-job', status: 'running', started_at: new Date().toISOString(), steps: [{ message: '正在分析素材', elapsed_ms: 0 }] };
    let row = { ...project(doc), planning: true }, writes = 0, html = '';
    const messages = { scrollTop: 0, scrollHeight: 1200, clientHeight: 400 };
    const outer = { scrollTop: 250, scrollLeft: 0, parentElement: null };
    const time = { textContent: '' }, steps = { innerHTML: '' }, live = { innerHTML: '' };
    const details = { open: false, dataset: { cpPlanning: 'scroll-job:running' } };
    const active = { querySelector: selector => ({ details, time, '[data-cp-plan-steps]': steps, '[data-cp-plan-live]': live }[selector] || null) };
    const version = { textContent: '' };
    const handlers = {};
    const root = { parentElement: outer,
        querySelector: selector => ({ '.cp-messages': messages, '[data-cp-active-planning]': active, '.cp-version': version }[selector] || null),
        querySelectorAll: selector => selector === '[data-cp-planning]' ? [details] : [], addEventListener: (name, fn) => { handlers[name] = fn; },
        get innerHTML() { return html; }, set innerHTML(value) { html = value; writes++; messages.scrollTop = 0; outer.scrollTop = 999; },
    };
    const api = async () => ({ project: structuredClone(row), projects: [structuredClone(row)], assets: [], runs: [] });
    const controller = C.createController({ api, user: () => 'alice', mediaURL: id => id }); controller.mount(root);
    return { controller, root, messages, outer, details, get writes() { return writes; },
        advance() { doc.planning.steps.push({ message: '读取脚本后继续规划', elapsed_ms: 5000 }); row = { ...row, revision: row.revision + 1, document: JSON.stringify(doc) }; },
        complete() { doc.messages.push({ role: 'assistant', content: '方案已完成', planning: { ...doc.planning, status: 'completed' } }); delete doc.planning; row = { ...row, planning: false, revision: row.revision + 1, document: JSON.stringify(doc) }; },
    };
}

test('thinking progress updates preserve the page and stop following even slightly above the bottom', async () => {
    const h = scrollingHarness(); await h.controller.newProject(); await h.controller.refresh();
    h.messages.scrollTop = 790; h.outer.scrollTop = 250; const writes = h.writes;
    h.advance(); await h.controller.refresh();
    assert.equal(h.writes, writes, 'a progress tick must not rebuild the conversation or canvas');
    assert.equal(h.messages.scrollTop, 790, 'reading ten pixels above the bottom must not snap down');
    assert.equal(h.outer.scrollTop, 250); assert.equal(h.details.open, false, 'manually collapsed progress stays collapsed');
    h.controller.reset();
});
test('finishing a plan preserves the reader position through the full render', async () => {
    const h = scrollingHarness(); await h.controller.newProject();
    h.messages.scrollTop = 310; h.outer.scrollTop = 160;
    h.complete(); await h.controller.refresh();
    assert.equal(h.messages.scrollTop, 310); assert.equal(h.outer.scrollTop, 160);
    h.controller.reset();
});
test('a reader at the very bottom can follow new content without a scroll animation', () => {
    const state = C.captureReadingPosition({ querySelector: selector => selector === '.cp-messages' ? ({ scrollTop: 799.5, scrollHeight: 1200, clientHeight: 400 }) : null, parentElement: null });
    const messages = { scrollTop: 799.5, scrollHeight: 1300, clientHeight: 400 };
    C.restoreReadingPosition({ querySelector: selector => selector === '.cp-messages' ? messages : null }, state);
    assert.equal(messages.scrollTop, 900);
    const css = fs.readFileSync('web/static/css/creation.css', 'utf8');
    assert.doesNotMatch(css.match(/\.cp-messages\s*\{[^}]+\}/)[0], /scroll-behavior:\s*smooth/);
});

test('restoring composer focus never scrolls its surrounding page', async t => {
    const h = scrollingHarness(); await h.controller.newProject();
    const oldDocument = globalThis.document; t.after(() => { if (oldDocument === undefined) delete globalThis.document; else globalThis.document = oldDocument; h.controller.reset(); });
    const focused = { hasAttribute: key => key === 'data-cp-draft', selectionStart: 1, selectionEnd: 2 };
    globalThis.document = { activeElement: focused }; h.root.contains = value => value === focused;
    let options;
    const query = h.root.querySelector;
    h.root.querySelector = selector => selector === '[data-cp-draft]' ? { focus: value => { options = value; }, setSelectionRange: () => {} } : query(selector);
    h.outer.scrollTop = 180; h.complete(); await h.controller.refresh();
    assert.deepEqual(options, { preventScroll: true }); assert.equal(h.outer.scrollTop, 180);
});

test('media progress shows real elapsed time without invented percentages or completion estimates', () => {
    const run = { id: 'media', status: 'running', created_at: '2026-09-17T12:00:00Z' };
    const now = Date.parse('2026-09-17T12:12:30Z');
    const html = C.renderMediaProgress(run, now);
    assert.match(html, /已等待 12分30秒/);
    assert.match(html, /可以离开此页/);
    assert.doesNotMatch(html, /%|预计|剩余/);
    assert.equal(C.renderMediaProgress({ ...run, status: 'failed' }, now), '');
    assert.equal(C.renderMediaProgress({ ...run, status: 'completed' }, now), '');
    assert.doesNotMatch(C.renderMediaProgress({ ...run, created_at: 'bad' }, now), /NaN|已等待/);
    assert.match(C.renderMediaProgress({ ...run, created_at: '2026-09-17T12:13:00Z' }, now), /已等待 0秒/);
});

test('media elapsed clock advances on an unchanged poll without rebuilding the canvas', async t => {
    let now = Date.parse('2026-09-17T12:01:00Z');
    const realNow = Date.now; Date.now = () => now; t.after(() => { Date.now = realNow; });
    const doc = document(); doc.states.video.run_id = 'media';
    const p = project(doc), run = { id: 'media', status: 'running', created_at: '2026-09-17T12:00:00Z' };
    const h = harness(async () => ({ project: p, projects: [p], assets: [], runs: [run] }));
    t.after(() => h.controller.reset());
    await h.controller.newProject(); await h.controller.refresh(); h.click('select', 'video'); await tick();
    assert.match(h.root.innerHTML, /已等待 1分0秒/);
    const time = { textContent: '已等待 1分0秒' };
    h.root.querySelectorAll = selector => selector === '[data-cp-media-run]' ? [{ dataset: { cpMediaRun: 'media' }, querySelector: () => time }] : [];
    const before = h.root.innerHTML;
    now += 60000; await h.controller.refresh();
    assert.equal(time.textContent, '已等待 2分0秒');
    assert.equal(h.root.innerHTML, before);
});

test('each node revision owns its request, thinking, result and collapse state', async () => {
    const doc=document();
    const done={id:'one',status:'completed',steps:[]};
    doc.messages=[{role:'user',node_id:'script',content:'优化对白'}, {role:'assistant',content:'对白已优化',planning:done}, {role:'user',node_id:'video',content:'优化运镜'}];
    doc.planning={id:'two',status:'running',steps:[]};
    let p={...project(doc),planning:true};
    const groups=C.conversationRounds(doc);
    assert.equal(groups.length,2);assert.equal(groups[0].nodeID,'script');assert.equal(groups[1].nodeID,'video');
    assert.equal(groups[0].messages.length,2);assert.equal(groups[1].active.id,'two');
    const h=harness(async()=>({project:structuredClone(p),projects:[p],assets:[],runs:[]}));
    await h.controller.newProject();
    assert.match(h.root.innerHTML,/data-cp-turn="p:turn-0" >/);
    assert.match(h.root.innerHTML,/data-cp-turn="p:turn-2" open/);
    assert.match(h.root.innerHTML,/第 2 轮 · 正在规划/);
    // A real summary click records user intent, independently of planning details.
    const round={dataset:{cpTurn:'p:turn-2'},open:true,hasAttribute:()=>true};
    h.handlers.click({target:{closest:s=>s==='summary'?{parentElement:round}:null}});
    h.click('select','script');await tick();
    assert.match(h.root.innerHTML,/data-cp-turn="p:turn-2" >/);
    doc.messages.push({role:'assistant',content:'运镜已优化',planning:{...doc.planning,status:'completed'}});delete doc.planning;
    p={...project(doc),revision:5};await h.controller.refresh();
    assert.match(h.root.innerHTML,/第 2 轮 · 已完成/);assert.match(h.root.innerHTML,/data-cp-turn="p:turn-2" >/);
    h.controller.reset();
});

test('a failed revision renders one error and retries its own node with original content', async () => {
    const doc=document(),error='创作规划等待超时，原有内容已保留，请重试',calls=[];
    doc.messages=[{role:'user',node_id:'script',content:'改善分镜'}, {role:'assistant',content:error,planning:{id:'bad',status:'failed',steps:[{stage:'failed',message:error}]}}];
    const p={...project(doc),error};
    const h=harness(async(method,path,body)=>{calls.push({path,body});return {project:p};});
    await h.controller.newProject();
    assert.equal(h.root.innerHTML.split(error).length-1,1);
    assert.match(h.root.innerHTML,/第 1 轮 · 未完成/);
    h.click('select','video');await tick();h.click('retry-plan');await tick();
    assert.equal(calls.at(-1).body.node_id,'script');assert.equal(calls.at(-1).body.message,'改善分镜');
    h.controller.reset();
});

test('right review scrolling is independent and survives polling renders', () => {
    const messages={scrollTop:100,scrollHeight:1200,clientHeight:400},main={scrollTop:950};
    const root={querySelector:s=>s==='.cp-messages'?messages:s==='.cp-main'?main:null,parentElement:null};
    const saved=C.captureReadingPosition(root); messages.scrollTop=0;main.scrollTop=0;
    C.restoreReadingPosition(root,saved);
    assert.equal(messages.scrollTop,100);assert.equal(main.scrollTop,950);
    const css=fs.readFileSync('web/static/css/creation.css','utf8');
    assert.match(css,/\.is-projects \.cp-main\s*\{[^}]*overflow-y: auto/);
    assert.match(css,/\.is-projects \.cp-messages\s*\{[^}]*flex: 1;[^}]*min-height: 0/);
    assert.match(css,/#view-creation:has\(\.is-projects\)\s*\{[^}]*overflow: hidden/);
});

test('the current round keeps its node label visible while reading a long process', () => {
    const css=fs.readFileSync('web/static/css/creation.css','utf8');
    assert.match(css,/\.cp-round > summary\s*\{[^}]*position: sticky;[^}]*top: 0/);
    assert.match(css,/\.is-projects \.cp-compose textarea\s*\{[^}]*height: 76px/);
});

test('a recovered project poll clears transient connection errors', async () => {
    let fail=false;
    const p=project(),h=harness(async()=>{if(fail)throw new Error('Failed to fetch');return {project:p,projects:[p],assets:[],runs:[]};});
    await h.controller.newProject();fail=true;h.controller.setVisible(true);await tick();h.controller.setVisible(false);
    h.click('select','script');await tick();assert.match(h.root.innerHTML,/Failed to fetch/);
    fail=false;await h.controller.refresh();h.click('select','video');await tick();
    assert.doesNotMatch(h.root.innerHTML,/Failed to fetch/);h.controller.reset();
});
