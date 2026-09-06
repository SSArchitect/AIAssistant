const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { actions, renderConnections, renderCatalog, renderRoleSelect, createController } = require('../web/static/js/connect.js');

test('connected and disconnected integrations have distinct lifecycle actions', () => {
    assert.deepEqual(actions({ desired_state: 'enabled', status: 'connected' }), ['check', 'details', 'role', 'note', 'disconnect', 'delete']);
    assert.deepEqual(actions({ desired_state: 'disconnected' }), ['check', 'details', 'role', 'note', 'reconnect', 'delete']);
});
test('catalog renders only server-supported connectors and safe text', () => {
    const result = renderCatalog([{ id: 'feishu', name: '<script>bad</script>' }]);
    assert.match(result, /data-connect-add="feishu"/);
    assert.doesNotMatch(result, /telegram|slack|<script>/);
    assert.match(result, /&lt;script&gt;/);
});
test('QR images reject external URLs and connection text is escaped', () => {
    const result = renderConnections([{ id: '1', kind: 'weixin', name: '<img onerror=bad>', desired_state: 'enabled', status: 'awaiting_auth', next_action: JSON.stringify({ kind: 'qr', value: 'https://attacker.example/track' }) }]);
    assert.doesNotMatch(result, /<img|attacker.example/);
    assert.match(result, /&lt;img/);
});
test('account switch discards stale async connection responses', async () => {
    let owner = 'alice'; const resolvers = [];
    const nodes = new Map();
    const element = { innerHTML: '', addEventListener() {}, querySelector(selector) { if (!nodes.has(selector)) nodes.set(selector, { innerHTML: '', textContent: '' }); return nodes.get(selector); } };
    const paths = [];
    const controller = createController({ element, user: () => owner, api: (method, path) => { paths.push(path); return new Promise(resolve => resolvers.push(resolve)); } });
    const pending = controller.refresh(); owner = 'bob'; controller.reset();
    resolvers[0]({ connectors: [{ id: 'secret' }] }); resolvers[1]({ connections: [{ name: 'Alice private' }] }); resolvers[2]({roles: [{id: 'alice-role'}]}); await pending;
    assert.deepEqual(controller.getState().connections, []);
    assert.deepEqual(controller.getState().catalog, []);
    assert.deepEqual(paths, ['/api/connect/v1/catalog', '/api/connect/v1/connections', '/api/connect/v1/roles']);
    assert.deepEqual(controller.getState().roles, []);
});
test('Connect is available from management and loads its view module', () => {
    const html = fs.readFileSync('web/index.html', 'utf8');
    assert.match(html, /data-view="connect"/);
    assert.ok(html.indexOf('data-view="connect"') > html.indexOf('id="view-management"'));
    assert.match(html, /data-view-panel="connect"/);
    assert.match(html, /static\/js\/connect.js/);
});

test('unchanged polling preserves card DOM and keyboard focus', async () => {
    const nodes = new Map(); let writes = 0;
    const element = { innerHTML:'', addEventListener(){}, querySelector(selector) {
        if (!nodes.has(selector)) { let html=''; nodes.set(selector, {get innerHTML(){return html;},set innerHTML(value){html=value; writes++;}}); }
        return nodes.get(selector);
    }};
    const controller = createController({ element, user:()=> 'alice', api:async (method,path)=> path.endsWith('catalog') ? {connectors:[{id:'feishu',name:'飞书'}]} : {connections:[]} });
    await controller.refresh(); const initial = writes;
    await controller.refresh();
    assert.equal(writes, initial);
    controller.reset();
});

test('role options escape names and retain an unavailable selection without silently changing it', () => {
    const roles = [{id:'default', name:'Default'}, {id:'mentor', name:'<Coach>'}];
    assert.match(renderRoleSelect(roles, 'mentor', 'zh'), /value="mentor" selected>&lt;Coach&gt;/);
    assert.match(renderRoleSelect(roles, 'deleted', 'zh'), /value="" selected disabled>deleted · 不可用/);
    assert.match(renderConnections([{id:'1', name:'Work', role_id:'mentor'}], 'zh', '', roles), /人设: &lt;Coach&gt;/);
});

test('creation inherits the Web role and an existing connection saves its own role without reconnecting', async () => {
    const nodes = new Map(), handlers = {}, mutations = [];
    let connections = [];
    const element = {innerHTML:'', addEventListener(type, fn) { handlers[type] = fn; }, querySelector(selector) {
        if (!nodes.has(selector)) nodes.set(selector, {innerHTML:'', textContent:''});
        return nodes.get(selector);
    }};
    const controller = createController({element, user:()=> 'alice', currentRole:()=> 'mentor', api:async (method,path,body)=> {
        if (method !== 'GET') {
            mutations.push({method,path,body});
            connections = [{id:'cx', kind:'weixin', name:'Personal', role_id:body.role_id, desired_state:'enabled', status:'connected'}];
            return connections[0];
        }
        if (path.endsWith('/catalog')) return {connectors:[{id:'weixin', name:'微信', fields:[]}]};
        if (path.endsWith('/roles')) return {roles:[{id:'default',name:'默认助手'}, {id:'mentor',name:'Mentor'}]};
        return {connections};
    }});
    const click = (selector,dataset)=> handlers.click({target:{closest: s=> s===selector ? {dataset} : null}});
    const oldFormData = globalThis.FormData;
    globalThis.FormData = class {constructor(form) {this.form=form;} get(key) {return this.form.values[key];}};
    try {
        await controller.refresh();
        assert.match(element.innerHTML, /\/new.*\/status.*\/stop.*\/help/);
        await click('[data-connect-add]', {connectAdd:'weixin'});
        const form = nodes.get('.connect-form-slot');
        assert.match(form.innerHTML, /value="mentor" selected/);
        await handlers.submit({target:{matches:()=>true, values:{name:'Personal', role_id:'mentor'}}, preventDefault(){}});
        assert.equal(mutations[0].body.role_id, 'mentor');
        assert.equal(mutations[0].path, '/api/connect/v1/connections');
        await click('[data-connect-action]', {connectionId:'cx', connectAction:'role'});
        assert.match(form.innerHTML, /value="mentor" selected/);
        const beforePoll = form.innerHTML;
        await controller.refresh();
        assert.equal(form.innerHTML, beforePoll);
        await handlers.submit({target:{matches:()=>true, values:{role_id:'default'}}, preventDefault(){}});
        assert.deepEqual(mutations[1], {method:'PUT', path:'/api/connect/v1/connections/cx/role', body:{role_id:'default'}});
        assert.match(nodes.get('.connect-owned').innerHTML, /人设: 默认助手/);
    } finally {globalThis.FormData = oldFormData; controller.reset();}
});

test('role lookup recovery clears its warning and repairs the open form without losing entered credentials', async () => {
    const nodes = new Map(), handlers = {};
    let offline = true;
    const select = {value:'', innerHTML:''}, submit = {disabled:true};
    const element = {innerHTML:'', addEventListener(type, fn) {handlers[type] = fn;}, querySelector(selector) {
        if (selector === '.connect-form [name="role_id"]') return select;
        if (selector === '.connect-form button[type="submit"]') return submit;
        if (!nodes.has(selector)) nodes.set(selector, {innerHTML:'', textContent:''});
        return nodes.get(selector);
    }};
    const controller = createController({element, user:()=> 'alice', currentRole:()=> 'mentor', api:async (method,path)=> {
        if (path.endsWith('/roles')) {
            if (offline) throw new Error('HTTP 404');
            return {roles:[{id:'default',name:'Default'}, {id:'mentor',name:'Mentor'}]};
        }
        return path.endsWith('/catalog') ? {connectors:[{id:'feishu',name:'飞书',fields:[{key:'app_secret',secret:true}]}]} : {connections:[]};
    }});
    await controller.refresh();
    assert.match(nodes.get('.connect-feedback').textContent, /暂时无法加载人设/);
    await handlers.click({target:{closest: selector=> selector==='[data-connect-add]' ? {dataset:{connectAdd:'feishu'}} : null}});
    const formSlot = nodes.get('.connect-form-slot'), enteredForm = formSlot.innerHTML + '<!-- credential draft -->';
    formSlot.innerHTML = enteredForm;
    offline = false;
    await controller.refresh();
    assert.equal(nodes.get('.connect-feedback').textContent, '');
    assert.deepEqual(controller.getState().roles.map(role=>role.id), ['default','mentor']);
    assert.match(select.innerHTML, /value="mentor" selected/);
    assert.equal(submit.disabled, false);
    assert.equal(formSlot.innerHTML, enteredForm, 'refresh must not replace the credential form');
    controller.reset();
});

test('background role refresh does not erase a failed connection operation', async () => {
    const nodes = new Map(), handlers = {};
    let offline = false;
    const element = {innerHTML:'', addEventListener(type, fn) {handlers[type]=fn;}, querySelector(selector) {
        if (!nodes.has(selector)) nodes.set(selector,{innerHTML:'',textContent:''});
        return nodes.get(selector);
    }};
    const controller = createController({element,user:()=> 'alice',api:async (method,path)=> {
        if (method==='POST') throw new Error('断开失败，请重试');
        if (path.endsWith('/roles')) {if (offline) throw new Error('offline'); return {roles:[]};}
        if (path.endsWith('/catalog')) return {connectors:[{id:'weixin',name:'微信'}]};
        return {connections:[{id:'cx',kind:'weixin',name:'微信',status:'connected',desired_state:'enabled'}]};
    }});
    await controller.refresh();
    await handlers.click({target:{closest:selector=>selector==='[data-connect-action]' ? {dataset:{connectionId:'cx',connectAction:'disconnect'}} : null}});
    assert.equal(nodes.get('.connect-feedback').textContent,'断开失败，请重试');
    offline=true;
    await controller.refresh();
    offline=false;
    await controller.refresh();
    assert.equal(nodes.get('.connect-feedback').textContent,'断开失败，请重试');
    controller.reset();
});

function managementHarness({ api, confirm } = {}) {
    const nodes = new Map(), handlers = {}, mutations = [];
    let owner = 'alice';
    let connections = [{id:'cx', kind:'feishu', name:'Work', note:'工作账号\n<通知>', desired_state:'enabled', status:'connected'}];
    const element = {innerHTML:'', addEventListener(type, fn) { handlers[type] = fn; }, querySelector(selector) {
        if (!nodes.has(selector)) nodes.set(selector, {innerHTML:'', textContent:''});
        return nodes.get(selector);
    }};
    const controller = createController({element, user:()=>owner, confirm, api:async (method, path, body)=> {
        if (method !== 'GET') mutations.push({method,path,body});
        const override = api?.(method,path,body);
        if (override !== undefined) return override;
        if (path.endsWith('/catalog')) return {connectors:[{id:'feishu',name:'飞书',fields:[{key:'secret',secret:true}]}]};
        if (path.endsWith('/roles')) return {roles:[{id:'default',name:'默认助手'}]};
        if (path.endsWith('/note')) { connections = connections.map(c=>({...c,note:body.note})); return connections[0]; }
        return {connections};
    }});
    const click = (selector,dataset={})=> handlers.click({target:{closest:s=>s===selector ? {dataset} : null}});
    const action = name=>click('[data-connect-action]',{connectionId:'cx',connectAction:name});
    const submit = async values=> {
        const original = globalThis.FormData;
        globalThis.FormData = class { get(key) { return values[key]; } };
        try { await handlers.submit({target:{matches:()=>true},preventDefault(){}}); }
        finally { globalThis.FormData = original; }
    };
    return {controller,nodes,mutations,click,action,submit,setOwner(value){owner=value;}};
}

test('notes render as text, save independently of persona lookup, and can be cleared', async () => {
    const h = managementHarness({api:(method,path)=>path.endsWith('/roles') ? Promise.reject(new Error('offline')) : undefined});
    try {
        await h.controller.refresh();
        assert.match(h.nodes.get('.connect-owned').innerHTML, /工作账号\n&lt;通知&gt;/);
        await h.action('note');
        const form = h.nodes.get('.connect-form-slot').innerHTML;
        assert.match(form,/textarea name="note"/);
        assert.doesNotMatch(form,/name="role_id"|name="secret"|type="submit" disabled/);
        for (const note of ['用于团队消息', '']) {
            await h.action('note');
            await h.submit({note});
            assert.equal(h.controller.getState().connections[0].note, note);
            assert.deepEqual(h.mutations.at(-1),{method:'PUT',path:'/api/connect/v1/connections/cx/note',body:{note}});
        }
    } finally {h.controller.reset();}
});

test('deletion confirms the named connection and discards stale polling results', async () => {
    let allow = false, polling = false, resolvePoll;
    const prompts = [];
    const h = managementHarness({confirm:async (message,options)=>{prompts.push({message,options});return allow;}, api:(method,path)=> {
        if (method==='DELETE') return {};
        if (polling && path.endsWith('/connections')) return new Promise(resolve=>{resolvePoll=resolve;});
    }});
    try {
        await h.controller.refresh();
        await h.action('delete');
        assert.equal(h.mutations.length,0);
        assert.match(prompts[0].message,/Work/);
        assert.match(prompts[0].message,/聊天记录.*保留/);
        assert.equal(prompts[0].options.confirmText,'删除连接');
        allow = true; polling = true;
        const pending = h.controller.refresh();
        await h.action('delete');
        assert.deepEqual(h.mutations.map(m=>[m.method,m.path]),[['DELETE','/api/connect/v1/connections/cx']]);
        assert.deepEqual(h.controller.getState().connections,[]);
        resolvePoll({connections:[{id:'cx',kind:'feishu',name:'stale'}]});
        await pending;
        assert.deepEqual(h.controller.getState().connections,[]);
    } finally {h.controller.reset();}
});

test('failed deletion keeps the connection and account changes cancel pending confirmation', async () => {
    let approve;
    const h = managementHarness({confirm:()=>new Promise(resolve=>{approve=resolve;}),api:method=>method==='DELETE'?Promise.reject(new Error('删除失败')):undefined});
    try {
        await h.controller.refresh();
        const failed = h.action('delete'); approve(true); await failed;
        assert.equal(h.controller.getState().connections.length,1);
        assert.equal(h.nodes.get('.connect-feedback').textContent,'删除失败');
        const switched = h.action('delete'); h.setOwner('bob'); h.controller.reset(); approve(true); await switched;
        assert.equal(h.mutations.length,1,'confirmation must never act as the new account');
    } finally {h.controller.reset();}
});

test('repeated add clicks preserve the form and creation request ID after a failed attempt', async () => {
    const h = managementHarness({api:method=>method==='POST'?Promise.reject(new Error('request interrupted')):undefined});
    try {
        await h.controller.refresh();
        assert.match(h.nodes.get('.connect-catalog').innerHTML,/新增连接/);
        await h.click('[data-connect-add]',{connectAdd:'feishu'});
        const slot = h.nodes.get('.connect-form-slot');
        slot.innerHTML += '<!-- entered credentials -->';
        const entered = slot.innerHTML;
        await h.click('[data-connect-add]',{connectAdd:'feishu'});
        assert.equal(slot.innerHTML,entered);
        await h.submit({name:'Work',role_id:'default',secret:'credential',note:'work account'});
        await h.click('[data-connect-add]',{connectAdd:'feishu'});
        await h.submit({name:'Work',role_id:'default',secret:'credential',note:'work account'});
        assert.equal(h.mutations.length,2);
        assert.equal(h.mutations[0].body.request_id,h.mutations[1].body.request_id);
        assert.equal(h.mutations[0].body.note,'work account');
    } finally {h.controller.reset();}
});

test('saving a note during polling keeps the saved value and schedules a fresh read', async () => {
    let oldPoll, blockOnce = false, listCalls = 0, note = 'old';
    const h = managementHarness({api:(method,path,body)=> {
        if (path.endsWith('/note')) {note=body.note;return {id:'cx',kind:'feishu',name:'Work',note};}
        if (method==='GET' && path.endsWith('/connections')) {
            listCalls++;
            if (blockOnce) {blockOnce=false; return new Promise(resolve=>{oldPoll=resolve;});}
            return {connections:[{id:'cx',kind:'feishu',name:'Work',note}]};
        }
    }});
    try {
        await h.controller.refresh();
        await h.action('note');
        blockOnce=true;
        const pending = h.controller.refresh();
        await h.submit({note:'saved'});
        assert.equal(h.controller.getState().connections[0].note,'saved');
        oldPoll({connections:[{id:'cx',kind:'feishu',name:'Work',note:'old'}]});
        await pending;
        await new Promise(resolve=>setImmediate(resolve));
        assert.equal(h.controller.getState().connections[0].note,'saved');
        assert.equal(listCalls,3);
    } finally {h.controller.reset();}
});

test('double submission and catalog clicks while creating send only one request', async () => {
    let complete;
    const h = managementHarness({api:method=>method==='POST'?new Promise(resolve=>{complete=resolve;}):undefined});
    try {
        await h.controller.refresh();
        await h.click('[data-connect-add]',{connectAdd:'feishu'});
        const first = h.submit({name:'Work',role_id:'default',note:'work'});
        await h.click('[data-connect-add]',{connectAdd:'feishu'});
        await h.submit({name:'Work',role_id:'default',note:'work'});
        assert.equal(h.mutations.length,1);
        complete({id:'new'});
        await first;
        assert.equal(h.nodes.get('.connect-form-slot').innerHTML,'');
    } finally {h.controller.reset();}
});
