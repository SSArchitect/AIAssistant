'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const indexSource = fs.readFileSync(
    path.resolve(__dirname, '../web/index.html'),
    'utf8',
);
const adminSource = fs.readFileSync(
    path.resolve(__dirname, '../web/admin.html'),
    'utf8',
);
const adminAppSource = fs.readFileSync(
    path.resolve(__dirname, '../web/static/js/admin.js'),
    'utf8',
);
const appSource = fs.readFileSync(
    path.resolve(__dirname, '../web/static/js/app.js'),
    'utf8',
);

function extractFunctionDeclaration(name) {
    const marker = `function ${name}(`;
    const start = appSource.indexOf(marker);
    assert.notEqual(start, -1, `missing ${name} in app.js`);

    const parametersEnd = appSource.indexOf(')', start + marker.length);
    const bodyStart = appSource.indexOf('{', parametersEnd);
    assert.notEqual(bodyStart, -1, `missing body for ${name}`);
    let depth = 0;
    let quote = '';
    let escaped = false;
    for (let index = bodyStart; index < appSource.length; index += 1) {
        const char = appSource[index];
        if (escaped) {
            escaped = false;
            continue;
        }
        if (quote) {
            if (char === '\\') escaped = true;
            else if (char === quote) quote = '';
            continue;
        }
        if (['"', "'", '`'].includes(char)) {
            quote = char;
            continue;
        }
        if (char === '{') depth += 1;
        if (char === '}') {
            depth -= 1;
            if (depth === 0) return appSource.slice(start, index + 1);
        }
    }
    assert.fail(`unterminated ${name}`);
}

test('sidebar keeps four primary destinations and moves management into a dedicated view', () => {
    const sidebarSource = indexSource.slice(indexSource.indexOf('<aside class="sidebar"'), indexSource.indexOf('</aside>'));
    const navSource = sidebarSource.slice(sidebarSource.indexOf('<nav'), sidebarSource.indexOf('</nav>'));
    assert.deepEqual(Array.from(navSource.matchAll(/data-view="([^"]+)"/g), match => match[1]), ['chat', 'pulse', 'todos', 'projects']);
    assert.doesNotMatch(sidebarSource, /data-nav-group|data-view="connect"|id="model-select"/);
    assert.match(sidebarSource, /data-view="management"/);
    const managementSource = indexSource.slice(indexSource.indexOf('id="view-management"'), indexSource.indexOf('id="view-connect"'));
    for (const view of ['connect', 'role', 'developer', 'tools', 'agents', 'trace', 'eval']) {
        assert.match(managementSource, new RegExp(`data-view="${view}"`));
    }
    assert.match(managementSource, /href="\/admin\.html"/);
    const footer = sidebarSource.slice(sidebarSource.indexOf('<div class="sidebar-footer">'));
    assert.match(footer, /id="account-select"/);
});

test('model selection lives in settings and management, with one shared control outside chat', () => {
    const managementSource = indexSource.slice(indexSource.indexOf('id="view-management"'), indexSource.indexOf('id="view-connect"'));
    const chatSource = indexSource.slice(indexSource.indexOf('id="view-chat"'), indexSource.indexOf('id="view-pulse"'));
    assert.match(managementSource, /aria-labelledby="management-model-title"/);
    assert.match(managementSource, /id="management-model-title" data-i18n="sidebar.modelSelect">模型选择/);
    assert.match(managementSource, /<select id="model-select"[^>]*aria-labelledby="management-model-title"/);
    assert.match(managementSource, /<option value="" data-i18n="sidebar.defaultModel">默认模型/);
    assert.equal((indexSource.match(/id="model-select"/g) || []).length, 1);
    assert.equal((indexSource.match(/id="current-model"/g) || []).length, 1);
    assert.doesNotMatch(chatSource, /id="model-select"|model-picker/);
});

test('management destinations share a highlighted parent while main destinations remain independent', () => {
    const resolve = vm.runInNewContext(`${extractFunctionDeclaration('navigationSectionForView')}; navigationSectionForView`);
    for (const view of ['management', 'connect', 'role', 'developer', 'tools', 'agents', 'trace', 'eval']) {
        assert.equal(resolve(view), 'management');
    }
    for (const view of ['chat', 'pulse', 'todos', 'projects', 'unknown']) assert.equal(resolve(view), view);
});

test('navigation updates parent highlight and the management return button without expanding a sidebar menu', () => {
    const makeItem = (view, id = '') => ({
        id, dataset: { view }, attributes: {}, active: false,
        classList: { toggle(_name, value) { this.owner.active = value; } },
        setAttribute(name, value) { this.attributes[name] = value; },
        removeAttribute(name) { delete this.attributes[name]; },
    });
    const items = [makeItem('chat'), makeItem('management', 'btn-management'), makeItem('role')];
    items.forEach(item => { item.classList.owner = item; });
    const back = { hidden: true };
    const context = vm.createContext({ document: { querySelectorAll: () => items, getElementById: () => back } });
    vm.runInContext(`${extractFunctionDeclaration('navigationSectionForView')}\n${extractFunctionDeclaration('updateNavigationSelection')}`, context);
    vm.runInContext("updateNavigationSelection('role')", context);
    assert.equal(items[1].active, true);
    assert.equal(items[1].attributes['aria-current'], 'page');
    assert.equal(back.hidden, false);
    vm.runInContext("updateNavigationSelection('management')", context);
    assert.equal(back.hidden, true);
    vm.runInContext("updateNavigationSelection('chat')", context);
    assert.equal(items[0].active, true);
    assert.equal(items[1].active, false);
    assert.equal(items[1].attributes['aria-current'], undefined);
    assert.equal(back.hidden, true);
});

test('entering management closes the mobile drawer, preserves desktop state, and ignores unknown views', () => {
    let mobile = true;
    const sidebarCalls = [];
    const panel = { dataset: { viewPanel: 'management' }, classList: { toggle: (_key, value) => { panel.active = value; } } };
    const context = vm.createContext({
        VIEW_COPY: { management: [] }, activeView: 'chat', connectController: null,
        document: { querySelectorAll: () => [panel] },
        updateNavigationSelection() {}, updateTopbar() {}, updateChatHistoryControls() {},
        isMobileLayout: () => mobile, setSidebarOpen: open => sidebarCalls.push(open),
    });
    vm.runInContext(`${extractFunctionDeclaration('closeMobileSidebar')}\n${extractFunctionDeclaration('setView')}`, context);
    vm.runInContext("setView('management')", context);
    assert.equal(context.activeView, 'management');
    assert.equal(panel.active, true);
    assert.deepEqual(sidebarCalls, [false]);
    mobile = false;
    vm.runInContext("setView('management')", context);
    vm.runInContext("setView('invalid')", context);
    assert.deepEqual(sidebarCalls, [false]);
    assert.equal(context.activeView, 'management');
});

test('management hides chat-only header controls and the stylesheet honors hidden controls', () => {
    const rolePicker = { hidden: false };
    const btnNewChat = { hidden: false };
    const context = vm.createContext({
        activeView: 'management', VIEW_COPY: { management: ['title', 'subtitle'] },
        rolePicker, btnNewChat, closeRoleMemoryPopover() {},
        viewTitle: {}, viewSubtitle: {}, t: key => key,
    });
    vm.runInContext(`${extractFunctionDeclaration('updateTopbar')}\nupdateTopbar()`, context);
    assert.equal(rolePicker.hidden, true);
    assert.equal(btnNewChat.hidden, true);
    const style = fs.readFileSync(path.resolve(__dirname, '../web/static/css/style.css'), 'utf8');
    assert.match(style, /\.topbar \[hidden\]\s*\{\s*display: none;/);
});

test('management return uses the shared toolbar button style and keeps its arrow when translated', () => {
    const actions = indexSource.slice(indexSource.indexOf('<div class="topbar-actions">'), indexSource.indexOf('<div class="role-picker"'));
    assert.match(actions, /class="btn-secondary management-back" id="management-back"/);
    const button = actions.match(/<button[^>]*id="management-back"[\s\S]*?<\/button>/)?.[0] || '';
    assert.match(button, /data-view="management"/);
    assert.match(button, /<svg[^>]*aria-hidden="true"/);
    assert.match(button, /<span data-i18n="management.back">/);
    assert.doesNotMatch(button.slice(0, button.indexOf('>')), /data-i18n=/);
    const style = fs.readFileSync(path.resolve(__dirname, '../web/static/css/style.css'), 'utf8');
    assert.doesNotMatch(style, /\.management-back\s*\{[^}]*border:\s*0/);
});

test('Android back closes the drawer before returning from management details to their parent', async () => {
    const bridge = fs.readFileSync(path.resolve(__dirname, '../mobile/android-bridge.js'), 'utf8');
    const start = bridge.indexOf("  App.addListener('backButton'");
    const end = bridge.indexOf("  AppUpdater.addListener('downloadProgress'", start);
    const clicks = [];
    class Element {
        constructor(name, hidden) { this.name = name; this.hidden = hidden; }
        click() { clicks.push(this.name); }
    }
    const drawer = new Element('drawer', false);
    const back = new Element('management', false);
    const chat = new Element('chat', false);
    let handler;
    let view = 'role';
    const context = vm.createContext({
        HTMLElement: Element,
        App: { addListener: (_event, callback) => { handler = callback; }, minimizeApp: () => clicks.push('minimize') },
        document: {
            getElementById: id => id === 'sidebar-backdrop' ? drawer : id === 'management-back' ? back : null,
            querySelector: selector => selector === '[data-view-panel].active'
                ? { getAttribute: () => view } : selector === '[data-view="chat"]' ? chat : null,
        },
    });
    vm.runInContext(bridge.slice(start, end), context);
    await handler();
    assert.deepEqual(clicks, ['drawer']);
    drawer.hidden = true;
    await handler();
    assert.deepEqual(clicks, ['drawer', 'management']);
    back.hidden = true;
    view = 'management';
    await handler();
    assert.equal(clicks.at(-1), 'chat');
    view = 'chat';
    await handler();
    assert.equal(clicks.at(-1), 'minimize');
});

test('recent conversations are bounded, searchable across all titles, and retain the current conversation', () => {
    const select = vm.runInNewContext(`${extractFunctionDeclaration('selectSidebarConversations')}; selectSidebarConversations`);
    const rows = Array.from({ length: 14 }, (_, i) => ({ id: String(i), title: `Topic ${i}` }));
    const titles = row => row.title;
    assert.equal(select(rows, '', false, null, titles).length, 10);
    assert.deepEqual(Array.from(select(rows, '', false, '13', titles), row => row.id), ['0','1','2','3','4','5','6','7','8','13']);
    assert.equal(select(rows, '', true, null, titles).length, 14);
    assert.deepEqual(Array.from(select(rows, ' TOPIC 13 ', false, null, titles), row => row.id), ['13']);
    assert.equal(select(rows, 'missing', false, '13', titles).length, 0);
    assert.equal(select([], '', false, null, titles).length, 0);
    assert.equal(rows.length, 14);
});

test('conversation controls expand, collapse, filter all titles, and reset for another account', () => {
    const list = { innerHTML: '' };
    const search = { value: '' };
    const button = { hidden: true, setAttribute(name, value) { this[name] = value; } };
    const context = vm.createContext({
        conversations: Array.from({ length: 12 }, (_, i) => ({ id: String(i), title: `Chat ${i}` })),
        conversationList: list, conversationSearch: search, conversationShowAll: button,
        conversationSectionCount: {}, showAllSidebarConversations: false, currentConversationId: null,
        pendingConversationDeletes: new Set(), displayConversationTitle: row => row.title,
        escapeHtml: value => String(value).replaceAll('<', '&lt;'), escapeAttr: value => value,
        t: key => key,
    });
    for (const name of ['selectSidebarConversations', 'renderConversationList', 'toggleSidebarConversationList', 'resetSidebarConversationFilter']) {
        vm.runInContext(extractFunctionDeclaration(name), context);
    }
    vm.runInContext('renderConversationList()', context);
    assert.equal((list.innerHTML.match(/data-conversation-id=/g) || []).length, 10);
    assert.equal(button.hidden, false);
    vm.runInContext('toggleSidebarConversationList()', context);
    assert.equal((list.innerHTML.match(/data-conversation-id=/g) || []).length, 12);
    assert.equal(button['aria-expanded'], 'true');
    vm.runInContext('toggleSidebarConversationList()', context);
    assert.equal(button['aria-expanded'], 'false');
    search.value = 'chat 11';
    vm.runInContext('renderConversationList()', context);
    assert.match(list.innerHTML, /Chat 11/);
    assert.equal(button.hidden, true);
    search.value = 'absent';
    vm.runInContext('renderConversationList()', context);
    assert.match(list.innerHTML, /sidebar.noMatchingConversations/);
    vm.runInContext('resetSidebarConversationFilter()', context);
    assert.equal(search.value, '');
    assert.equal(context.showAllSidebarConversations, false);
    context.conversations = [];
    vm.runInContext('renderConversationList()', context);
    assert.equal(button.hidden, true);
    assert.match(list.innerHTML, /sidebar.emptyConversations/);
    assert.match(extractFunctionDeclaration('switchAccount'), /resetSidebarConversationFilter\(\)/);
});

test('empty or missing pinned agents hide the section; disabled agents stay disabled without runtime details', () => {
    const section = { hidden: false };
    const list = { innerHTML: '', closest: () => section };
    const count = { textContent: '' };
    const context = vm.createContext({
        pinnedAgentList: list, pinnedSectionCount: count, pinnedAgentIds: ['missing'], agents: [],
        currentAgentId: 'a', escapeHtml: value => String(value), escapeAttr: value => String(value),
        agentIconText: () => 'A', t: key => key,
    });
    vm.runInContext(extractFunctionDeclaration('renderPinnedAgents'), context);
    vm.runInContext('renderPinnedAgents()', context);
    assert.equal(section.hidden, true);
    assert.equal(list.innerHTML, '');
    context.pinnedAgentIds = ['a'];
    context.agents = [{ id: 'a', name: 'Assistant', framework: 'internal-runtime', enabled: false }];
    vm.runInContext('renderPinnedAgents()', context);
    assert.equal(section.hidden, false);
    assert.match(list.innerHTML, /disabled/);
    assert.doesNotMatch(list.innerHTML, /internal-runtime|<small>/);
    assert.equal(count.textContent, '1');
});

test('admin settings moved out of the sidebar footer and Role has its own view', () => {
    const footerSource = indexSource.slice(
        indexSource.indexOf('<div class="sidebar-footer">'),
        indexSource.indexOf('</aside>'),
    );

    assert.doesNotMatch(footerSource, /\/admin\.html/);
    assert.doesNotMatch(indexSource, /完整配置/);
    assert.equal((indexSource.match(/href="\/admin\.html"/g) || []).length, 1);
    assert.match(indexSource, /data-view="role"/);
    assert.match(indexSource, /data-view-panel="role"/);
    assert.match(appSource, /role:\s*\['views\.role\.title',\s*'views\.role\.subtitle'\]/);
    assert.doesNotMatch(adminSource, /id="role-list"/);
    assert.doesNotMatch(adminSource, /data-i18n="roles\.title"/);
    assert.doesNotMatch(adminAppSource, /\/api\/roles/);
    assert.doesNotMatch(adminAppSource, /ROLE_EXAMPLES/);
    assert.match(adminSource, /<title>管理员配置 - Agent Assistant<\/title>/);
    assert.match(adminSource, /data-i18n="admin\.title">管理员配置<\/h1>/);
});

test('Role payload trims multiline instructions and preferences without user_id', () => {
    const source = extractFunctionDeclaration('parseRoleConfigLines');
    const parsed = vm.runInNewContext(
        `${source}\nparseRoleConfigLines(' first \\n\\n second  \\n');`,
    );
    assert.deepEqual(Array.from(parsed), ['first', 'second']);

    const collectSource = extractFunctionDeclaration('collectRoleConfigPayload');
    assert.match(collectSource, /metadata\.preferences\s*=\s*parseRoleConfigLines/);
    assert.doesNotMatch(collectSource, /user_id/);
});

test('Role CRUD uses account-scoped routes and guards built-in roles', () => {
    const saveSource = appSource.slice(
        appSource.indexOf('async function saveRoleConfig('),
        appSource.indexOf('async function deleteRoleConfig('),
    );
    const deleteSource = extractFunctionDeclaration('deleteRoleConfig');

    assert.match(saveSource, /isBuiltInRole\(existing\)/);
    assert.match(saveSource, /apiCall\('POST', '\/api\/roles'/);
    assert.match(saveSource, /apiCall\('PUT', `\/api\/roles\/\$\{encodeURIComponent\(existing\.id\)\}`/);
    assert.match(deleteSource, /isBuiltInRole\(role\)/);
    assert.match(deleteSource, /apiCall\('DELETE', `\/api\/roles\/\$\{encodeURIComponent\(role\.id\)\}`/);
});

test('Role redraws preserve the exact dirty form draft', () => {
    const inputs = {
        id: { value: 'custom_role' },
        name: { value: '  Draft name  ' },
        description: { value: 'Draft description' },
        'base-persona': { value: 'Line one\n\nLine two  ' },
        instructions: { value: ' first \n\n second  \n' },
        preferences: { value: ' keep spacing \n\n and blanks ' },
        enabled: { checked: false },
        'memory-enabled': { checked: true },
    };
    const context = vm.createContext({
        selectedRoleConfigId: 'custom_role',
        roleConfigDraft: null,
        roleConfigDirty: false,
        roleConfigInput: (id) => inputs[id] || null,
        readRoleConfigChecked: (id) => Boolean(inputs[id]?.checked),
        setRoleConfigValue: (id, value) => {
            inputs[id].value = value;
        },
        setRoleConfigChecked: (id, value) => {
            inputs[id].checked = Boolean(value);
        },
        syncRoleConfigEditorControls: () => {},
    });

    [
        'captureRoleConfigDraft',
        'restoreRoleConfigDraftIfDirty',
        'renderRoleConfigEditor',
    ].forEach((name) => {
        vm.runInContext(extractFunctionDeclaration(name), context);
    });

    vm.runInContext('captureRoleConfigDraft()', context);
    Object.values(inputs).forEach((input) => {
        if (Object.hasOwn(input, 'value')) input.value = '';
        if (Object.hasOwn(input, 'checked')) input.checked = true;
    });
    vm.runInContext('renderRoleConfigEditor()', context);

    assert.equal(inputs.name.value, '  Draft name  ');
    assert.equal(inputs['base-persona'].value, 'Line one\n\nLine two  ');
    assert.equal(inputs.instructions.value, ' first \n\n second  \n');
    assert.equal(inputs.preferences.value, ' keep spacing \n\n and blanks ');
    assert.equal(inputs.enabled.checked, false);
    assert.equal(inputs['memory-enabled'].checked, true);
});

test('language changes, repeated Role navigation, and save failures retain the dirty draft', () => {
    const languageSource = extractFunctionDeclaration('setLanguage');
    const setViewSource = extractFunctionDeclaration('setView');
    const editorSource = extractFunctionDeclaration('renderRoleConfigEditor');
    const saveSource = appSource.slice(
        appSource.indexOf('async function saveRoleConfig('),
        appSource.indexOf('async function deleteRoleConfig('),
    );
    const catchStart = saveSource.indexOf('} catch (err) {');
    const catchEnd = saveSource.indexOf('} finally {', catchStart);

    assert.match(languageSource, /renderRoleConfig\(\)/);
    assert.match(setViewSource, /if \(view === 'role'\) renderRoleConfig\(\)/);
    assert.match(editorSource, /if \(restoreRoleConfigDraftIfDirty\(\)\) return/);
    assert.ok(saveSource.indexOf('captureRoleConfigDraft()') < saveSource.indexOf("apiCall('POST', '/api/roles'"));
    assert.match(saveSource, /selectedRoleConfigId = saved\.id;\s*clearRoleConfigDraft\(\)/);
    assert.doesNotMatch(saveSource.slice(catchStart, catchEnd), /clearRoleConfigDraft\(\)/);
});
