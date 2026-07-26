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

test('sidebar navigation follows the primary, Config, and Developer hierarchy', () => {
    const positions = {
        chat: indexSource.indexOf('data-view="chat"'),
        pulse: indexSource.indexOf('data-view="pulse"'),
        todos: indexSource.indexOf('data-view="todos"'),
        projects: indexSource.indexOf('data-view="projects"'),
        config: indexSource.indexOf('data-nav-group="config"'),
        developerGroup: indexSource.indexOf('data-nav-group="developer"'),
    };

    assert.ok(Object.values(positions).every((position) => position >= 0));
    assert.ok(
        positions.chat < positions.pulse
        && positions.pulse < positions.todos
        && positions.todos < positions.projects
        && positions.projects < positions.config
        && positions.config < positions.developerGroup,
    );

    const configSource = indexSource.slice(positions.config, positions.developerGroup);
    assert.match(indexSource, /class="nav-group config-nav-group collapsed" data-nav-group="config"/);
    assert.match(configSource, /data-toggle-nav-group="config"[\s\S]*?aria-expanded="false"/);
    const configItems = ['role', 'developer', 'tools', 'agents'].map(
        (view) => configSource.indexOf(`data-view="${view}"`),
    );
    assert.ok(configItems.every((position) => position >= 0));
    assert.ok(configItems.every((position, index) => index === 0 || configItems[index - 1] < position));

    const developerSource = indexSource.slice(
        positions.developerGroup,
        indexSource.indexOf('</nav>', positions.developerGroup),
    );
    assert.match(indexSource, /class="nav-group developer-nav-group collapsed" data-nav-group="developer"/);
    assert.match(developerSource, /data-toggle-nav-group="developer"[\s\S]*?aria-expanded="false"/);
    assert.ok(developerSource.indexOf('data-view="trace"') < developerSource.indexOf('data-view="eval"'));
    assert.match(developerSource, /href="\/admin\.html"/);
    assert.match(developerSource, /data-i18n="nav\.adminConfig"/);
    assert.doesNotMatch(developerSource, /data-view="tools"/);
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
