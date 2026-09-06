(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.LongTasks = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';
    const terminal = new Set(['completed', 'failed', 'partial', 'cancelled', 'interrupted']);
    const escape = value => String(value || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
    const labels = {
        preparing: ['正在准备', 'Preparing'], submitting: ['正在提交', 'Submitting'], queued: ['排队中', 'Queued'],
        running: ['生成中', 'Generating'], recovering: ['生成服务正在恢复', 'Provider recovering'],
        reconnecting: ['正在继续查询原任务', 'Checking the original task'], saving: ['正在保存结果', 'Saving result'],
        planning: ['正在制定研究计划', 'Planning research'], searching: ['正在检索资料', 'Searching sources'],
        summarizing: ['正在整理证据', 'Summarizing evidence'], reviewing: ['正在核验与补充证据', 'Reviewing evidence'],
        writing: ['正在撰写报告', 'Writing report'], assembling: ['正在整理最终结果', 'Preparing final result'],
        approval: ['等待你的授权', 'Needs your approval'], completed: ['已完成', 'Completed'], failed: ['执行失败', 'Failed'],
        partial: ['部分完成', 'Partially completed'], cancelled: ['已停止等待', 'Waiting stopped'],
        interrupted: ['服务重启，执行已中断', 'Interrupted by service restart'], attention: ['生成结果尚未确认', 'Generation outcome unconfirmed'],
    };
    const numberInRange = (value, min, max) => typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max ? value : null;
    function summarize(run = {}, now = Date.now()) {
        const events = run.events || [];
        let kind = run.agent_id === 'image_generation_v1' ? 'image' : run.agent_id === 'deep_research_v1' ? 'research' : '';
        let stage = 'preparing';
        let unresolvedMedia = false;
        let failedMedia = false;
        let updatedAt = run.started_at;
        const media = new Map();
        let progress = null, queuePosition = null, chunkTotal = null;
        const completedChunks = new Set();
        for (const event of events) {
            const type = event.type || '';
            const payload = event.payload || {};
            if (type === 'media.task.progress') {
                kind = payload.kind || kind;
                progress = numberInRange(payload.progress_percent, 0, 100);
                queuePosition = Number.isSafeInteger(payload.queue_position) && payload.queue_position >= 1 ? payload.queue_position : null;
                stage = { succeeded: 'saving', completed: 'assembling', unknown: 'attention' }[payload.stage] || payload.stage;
                media.set(payload.task_id || payload.idempotency_key || 'media', payload.stage);
                updatedAt = event.created_at || updatedAt;
            } else if (type.startsWith('research.')) {
                kind = kind || 'research';
                if (type.startsWith('research.step_summary.')) {
                    if (Number.isSafeInteger(payload.chunk_count) && payload.chunk_count > 0) chunkTotal = payload.chunk_count;
                    const chunk = payload.chunk ?? payload.chunk_index;
                    if (type.endsWith('.completed') && Number.isSafeInteger(chunk) && chunk > 0) completedChunks.add(chunk);
                }
                if (kind === 'research') {
                    if (type.includes('plan.')) stage = 'planning';
                    else if (type.includes('report_archive.')) stage = 'saving';
                    else if (type.includes('report.')) stage = 'writing';
                    else if (type.includes('gap') || type.includes('supplemental')) stage = 'reviewing';
                    else if (type.includes('step_summary')) stage = 'summarizing';
                    else if (type.includes('search') || type.includes('queries')) stage = 'searching';
                    updatedAt = event.created_at || updatedAt;
                }
            } else if (type === 'tool.started' || type === 'agent.tool.delegated') {
                const name = payload.name || payload.target_agent_id;
                if (name === 'generate_video') { kind = 'video'; stage = 'preparing'; }
                if (name === 'image_generation_v1') { kind = 'image'; stage = 'preparing'; }
                if (name === 'deep_research_v1') { kind = kind || 'research'; stage = 'planning'; }
            } else if (type === 'aigc.image.started') { kind = 'image'; stage = 'running'; }
            else if (type === 'aigc.image.completed') { kind = 'image'; stage = 'assembling'; }
            else if (type === 'approval.required') { stage = 'approval'; updatedAt = event.created_at || updatedAt; }
            else if (type === 'approval.resolved') stage = 'preparing';
        }
        unresolvedMedia = [...media.values()].some(s => s === 'unknown');
        failedMedia = [...media.values()].some(s => s === 'failed' || s === 'expired');
        let state = terminal.has(run.status) ? run.status : 'running';
        if (state === 'completed' && unresolvedMedia) state = 'attention';
        else if (state === 'completed' && failedMedia) state = 'partial';
        if (state !== 'running') {
            stage = state;
            updatedAt = run.completed_at || [...events].reverse().find(e => e.run_id === run.run_id && e.type === `run.${state}`)?.created_at || updatedAt;
        }
        const started = Date.parse(run.started_at || '');
        const end = terminal.has(run.status) ? Date.parse(run.completed_at || '') || now : now;
        const elapsed = Number.isFinite(started) ? Math.max(0, Math.floor((end - started) / 1000)) : 0;
        return { id: run.run_id, conversationId: run.conversation_id, title: run.input || '', kind: kind || 'task',
            stage, state, elapsed, updatedAt, active: !terminal.has(run.status), visible: Boolean(kind) || elapsed >= 30,
            needsApproval: stage === 'approval', progress: stage === 'running' ? progress : null,
            queuePosition: stage === 'queued' ? queuePosition : null,
            evidence: stage === 'summarizing' && chunkTotal && completedChunks.size <= chunkTotal ? { completed: completedChunks.size, total: chunkTotal } : null };
    }
    function duration(seconds) {
        return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
    }
    function renderReminder(id, muted, language = 'zh') {
        const en = language !== 'zh';
        return `<button type="button" data-task-mute="${escape(id)}" role="switch" aria-checked="${!muted}" aria-label="${en ? 'Task reminders' : '任务提醒'}"><span class="task-reminder-switch" aria-hidden="true"></span>${muted ? (en ? 'Reminders off' : '提醒已关闭') : (en ? 'Reminders on' : '提醒已开启')}</button>`;
    }
    function renderStages(task, en) {
        const stages = task.kind === 'research' ? ['planning', 'searching', 'summarizing', 'writing', 'saving']
            : ['preparing', 'queued', 'running', 'saving'];
        const current = { submitting: 'preparing', recovering: 'running', reconnecting: 'running', reviewing: 'summarizing', assembling: 'saving' }[task.stage] || task.stage;
        return `<ol class="long-task-stages" aria-label="${en ? 'Task stages' : '任务阶段'}">${stages.map(stage => `<li${stage === current && task.active ? ' aria-current="step"' : ''}>${escape(labels[stage][en ? 1 : 0])}</li>`).join('')}</ol>`;
    }
    function renderCard(task, language = 'zh', options = {}) {
        const en = language !== 'zh';
        const names = { image: ['图片生成', 'Image generation'], video: ['视频生成', 'Video generation'], research: ['深度研究', 'Deep research'], task: ['任务', 'Task'] };
        const name = (names[task.kind] || names.task)[en ? 1 : 0];
        const label = (labels[task.stage] || labels.preparing)[en ? 1 : 0];
        const note = task.active ? (task.needsApproval ? (en ? 'Open this conversation to continue.' : '请回到会话处理授权。')
            : (en ? 'You can leave this page. Results return to this conversation.' : '可以离开此页，结果会保存在原会话。'))
            : task.state === 'attention' || task.state === 'interrupted' ? (en ? 'The outcome is unconfirmed. Avoid submitting a duplicate task.' : '结果尚未确认，请避免重复提交生成任务。')
            : task.state === 'cancelled' && ['image', 'video'].includes(task.kind) ? (en ? 'The provider may still be generating.' : '生成服务可能仍在执行。') : '';
        const updated = task.updatedAt ? new Date(task.updatedAt).toLocaleTimeString(en ? 'en-US' : 'zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '';
        let metrics = '';
        if (task.active && task.queuePosition !== null && task.queuePosition !== undefined) metrics += `<div class="long-task-metric">${en ? `Queue position ${task.queuePosition}` : `排队第 ${task.queuePosition} 位`}</div>`;
        if (task.active && task.progress !== null && task.progress !== undefined) metrics += `<div class="long-task-metric">${en ? 'Generation progress' : '生成进度'} <strong>${task.progress}%</strong><progress max="100" value="${task.progress}" aria-label="${en ? 'Generation progress' : '生成进度'}"></progress></div>`;
        if (task.evidence) metrics += `<div class="long-task-metric">${en ? `Summarized ${task.evidence.completed} / ${task.evidence.total} evidence groups` : `已整理 ${task.evidence.completed} / ${task.evidence.total} 组资料`}<progress max="${task.evidence.total}" value="${task.evidence.completed}" aria-label="${en ? 'Evidence summary progress' : '资料整理进度'}"></progress></div>`;
        return `<section class="long-task-card${task.unread ? ' is-unread' : ''}" data-state="${escape(task.state)}" data-task-id="${escape(task.id)}">
            <div class="long-task-heading"><strong>${escape(name)}${task.unread ? `<span class="task-unread-dot" aria-label="${en ? 'Unread update' : '未读更新'}"></span>` : ''}</strong><span>${escape(label)}</span></div>
            <div class="long-task-title">${escape(task.title)}</div>
            ${task.kind !== 'task' && task.active ? renderStages(task, en) : ''}
            ${metrics}
            <div class="long-task-time">${en ? 'Elapsed' : '已用时'} ${duration(task.elapsed)}${updated ? ` · ${en ? 'Updated' : '状态更新于'} ${escape(updated)}` : ''}</div>
            ${note ? `<p>${escape(note)}</p>` : ''}
            <div class="long-task-actions">
                ${options.inline ? '' : `<button type="button" data-task-open="${escape(task.conversationId)}" data-task-read="${escape(task.id)}">${en ? 'Go to conversation' : '跳转至会话'}</button>`}
                ${task.unread ? `<button type="button" data-task-read-only="${escape(task.id)}">${en ? 'Mark read' : '标为已读'}</button>` : ''}
                ${task.active ? renderReminder(task.id, Boolean(options.muted), language) : ''}
            </div>
        </section>`;
    }
    function renderSummary(tasks, language = 'zh') {
        const en = language !== 'zh';
        const active = tasks.filter(task => task.active).length;
        const unread = tasks.filter(task => task.unread).length;
        return `<span>${en ? 'Background tasks' : '后台任务'}</span><span class="task-crumb-separator" aria-hidden="true">/</span><span>${active ? (en ? `${active} running` : `${active} 项进行中`) : (en ? 'No running tasks' : '暂无进行中任务')}</span>${unread ? `<span class="task-crumb-separator" aria-hidden="true">/</span><span class="task-update-badge">${en ? `${unread} unread` : `${unread} 条未读更新`}</span>` : ''}<span class="task-crumb-chevron" aria-hidden="true">⌄</span>`;
    }
    function renderLauncher(tasks, language = 'zh') {
        const en = language !== 'zh';
        const active = tasks.filter(task => task.active).length;
        const unread = tasks.filter(task => task.unread).length;
        const label = en ? `Background tasks, ${active} running, ${unread} unread updates`
            : `后台任务，${active} 项进行中，${unread} 条未读更新`;
        const count = unread || active;
        return `<svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="5" width="16" height="14" rx="4"/><path d="m8 10 2 2-2 2m5 0h3"/></svg><span class="visually-hidden">${label}</span>${count ? `<span class="task-launcher-count${unread ? ' is-unread' : ''}" aria-hidden="true">${count > 99 ? '99+' : count}</span>` : ''}`;
    }
    const shouldShowLauncher = tasks => tasks.some(task => task.active || task.unread);

    function createLauncherController({ button, shelf, body, getArea, storage, onDragStart }) {
        const key = 'long-task-launcher-position';
        const clamp = (n, min, max) => Math.min(Math.max(min, max), Math.max(min, n));
        let position = { x: .5, y: .9 }, drag = null, suppressClick = false;
        try {
            const saved = JSON.parse(storage?.getItem(key) || 'null');
            if (saved && [saved.x, saved.y].every(n => typeof n === 'number' && Number.isFinite(n) && n >= 0 && n <= 1)) position = saved;
        } catch { /* Position persistence is optional. */ }
        function bounds() {
            const area = getArea();
            return { ...area, minX: 8, maxX: Math.max(8, area.width - 52),
                minY: Math.max(8, area.top || 8),
                maxY: Math.max(area.top || 8, area.height - (area.bottom || 8) - 44) };
        }
        function point(b = bounds()) {
            return { x: b.minX + position.x * (b.maxX - b.minX), y: b.minY + position.y * (b.maxY - b.minY) };
        }
        function layout() {
            const b = bounds(), p = point(b);
            shelf.style.left = `${p.x}px`;
            shelf.style.top = `${p.y}px`;
            const width = Math.min(390, Math.max(44, b.width - 16));
            body.style.width = `${width}px`;
            body.style.left = `${clamp(p.x + 22 - width / 2, 8, b.width - width - 8) - p.x}px`;
            const above = p.y - b.minY - 12;
            const below = b.height - (b.bottom || 8) - p.y - 56;
            const up = above >= below;
            body.style.bottom = up ? '56px' : 'auto';
            body.style.top = up ? 'auto' : '56px';
            body.style.maxHeight = `${Math.max(0, Math.min(460, up ? above : below))}px`;
        }
        button.addEventListener('pointerdown', event => {
            if (event.button !== 0 || event.isPrimary === false || drag) return;
            suppressClick = false;
            drag = { id: event.pointerId, x: event.clientX, y: event.clientY, point: point(), original: { ...position }, moved: false };
            button.setPointerCapture(event.pointerId);
        });
        button.addEventListener('pointermove', event => {
            if (!drag || drag.id !== event.pointerId) return;
            const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
            if (!drag.moved && Math.hypot(dx, dy) < 6) return;
            if (!drag.moved) { drag.moved = true; onDragStart?.(); shelf.classList.toggle('is-dragging', true); }
            event.preventDefault();
            const b = bounds();
            const x = clamp(drag.point.x + dx, b.minX, b.maxX), y = clamp(drag.point.y + dy, b.minY, b.maxY);
            position = { x: (x - b.minX) / (b.maxX - b.minX || 1), y: (y - b.minY) / (b.maxY - b.minY || 1) };
            layout();
        });
        function finish(event, cancel = false) {
            if (!drag || drag.id !== event.pointerId) return;
            const previous = drag; drag = null;
            if (previous.moved) {
                suppressClick = true;
                if (cancel) position = previous.original;
                else {
                    event.preventDefault();
                    try { storage?.setItem(key, JSON.stringify(position)); } catch { /* Optional persistence. */ }
                }
            }
            shelf.classList.toggle('is-dragging', false);
            if (button.hasPointerCapture(event.pointerId)) button.releasePointerCapture(event.pointerId);
            layout();
        }
        button.addEventListener('pointerup', event => finish(event));
        button.addEventListener('pointercancel', event => finish(event, true));
        button.addEventListener('lostpointercapture', event => finish(event, true));
        layout();
        return { layout, consumeClick(event) {
            if (event?.detail === 0) return false;
            const suppressed = suppressClick; suppressClick = false; return suppressed;
        } };
    }
    function createTracker(storage) {
        let account = '', records = {}, items = new Map();
        function save() {
            try { storage?.setItem(`long-tasks:${account}`, JSON.stringify(records)); } catch { /* optional local preferences */ }
        }
        function read(id) {
            if (records[id]) {
                records[id].unread = false;
                if (records[id].active === false) records[id].resultRead = true;
            }
        }
        return {
            setAccount(value) {
                if (account === value) return;
                account = value || ''; items = new Map(); records = {};
                try { records = JSON.parse(storage?.getItem(`long-tasks:${account}`) || '{}') || {}; } catch { records = {}; }
                if (Array.isArray(records) || typeof records !== 'object') records = {};
            },
            update(runs, now = Date.now()) {
                const notifications = [];
                for (const run of runs || []) {
                    if (String(run.user_id) !== account || !run.run_id || !run.conversation_id) continue;
                    const task = summarize(run, now);
                    const previous = records[task.id];
                    if ((previous?.active === false || previous?.resultRead) && task.active) continue;
                    const signature = JSON.stringify([task.state, task.stage, task.queuePosition,
                        task.progress === null ? null : Math.floor(task.progress / 10), task.evidence]);
                    const revision = Date.parse(task.updatedAt || '') || 0;
                    if (task.active && previous?.revision > revision && revision > 0) continue;
                    const completed = previous?.active === true && !task.active;
                    const changed = completed || Boolean(previous?.signature && previous.signature !== signature);
                    const muted = Boolean(previous?.muted);
                    const resultRead = Boolean(previous?.resultRead);
                    const unread = !resultRead && !muted && (Boolean(previous?.unread) || (task.visible && changed));
                    if (task.visible) items.set(task.id, task);
                    if (task.visible && completed && !muted && !resultRead) notifications.push(task);
                    records[task.id] = { active: task.active, muted, unread, resultRead, signature, revision,
                        updated: changed ? now : previous?.updated || now };
                }
                Object.entries(records).filter(([,v]) => !v.active).sort((a,b) => b[1].updated - a[1].updated)
                    .slice(100).forEach(([key]) => { delete records[key]; items.delete(key); });
                save();
                return notifications;
            },
            tasks: () => [...items.values()].map(task => ({ ...task, unread: Boolean(records[task.id]?.unread) }))
                .sort((a,b) => Number(b.unread) - Number(a.unread) || Number(b.active) - Number(a.active) || (records[b.id]?.updated || 0) - (records[a.id]?.updated || 0)),
            mute(id) { records[id] = { ...records[id], muted: !records[id]?.muted, unread: false }; save(); },
            muted: id => Boolean(records[id]?.muted),
            markRead(id) { read(id); save(); },
            markResultRead(id) {
                if (!id || records[id]?.resultRead) return;
                records[id] = { ...records[id], resultRead: true, unread: false, updated: Date.now() };
                save();
            },
            markAllRead() { Object.keys(records).forEach(read); save(); },
        };
    }
    return Object.freeze({ summarize, renderCard, renderSummary, renderLauncher, renderReminder, shouldShowLauncher, createLauncherController, createTracker, duration });
}));
