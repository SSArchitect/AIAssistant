(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.ConnectUI = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';
    const labels = {
        zh: { note: '备注', noteHint: '选填，最多 500 字，用于区分账号或用途。', noteSave: '保存备注', delete: '删除连接', deleteConfirm: '确定删除连接「{name}」吗？将停止该连接的任务并移除连接配置和已保存的授权。已有聊天记录会保留。', catalogHelp: '新增连接会创建一条独立记录；恢复已有连接，请使用卡片上的“重新连接”。', rolesUnavailable: '暂时无法加载人设，请稍后刷新。连接管理仍可使用。', role: '人设', defaultRole: '默认助手', roleSave: '保存人设', roleHint: '从下一条新消息生效，复用该人设的长期记忆。旧会话内容保留；如需清空对话上下文，请在原平台发送 /new。', commands: '在原平台发送 /new 开始新会话，/status 查看任务，/stop 停止任务，/help 查看帮助。新会话保留人设和长期记忆。', mine: '我的连接', available: '可连接的端', empty: '还没有连接，选择下方支持的端开始。', none: '当前部署暂无可用连接端。', intro: '通过熟悉的端使用 Super Chat。不同来源使用独立会话。', check: '连接检测', details: '详情', reconnect: '重新连接', refresh: '刷新', cancel: '取消', name: '连接名称', save: '新增连接', disconnect: '断开连接', history: '查看会话', checking: '正在处理…', login: '请先登录账号。', retry: '重发', uncertain: '该消息可能已经送达。重发可能产生重复消息，确认重发？', feishuHelp: '飞书自建应用需开启机器人、接收私聊消息和发送消息权限，并订阅 im.message.receive_v1。选择“使用长连接接收事件”，发布应用后发送下方配对码。', pairing: '向机器人私聊发送：', source: '独立来源会话', checkNote: '检测不会发送聊天消息。未验证不代表不可用。', connected: '已连接', disconnected: '已断开', connecting: '连接中', awaiting_auth: '等待扫码', awaiting_pairing: '等待配对', error: '连接失败', degraded: '连接异常', partial: '部分已验证', passed: '通过', failed: '失败', unknown: '未验证', inbound: '接收消息', delivery: '发送消息', credentials: '凭据', permissions: '权限', transport: '网络', noHistory: '收到首条消息后创建独立会话。', close: '关闭详情' },
        en: { note: 'Note', noteHint: 'Optional, up to 500 characters. Describe the account or its purpose.', noteSave: 'Save note', delete: 'Delete connection', deleteConfirm: 'Delete connection “{name}”? Its tasks will stop and its settings and saved authorization will be removed. Existing chat history will be kept.', catalogHelp: 'Add connection creates a separate entry. To restore an existing connection, use Reconnect on its card.', rolesUnavailable: 'Personas could not be loaded. Refresh to try again. Connection management is still available.', role: 'Persona', defaultRole: 'Default assistant', roleSave: 'Save persona', roleHint: 'Applies to new messages and reuses this persona’s long-term memory. Previous conversation context remains; send /new in the connected app to start fresh.', commands: 'Send /new for a new conversation, /status for task status, /stop to stop tasks, or /help for help. New conversations keep the persona and long-term memory.', mine: 'My connections', available: 'Available connectors', empty: 'No connections yet. Choose a supported connector below.', none: 'No connectors are enabled on this deployment.', intro: 'Use Super Chat from your preferred apps. Each source has its own conversation.', check: 'Check connection', details: 'Details', reconnect: 'Reconnect', refresh: 'Refresh', cancel: 'Cancel', name: 'Connection name', save: 'Add connection', disconnect: 'Disconnect', history: 'View conversation', checking: 'Working…', login: 'Sign in to manage connections.', retry: 'Resend', uncertain: 'This message may already have arrived. Resending can create a duplicate. Resend?', feishuHelp: 'Enable the bot, direct-message receive and send permissions in your Feishu app. Subscribe to im.message.receive_v1 using a persistent connection, publish the app, then send the pairing code below.', pairing: 'Send this in a direct message to the bot:', source: 'Source conversations', checkNote: 'Checks do not send messages. Unknown does not mean unavailable.', connected: 'Connected', disconnected: 'Disconnected', connecting: 'Connecting', awaiting_auth: 'Scan to connect', awaiting_pairing: 'Pairing required', error: 'Connection failed', degraded: 'Connection issue', partial: 'Partially verified', passed: 'Passed', failed: 'Failed', unknown: 'Not verified', inbound: 'Receiving', delivery: 'Sending', credentials: 'Credentials', permissions: 'Permissions', transport: 'Network', noHistory: 'The first message creates a source conversation.', close: 'Close details' }
    };
    function esc(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
    function parse(value, fallback = null) { try { return JSON.parse(value); } catch (_) { return fallback; } }
    function copy(language) { return labels[language] || labels.zh; }
    function actions(connection) {
        return connection.desired_state === 'disconnected' ? ['check', 'details', 'role', 'note', 'reconnect', 'delete']
            : ['check', 'details', 'role', 'note', ...(['error', 'degraded', 'awaiting_pairing'].includes(connection.status) ? ['reconnect'] : []), 'disconnect', 'delete'];
    }
    function renderConnections(connections, language = 'zh', busy = '', roles = []) {
        const t = copy(language);
        if (!connections.length) return `<p class="connect-empty">${t.empty}</p>`;
        return connections.map(c => {
            const action = parse(c.next_action); let next = '';
            if (action?.kind === 'pairing') next = `<div class="connect-next"><p>${t.pairing}</p><code>/connect ${esc(action.value)}</code><p>${t.feishuHelp}</p></div>`;
            if (action?.kind === 'qr' && /^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(action.value)) next = `<div class="connect-next"><img class="connect-qr" src="${esc(action.value)}" alt="${t.awaiting_auth}"><p>${esc(action.description)}</p></div>`;
            return `<article class="connect-card"><div class="connect-card-head"><span class="connect-kind">${esc(c.kind)}</span><span class="connect-status status-${esc(c.status)}">${esc(t[c.status] || c.status)}</span></div><h3>${esc(c.name)}</h3>${c.note ? `<p class="connect-note">${esc(c.note)}</p>` : ''}<p class="connect-identity">${t.role}: ${esc(roleName(c.role_id || 'default', roles, language))}</p>${c.sender ? `<p class="connect-identity">${esc(c.sender)}</p>` : ''}${c.last_error ? `<p class="connect-error">${esc(c.last_error)}</p>` : ''}${next}<p class="connect-time">${c.last_check_at ? `${t.check}: ${esc(new Date(c.last_check_at).toLocaleString())}` : t.checkNote}</p><div class="connect-actions">${actions(c).map(action => `<button class="btn-secondary ${['disconnect', 'delete'].includes(action) ? 'connect-disconnect' : ''}" type="button" data-connect-action="${action}" data-connection-id="${esc(c.id)}" ${busy ? 'disabled' : ''}>${esc(t[action])}</button>`).join('')}</div></article>`;
        }).join('');
    }
    function roleName(id, roles, language) {
        return roles.find(role => role.id === id)?.name || (id === 'default' ? copy(language).defaultRole : id);
    }
    function renderRoleOptions(roles, selected, language) {
        const available = roles.some(r => r.id === selected);
        return `${available ? '' : `<option value="" selected disabled>${esc(roleName(selected, roles, language))} · ${language === 'en' ? 'Unavailable' : '不可用'}</option>`}${roles.map(role => `<option value="${esc(role.id)}" ${role.id === selected ? 'selected' : ''}>${esc(roleName(role.id, roles, language))}</option>`).join('')}`;
    }
    function renderRoleSelect(roles, selected, language) {
        const t = copy(language);
        return `<label>${t.role}<select name="role_id" required>${renderRoleOptions(roles, selected, language)}</select></label><p class="connect-time">${t.roleHint}</p>`;
    }
    function renderCatalog(catalog, language = 'zh') {
        const t = copy(language);
        if (!catalog.length) return `<p class="connect-empty">${t.none}</p>`;
        return catalog.map(c => `<article class="connect-card connect-catalog-card"><span class="connect-kind">${esc(c.id)}</span><h3>${esc(c.name)}</h3><button class="btn-primary" type="button" data-connect-add="${esc(c.id)}">${t.save}</button></article>`).join('');
    }
    function renderDetails(detail, language) {
        const t = copy(language);
        const checks = detail.checks || [];
        return `<div class="connect-detail-head"><h3>${esc(detail.connection.name)}</h3><button class="btn-secondary" data-connect-close type="button">${t.close}</button></div><p>${t.checkNote}</p>${checks.slice(0, 1).map(check => `<ul class="connect-diagnostics">${parse(check.results, []).map(r => `<li><strong>${esc(t[r.name] || r.name)}</strong><span>${esc(t[r.status] || r.status)}</span><p>${esc(r.detail)}</p></li>`).join('')}</ul>`).join('')}<h4>${t.source}</h4>${(detail.sources || []).map(source => source.conversation_id ? `<button type="button" class="btn-secondary" data-connect-history="${esc(source.conversation_id)}">${t.history} · ${esc(source.peer)}</button>` : '').join('') || `<p>${t.noHistory}</p>`}<ul class="connect-diagnostics">${(detail.deliveries || []).filter(d => ['unknown', 'failed'].includes(d.status)).map(d => `<li><span>${esc(d.last_error)}</span><button class="btn-secondary" data-connect-retry="${esc(d.id)}" data-connection-id="${esc(detail.connection.id)}" type="button">${t.retry}</button></li>`).join('')}</ul>`;
    }
    function createController({ element, api, user, language = () => 'zh', currentRole = () => 'default', openConversation, confirm = async () => false }) {
        let epoch = 0, account = '', catalog = [], roles = [], connections = [], detail = null, timer = null, visible = false, loading = false, busy = '', draft = null;
        let feedbackText = '', roleLoadFailed = false, revision = 0, refreshPending = false;
        const deletedIDs = new Set();
        const rendered = new WeakMap();
        function reset() { deletedIDs.clear(); epoch++; revision = 0; refreshPending = false; account = ''; catalog = []; roles = []; connections = []; detail = null; draft = null; busy = ''; loading = false; feedbackText = ''; roleLoadFailed = false; clearTimeout(timer); element.innerHTML = ''; }
        function shell() {
            const t = copy(language());
            element.innerHTML = `<div class="connect-page"><div class="connect-intro"><div><h2>Connect</h2><p>${t.intro}</p><p>${t.commands}</p></div><button class="btn-secondary" type="button" data-connect-refresh>${t.refresh}</button></div><p class="connect-feedback" role="status"></p><div class="connect-form-slot"></div><h2 class="connect-section-title">${t.mine}</h2><div class="connect-grid connect-owned"></div><section class="connect-detail" hidden></section><h2 class="connect-section-title">${t.available}</h2><p class="connect-time">${t.catalogHelp}</p><div class="connect-grid connect-catalog"></div></div>`;
        }
        function renderFeedback() { const el = element.querySelector('.connect-feedback'); if (el) el.textContent = feedbackText || (roleLoadFailed ? copy(language()).rolesUnavailable : ''); }
        function feedback(message) { feedbackText = message || ''; renderFeedback(); }
        function render() {
            if (!element.querySelector('.connect-page')) shell();
            renderFeedback();
            const replace = (selector, html) => { const node = element.querySelector(selector); if (rendered.get(node) !== html) { node.innerHTML = html; rendered.set(node, html); } };
            replace('.connect-owned', renderConnections(connections, language(), busy, roles));
            replace('.connect-catalog', renderCatalog(catalog, language()));
            const pane = element.querySelector('.connect-detail'); pane.hidden = !detail;
            replace('.connect-detail', detail ? renderDetails(detail, language()) : '');
        }
        async function refresh() {
            if (!user()) { reset(); shell(); feedback(copy(language()).login); return; }
            if (user() !== account) { reset(); account = user(); shell(); }
            if (loading) { refreshPending = true; return; } loading = true; const version = epoch, dataVersion = revision, owner = account;
            try {
                const detailId = detail?.connection?.id;
                const [types, owned, availableRoles, freshDetail] = await Promise.all([api('GET', '/api/connect/v1/catalog'), api('GET', '/api/connect/v1/connections'), api('GET', '/api/connect/v1/roles').catch(() => ({roles: null})), detailId ? api('GET', `/api/connect/v1/connections/${encodeURIComponent(detailId)}`).catch(() => null) : null]);
                if (version !== epoch || owner !== user() || dataVersion !== revision) return;
                if (detailId && detail?.connection?.id === detailId) detail = freshDetail;
                catalog = types.connectors || [];
                roleLoadFailed = !Array.isArray(availableRoles.roles);
                if (!roleLoadFailed) {
                    const rolesChanged = JSON.stringify(roles) !== JSON.stringify(availableRoles.roles);
                    roles = availableRoles.roles;
                    if (rolesChanged) refreshRoleForm();
                }
                connections = (owned.connections || []).filter(c => !deletedIDs.has(c.id)); render();
            } catch (e) { if (version === epoch && owner === user()) feedback(e.message); }
            finally { if (version === epoch) {
                loading = false; clearTimeout(timer);
                if (refreshPending) { refreshPending = false; void refresh(); }
                else if (visible) timer = setTimeout(refresh, 5000);
            } }
        }
        function showForm(kind, id = '', mode = 'credentials') {
            const connection = connections.find(c => c.id === id);
            const connector = catalog.find(c => c.id === kind) || (connection && ['role', 'note'].includes(mode) ? {name: connection.name, fields: []} : null);
            if (!connector) return;
            const t = copy(language()); draft = { kind, id, mode, requestID: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}` };
            const selected = id ? connections.find(c => c.id === id)?.role_id || 'default' : currentRole();
            const selectedRole = !id && roles.length && !roles.some(r => r.id === selected) ? roles[0].id : selected;
            draft.roleID = selectedRole;
            const title = mode === 'note' ? t.note : mode === 'role' ? t.role : id ? t.reconnect : t.save;
            const noteField = `<label>${t.note}<textarea name="note" rows="3" maxlength="500" placeholder="${esc(t.noteHint)}">${esc(connection?.note || '')}</textarea></label>`;
            element.querySelector('.connect-form-slot').innerHTML = `<form class="connect-form"><h3>${esc(connection?.name || connector.name)} · ${title}</h3>${id ? '' : `<label>${t.name}<input name="name" maxlength="80" required value="${esc(connector.name)}"></label>`}${!id || mode === 'role' ? renderRoleSelect(roles, selectedRole, language()) : ''}${!id || mode === 'note' ? noteField : ''}${['role', 'note'].includes(mode) ? '' : (connector.fields || []).map(f => `<label>${esc(f.label)}<input name="${esc(f.key)}" type="${f.secret ? 'password' : 'text'}" autocomplete="off" ${f.required && !id ? 'required' : ''}></label>`).join('')}<div class="connect-actions"><button class="btn-primary" type="submit" ${(!id || mode === 'role') && !roles.length ? 'disabled' : ''}>${mode === 'note' ? t.noteSave : mode === 'role' ? t.roleSave : id ? t.reconnect : t.save}</button><button class="btn-secondary" type="button" data-connect-cancel>${t.cancel}</button></div></form>`;
        }
        function refreshRoleForm() {
            if (!draft || (draft.id && draft.mode !== 'role')) return;
            const select = element.querySelector('.connect-form [name="role_id"]');
            if (!select) return;
            // Update options only: keep the user's selected role and all credential fields intact.
            draft.roleID = select.value || draft.roleID;
            select.innerHTML = renderRoleOptions(roles, draft.roleID, language());
            const submit = element.querySelector('.connect-form button[type="submit"]');
            if (submit) submit.disabled = !roles.length;
        }
        async function operation(id, task) {
            if (busy) return; const version = epoch, owner = user(); busy = id; render(); feedback(copy(language()).checking);
            try { await task(); if (epoch !== version || owner !== user()) return; revision++; feedback(''); await refresh(); }
            catch (e) { if (epoch === version && owner === user()) feedback(e.message); }
            finally { if (epoch === version) { busy = ''; render(); } }
        }
        element.addEventListener('click', async event => {
            const add = event.target.closest('[data-connect-add]'); if (add) {
                if (busy || (draft && !draft.id && draft.kind === add.dataset.connectAdd)) return;
                showForm(add.dataset.connectAdd); return;
            }
            if (event.target.closest('[data-connect-refresh]')) { await refresh(); return; }
            if (event.target.closest('[data-connect-cancel]')) { if (busy) return; draft = null; element.querySelector('.connect-form-slot').innerHTML = ''; return; }
            if (event.target.closest('[data-connect-close]')) { detail = null; render(); return; }
            const history = event.target.closest('[data-connect-history]'); if (history) { await openConversation(history.dataset.connectHistory); return; }
            const retry = event.target.closest('[data-connect-retry]');
            if (retry) { const owner = user(); if (!await confirm(copy(language()).uncertain) || owner !== user()) return; await operation(retry.dataset.connectionId, () => api('POST', `/api/connect/v1/connections/${encodeURIComponent(retry.dataset.connectionId)}/deliveries/${encodeURIComponent(retry.dataset.connectRetry)}/retry`, {})); return; }
            const button = event.target.closest('[data-connect-action]'); if (!button || busy) return;
            const id = button.dataset.connectionId, action = button.dataset.connectAction, connection = connections.find(c => c.id === id); if (!connection) return;
            if (action === 'role' || action === 'note') { showForm(connection.kind, id, action); return; }
            if (action === 'delete') {
                const version = epoch, owner = user(), t = copy(language());
                if (!await confirm(t.deleteConfirm.replace('{name}', connection.name), {confirmText: t.delete, danger: true}) || epoch !== version || owner !== user()) return;
                await operation(id, async () => {
                    await api('DELETE', `/api/connect/v1/connections/${encodeURIComponent(id)}`);
                    if (epoch !== version || owner !== user()) return;
                    deletedIDs.add(id);
                    connections = connections.filter(c => c.id !== id);
                    if (detail?.connection?.id === id) detail = null;
                    if (draft?.id === id) { draft = null; element.querySelector('.connect-form-slot').innerHTML = ''; }
                });
                return;
            }
            if (action === 'reconnect') { showForm(connection.kind, id); return; }
            await operation(id, async () => {
                const version = epoch;
                if (action !== 'details') await api('POST', `/api/connect/v1/connections/${encodeURIComponent(id)}/${action}`, {});
                if (action === 'check' || action === 'details') { const data = await api('GET', `/api/connect/v1/connections/${encodeURIComponent(id)}`); if (epoch === version) detail = data; }
            });
        });
        element.addEventListener('submit', async event => {
            if (!event.target.matches('.connect-form')) return; event.preventDefault(); if (!draft || busy) return;
            const data = new FormData(event.target), current = draft, credentials = {};
            for (const field of catalog.find(c => c.id === current.kind)?.fields || []) credentials[field.key] = String(data.get(field.key) || '');
            await operation(current.id || 'create', async () => {
                const version = epoch;
                if (current.mode === 'role') await api('PUT', `/api/connect/v1/connections/${encodeURIComponent(current.id)}/role`, { role_id: data.get('role_id') });
                else if (current.mode === 'note') {
                    const updated = await api('PUT', `/api/connect/v1/connections/${encodeURIComponent(current.id)}/note`, { note: String(data.get('note') || '') });
                    if (epoch === version) connections = connections.map(c => c.id === current.id ? updated : c);
                }
                else await api('POST', current.id ? `/api/connect/v1/connections/${encodeURIComponent(current.id)}/reconnect` : '/api/connect/v1/connections', current.id ? { credentials } : { kind: current.kind, name: data.get('name'), role_id: data.get('role_id'), request_id: current.requestID, note: String(data.get('note') || ''), credentials });
                if (epoch === version) { draft = null; element.querySelector('.connect-form-slot').innerHTML = ''; }
            });
        });
        return { refresh, reset, setVisible(value) { visible = value; clearTimeout(timer); if (value) { shell(); render(); if (draft) showForm(draft.kind, draft.id, draft.mode); void refresh(); } }, getState: () => ({ account, connections, catalog, roles }) };
    }
    return { actions, renderConnections, renderCatalog, renderRoleSelect, createController };
});
