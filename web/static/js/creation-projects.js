(function (root, factory) {
    const api = factory(typeof module === 'object' && module.exports ? require('./creation-library.js') : root.CreationLibrary);
    if (typeof module === 'object' && module.exports) module.exports = api;
    root.CreationProjects = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (Library) {
    'use strict';
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const parse = (value, fallback) => { try { return typeof value === 'string' ? JSON.parse(value) : value || fallback; } catch (_) { return fallback; } };
    const uid = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const statusNames = { queued: '等待生成', running: '生成中', stopping: '正在停止', completed: '已完成', failed: '生成失败', cancelled: '已停止', interrupted: '已中断' };
    const roleNames = { identity: '人物身份', style: '画面风格', first_frame: '视频首帧', reference: '视觉参考', environment: '场景环境', composition: '镜头构图' };
    function documentOf(project) { return parse(project?.document, { plan: { nodes: [], questions: [] }, states: {}, messages: [], asset_ids: [] }); }
    const automaticActive = project => ['running', 'stopping'].includes(project?.automatic_status);
    function automaticBlock(project, runs = []) {
        if (!documentOf(project).plan.nodes.length) return '先形成创作画布';
        if (project?.planning) return '正在规划';
        if (automaticActive(project)) return '一键生成正在进行';
        if (runs.some(r => ['queued','running','stopping'].includes(r.status))) return '等待当前生成完成';
        return '';
    }
    function renderAutomatic(project, open = true) {
        const activity = documentOf(project).automation;
        if (!activity || !automaticActive(project)) return '';
        return `<details class="cp-planning cp-automatic is-running" data-cp-planning="auto:${esc(activity.id)}" ${open ? 'open' : ''}><summary><strong>${project.automatic_status === 'stopping' ? '正在停止一键生成' : '一键生成中'}</strong><span>已确认内容保持不变</span></summary><div class="cp-planning-body"><ol>${planningSteps(activity)}</ol><p>可以离开此页，创作助手会继续按依赖完成后续节点。</p></div></details>`;
    }
    function approved(state) { return !!state?.revision && state.approved_revision === state.revision; }
    function dependenciesReady(doc, node) { return (node.depends_on || []).every(id => approved(doc.states[id])); }
    function generationBlock(project, node, runs = []) {
        const doc = documentOf(project);
        if (automaticActive(project)) return '创作助手正在一键生成，可先停止再手动调整';
        if (project?.planning) return '创作助手正在整理方案';
        if (doc.plan.questions?.length) return '先确定创作方向';
        if (!dependenciesReady(doc, node)) return '先确认上游内容';
        if (node.kind === 'video' && !approved(doc.states[node.id])) return '先确认脚本与参考关系';
        if (runs.some(r => ['queued', 'running', 'stopping'].includes(r.status))) return '等待当前生成完成';
        return '';
    }
    function validPosition(value) { return value && Number.isFinite(value.x) && Number.isFinite(value.y) && value.x >= 0 && value.y >= 0 && value.x <= 20000 && value.y <= 20000; }
    function layoutGraph(doc, assets = [], positions = {}) {
        const nodes = [], edges = [], depths = new Map(), lanes = new Map();
        const add = (id, depth, kind, data) => {
            const lane = lanes.get(depth) || 0; lanes.set(depth, lane + 1); depths.set(id, depth);
            const position = validPosition(positions[id]) ? positions[id] : { x: 28 + depth * 302, y: 35 + lane * 255 };
            nodes.push({ id, kind, data, ...position, width: 232, height: 216 });
        };
        const sourceIDs = new Set(doc.asset_ids || []);
        for (const node of doc.plan.nodes || []) {
            if (node.asset_id) sourceIDs.add(node.asset_id);
            for (const ref of node.references || []) if (ref.asset_id) sourceIDs.add(ref.asset_id);
        }
        for (const id of sourceIDs) {
            const asset = assets.find(a => a.id === id) || { id, name: '引用素材（信息加载中）', mime_type: 'image/png' };
            add(`asset:${id}`, 0, 'asset', asset);
        }
        for (const node of doc.plan.nodes || []) {
            const refs = node.references || [], sources = [...(node.depends_on || [])];
            for (const ref of refs) if (ref.asset_id && depths.has(`asset:${ref.asset_id}`)) sources.push(`asset:${ref.asset_id}`);
            if (node.asset_id && depths.has(`asset:${node.asset_id}`)) sources.push(`asset:${node.asset_id}`);
            const depth = sources.length ? 1 + Math.max(...sources.map(id => depths.get(id) || 0)) : (sourceIDs.size ? 1 : 0);
            add(node.id, depth, node.kind, node);
            for (const from of new Set(sources)) {
                const ref = refs.find(r => (r.node_id || `asset:${r.asset_id}`) === from);
                edges.push({ from, to: node.id, label: ref ? roleNames[ref.role] || '参考' : from.startsWith('asset:') ? '复用素材' : '内容依据' });
            }
        }
        return { nodes, edges, width: Math.max(520, ...nodes.map(n => n.x + n.width + 28)), height: Math.max(380, ...nodes.map(n => n.y + n.height + 35)) };
    }
    function movedPosition(origin, dx, dy, zoom) {
        const bounded = value => Math.round(Math.max(0, Math.min(20000, value)) * 100) / 100;
        return { x: bounded(origin.x + dx / zoom), y: bounded(origin.y + dy / zoom) };
    }
    function canvasFit(layout, width, height) {
        return Math.min(1, Math.max(1, width - 24) / layout.width, Math.max(1, height - 24) / layout.height);
    }
    function canvasFocus(node, zoom, width, height) {
        return { left: Math.max(0, (node.x + node.width / 2) * zoom - width / 2), top: Math.max(0, (node.y + node.height / 2) * zoom - height / 2) };
    }
    function unboundShots(doc) {
        const videos = doc.plan.nodes.filter(n => n.kind === 'video');
        if (!videos.length && doc.preferences?.output_kind !== 'video') return [];
        const bound = new Set(videos.flatMap(n => (n.references || []).filter(r => r.shot_ids?.length).map(r => r.node_id)));
        return doc.plan.nodes.filter(n => n.purpose === 'shot_reference' && !bound.has(n.id));
    }
    function revisionSuggestions(node) {
        const common = [
            ['强化人物动机', '让人物的目标、行动原因和前后变化更清楚，用可见行动表达。'],
            ['情绪更有层次', '增强情绪递进与人物反应，为转折和收束留出空间。'],
            ['风格更加统一', '统一视觉媒介、光线、色彩与人物气质，服从已确认的视觉参考。'],
            ['减少信息堆叠', '精简重复描述和次要事件，让核心故事更容易理解。'],
        ];
        const specific = node.purpose === 'brief' ? [
            ['突出故事核心', '聚焦最值得表达的一件事，强化主线、冲突与最终落点。'],
            ['开场更有吸引力', '优化开场的悬念或可见事件，让观众尽快理解看点。'],
            ['更轻松幽默', '通过角色反应与动作设计增加轻松幽默感，保持现有故事主线。'],
            ['更有戏剧张力', '增强目标与阻碍之间的张力，保持角色身份和已确认设定。'],
            ['明确素材分工', '明确每份素材贡献的身份、场景或画风，指出缺口，排除无关角色。'],
            ['结尾更有余韵', '完善结尾的情绪落点或呼应，让主题自然呈现。'],
        ] : node.purpose === 'shot_reference' ? [
            ['站位更清楚', '明确本镜头各人物的站位与视线，保持空间轴线和身份。'],
            ['构图更开阔', '拉开景别，展示指定场景的空间层次，保留关键人物和动作。'],
            ['动作更有张力', '强化本镜头关键姿态和动作可读性，不改变前后因果。'],
            ['加强身份一致性', '逐一对照本镜头人物参考，修正物种、服装与道具，不混入其他角色。'],
            ['环境更贴合', '对照所选场景，修正地形、空间、光线和环境状态。'],
            ['保持前后衔接', '保持相邻镜头的视线、道具持有者和动作结束状态。'],
        ] : node.purpose === 'script' || node.kind === 'video' ? [
            ['节奏更紧凑', '调整各段时间分配，减少铺垫，把时间留给关键动作和结尾。'],
            ['运镜更流畅', '优化景别、摄影机方向与转场接口，保持空间轴线，减少无意义切镜。'],
            ['动作更清楚', '将复杂动作拆成可见的起因、变化与结果，明确道具接触与结束状态。'],
            ['加强角色连续性', '检查身份、服装、道具持有者、数量与站位，使相邻分镜状态衔接。'],
            ['对白更自然', '在保留用户要求原文的前提下优化对白的表演、停顿与时长，避免说不完。'],
            ['声音更有层次', '细化环境声、同步动作音效与配乐的进入、让位和收束，不增加未要求的旁白。'],
        ] : [
            ['主体更突出', '通过主体大小、位置、留白与对比强化视觉焦点。'],
            ['参考图更贴合', '明确参考图需要保留和修改的特征，排除设定图的排版、文字和色板。'],
            ['光影更有氛围', '具体化光源方向、软硬、明暗与色温，保持既定画风。'],
            ['细节更准确', '检查角色外形、服装与道具的形制，减少模糊或冲突描述。'],
            ['构图更简洁', '调整前中后景层次，减少分散注意力的元素。'],
            ['更适合作为参考', '提高角色或场景的识别度与一致性，方便下游视频复用。'],
        ];
        const supplied = (node.revision_suggestions || []).filter(s => typeof s.label === 'string' && s.label.trim() && typeof s.instruction === 'string' && s.instruction.trim()).slice(0, 12);
        const seen = new Set();
        return [...supplied, ...specific.concat(common).map(([label, instruction]) => ({ label, instruction }))]
            .filter(s => !seen.has(s.label) && seen.add(s.label)).slice(0, Math.max(10, supplied.length));
    }
    function refinementMessage(node, choices, custom) {
        const directions = [...choices, custom.trim()].filter(Boolean);
        if (!directions.length) throw new Error('选择一个修改方向，或写下你的想法');
        return `请优化「${node.title}」这个节点，方向如下：\n${directions.map((text, i) => `${i + 1}. ${text}`).join('\n')}\n保留本次调整未涉及的明确要求；仅同步受影响的下游方案，其他节点保持不变。先给我审阅修改结果，不自动生成图片或视频。`;
    }
    function nodeStatus(doc, node, runs) {
        const state = doc.states[node.id] || {}, run = runs.find(r => r.id === state.run_id);
        if (run && ['queued', 'running', 'stopping'].includes(run.status)) return statusNames[run.status];
        if (run?.status === 'completed' && node.kind === 'video') return '已完成';
        if (approved(state)) return state.approved_by === 'agent' ? 'AI 已确认' : '已确认';
        if (run && ['failed', 'interrupted', 'cancelled'].includes(run.status)) return statusNames[run.status];
        if (node.kind === 'image' && !state.selected_asset_id && !state.candidates?.length) return '待生成';
        return '待审阅';
    }
    function renderReferences(doc, node, assets) {
        return (node.references || []).map(ref => {
            const source = ref.node_id ? doc.plan.nodes.find(n => n.id === ref.node_id) : assets.find(a => a.id === ref.asset_id);
            const intervals = (ref.scene_intervals || []).map(span => `${span.start_seconds}–${span.end_seconds} 秒`).join('、');
            const shots = (ref.shot_ids || []).map(id => { const i = (node.shot_ids || []).indexOf(id); return i < 0 ? '待修复的镜头绑定' : `镜头 ${i + 1}`; }).join('、');
            const note = [shots && `用于${shots}`, intervals && `场景时段：${intervals}`, ref.note].filter(Boolean).join(' · ');
            return `<li><span>${esc(source?.title || source?.name || '参考素材')}</span><b>${esc(roleNames[ref.role])}</b><small>${esc(note)}</small></li>`;
        }).join('');
    }
    function shotCards(doc, node) {
        if (node.kind !== 'video') return [];
        return (node.references || []).flatMap(ref => {
            const source = doc.plan.nodes.find(n => n.id === ref.node_id && n.purpose === 'shot_reference');
            if (!source) return [];
            const state = doc.states[source.id] || {}, assetID = state.selected_asset_id || source.asset_id || '';
            return (ref.shot_ids || []).map(id => {
                const index = (node.shot_ids || []).indexOf(id), shots = node.storyboard?.shots || [];
                if (index < 0 || !shots[index]) return null;
                return { nodeID: source.id, title: source.title, index: index + 1, start: shots[index].start_seconds,
                    end: shots[index+1]?.start_seconds ?? node.duration_seconds, assetID, approved: approved(state) };
            }).filter(Boolean);
        }).sort((a,b) => a.index - b.index);
    }
    function renderShotStrip(doc, node, mediaURL) {
        const cards = shotCards(doc,node);
        if (!cards.length) return '';
        return `<section class="cp-shot-board"><h4>关键分镜图</h4><div>${cards.map(card => `<article>
            ${card.assetID ? Library.media(card.assetID,card.title,false,mediaURL) : '<div class="cp-shot-empty">待准备画面</div>'}
            <button type="button" data-cp-action="select" data-id="${esc(card.nodeID)}"><strong>镜头 ${card.index} · ${esc(card.title)}</strong><small>${esc(card.start)}–${esc(card.end)} 秒 · ${!card.assetID ? '待生成' : card.approved ? '已确认' : '待审阅'}</small></button>
        </article>`).join('')}</div></section>`;
    }
    // Restore positions immediately; smooth scrolling would replay on every DOM refresh.
    function captureReadingPosition(root) {
        const messages = root?.querySelector('.cp-messages'), ancestors = [];
        for (let parent = root?.parentElement; parent; parent = parent.parentElement) {
            ancestors.push({ element: parent, top: parent.scrollTop, left: parent.scrollLeft });
        }
        const main = root?.querySelector('.cp-main');
        return { top: messages?.scrollTop || 0, follow: !messages || messages.scrollHeight - messages.clientHeight - messages.scrollTop <= 2, mainTop: main?.scrollTop || 0, ancestors };
    }
    function restoreReadingPosition(root, position, force = false) {
        const messages = root?.querySelector('.cp-messages');
        if (messages) {
            const top = force || position.follow ? Math.max(0, messages.scrollHeight - messages.clientHeight) : position.top;
            if (messages.scrollTop !== top) messages.scrollTop = top;
        }
        const main = root?.querySelector('.cp-main');
        if (main && main.scrollTop !== position.mainTop) main.scrollTop = position.mainTop || 0;
        for (const saved of position.ancestors) {
            if (saved.element.scrollTop !== saved.top) saved.element.scrollTop = saved.top;
            if (saved.element.scrollLeft !== saved.left) saved.element.scrollLeft = saved.left;
        }
    }
    function planningDuration(activity, now = Date.now()) {
        const elapsed = activity.status === 'running' ? Math.max(activity.elapsed_ms || 0, now - Date.parse(activity.started_at) || 0) : activity.elapsed_ms || 0;
        const seconds = Math.max(0, Math.floor(elapsed / 1000));
        return { seconds, label: seconds >= 60 ? `${Math.floor(seconds / 60)}分${seconds % 60}秒` : `${seconds}秒` };
    }
    function mediaElapsed(run, now = Date.now()) {
        return Number.isFinite(Date.parse(run.created_at)) ? `已等待 ${planningDuration({ status: 'running', started_at: run.created_at }, now).label}` : '';
    }
    function renderMediaProgress(run, now = Date.now()) {
        if (!run || !['queued', 'running', 'stopping'].includes(run.status)) return '';
        return `<div class="cp-media-progress" data-cp-media-run="${esc(run.id)}"><div><strong>${esc(statusNames[run.status])}</strong><time>${mediaElapsed(run, now)}</time></div><p>${run.status === 'stopping' ? '已请求停止，当前提交会先完成并保存。' : '可以离开此页，任务会继续。完成后结果会自动归入画布与资产。'}</p></div>`;
    }
    const planningSteps = activity => (activity.steps || []).filter(step => !['failed', 'interrupted'].includes(step.stage)).map(step => `<li><span>${esc(step.message)}</span><small>${Math.floor((step.elapsed_ms || 0) / 1000)}s</small></li>`).join('');
    const planningLive = (activity, seconds) => `${activity.output_chars ? `正在接收方案 · 已收到 ${Number(activity.output_chars)} 字符` : '请求已提交，等待模型返回内容…'}${seconds >= 25 ? '<span>仍在处理中，可以先离开此页，返回后继续查看。</span>' : ''}`;
    function renderPlanning(activity, openOverride, now = Date.now()) {
        if (!activity) return '';
        const running = activity.status === 'running', failed = ['failed', 'interrupted'].includes(activity.status);
        const { seconds, label: duration } = planningDuration(activity, now);
        const title = running ? '正在思考与规划' : failed ? '本次规划未完成' : '思考与规划已完成';
        const key = `${activity.id}:${activity.status}`;
        return `<details class="cp-planning ${running ? 'is-running' : failed ? 'is-failed' : 'is-complete'}" data-cp-planning="${esc(key)}" ${openOverride ?? (running || failed) ? 'open' : ''}>
            <summary><span class="cp-planning-indicator" aria-hidden="true"></span><strong>${title}</strong><time>${duration}</time><span class="cp-planning-chevron" aria-hidden="true">⌄</span></summary>
            <div class="cp-planning-body"><ol data-cp-plan-steps>${planningSteps(activity)}</ol>
            ${running ? `<p class="cp-planning-live" role="status" data-cp-plan-live>${planningLive(activity, seconds)}</p>` : ''}</div></details>`;
    }
    function conversationRounds(doc) {
        const rounds = [];
        for (const [index, message] of (doc.messages || []).entries()) {
            if (message.role === 'user' || !rounds.length) rounds.push({ id: `turn-${index}`, nodeID: message.node_id || '', messages: [] });
            const round = rounds[rounds.length - 1];
            round.messages.push(message);
            if (message.planning) round.activity = message.planning;
        }
        if (doc.planning) {
            if (!rounds.length) rounds.push({ id: 'turn-0', nodeID: '', messages: [] });
            rounds[rounds.length - 1].active = doc.planning;
        }
        return rounds;
    }
    function normalizePreferences(value = {}) {
        return { output_kind: ['image', 'video'].includes(value?.output_kind) ? value.output_kind : '', aspect_ratio: ['1:1', '16:9', '9:16'].includes(value?.aspect_ratio) ? value.aspect_ratio : '' };
    }
    function preferenceSummary(value) {
        const p = normalizePreferences(value);
        return [p.output_kind === 'image' ? '图片' : p.output_kind === 'video' ? '视频' : '', p.aspect_ratio].filter(Boolean).join(' · ') || '创作选项';
    }
    function renderDecisions(project, busy = false) {
        const questions = documentOf(project).plan.questions || [];
        if (!questions.length || project?.planning || project?.error || automaticActive(project)) return '';
        return `<section class="cp-decisions" aria-label="等待你的判断"><header><span>下一步</span><strong>需要你来定</strong></header>${questions.map((q, i) => `<fieldset><legend>${esc(q.question)}</legend><div>${q.options.map((option, j) => `<button type="button" data-cp-action="answer" data-id="${i}:${j}" ${busy ? 'disabled' : ''}><span>${esc(option)}</span>${j === 0 && !option.includes('推荐') ? '<small>推荐</small>' : ''}</button>`).join('')}</div></fieldset>`).join('')}<p>选择一个方向，或在下方输入你的想法。</p></section>`;
    }
    function createController({ api, user, mediaURL, confirm = async () => false, onAssets = () => {}, onTemplates = () => {} }) {
        let element = null, visible = false, timer = null, epoch = 0, viewEpoch = 0, busy = false;
        let projectsView = true, projectSearch = '', renameID = '', renameValue = '', openRequest = 0;
        let projects = [], project = null, assets = [], runs = [], selected = '', draft = '', attachments = [], feedback = '', picker = false, versions = null, editing = false, editText = '';
        let zoom = 1, autoFit = true, pan = null, dragging = null, renderPending = false, suppressClick = null;
        let fullscreen = false, fullscreenReview = false, normalCanvas = null;
        const fullscreenEscape = event => {
            if (fullscreen && event.key === 'Escape') { event.preventDefault(); toggleFullscreen(false); }
        };
        function focusCanvasNode(id) {
            const node = canvasLayout().nodes.find(n => n.id === id), view = element?.querySelector('[data-cp-viewport]');
            if (!node || !view) return;
            zoom = Math.max(.75, zoom); autoFit = false; drawCanvas();
            const pos = canvasFocus(node, zoom, view.clientWidth, view.clientHeight);
            view.scrollLeft = pos.left; view.scrollTop = pos.top;
        }
        function toggleFullscreen(value = !fullscreen) {
            if (value === fullscreen) return;
            const view = element?.querySelector('[data-cp-viewport]');
            if (value) normalCanvas = { zoom, x: view?.scrollLeft || 0, y: view?.scrollTop || 0 };
            fullscreen = value; fullscreenReview = false;
            if (typeof document !== 'undefined') {
                document.removeEventListener('keydown', fullscreenEscape);
                if (value) document.addEventListener('keydown', fullscreenEscape);
            }
            if (!value && normalCanvas) zoom = normalCanvas.zoom;
            render();
            const next = element?.querySelector('[data-cp-viewport]');
            if (!value && next && normalCanvas) { next.scrollLeft = normalCanvas.x; next.scrollTop = normalCanvas.y; }
            element?.querySelector('[data-cp-action="fullscreen"]')?.focus({ preventScroll: true });
        }
        const canvasStates = new Map(), refinementDrafts = new Map();
        const preferenceDrafts = new Map();
        let optionsOpen = false;
        const requestKeys = new Map(), planningOpen = new Map(), roundsOpen = new Map();
        let pendingMessage = null, followMessages = false, pollError = '';
        const assetPicker = Library.createController({api,user,mediaURL,onAttach: async chosen => {
            attachments=[...new Set([...attachments,...chosen.map(a=>a.id)])];
            assets=[...assets.filter(a=>!chosen.some(b=>b.id===a.id)),...chosen];picker=false;render();
        }});
        const currentDoc = () => documentOf(project);
        const currentPreferences = () => preferenceDrafts.get(project?.id || '') || normalizePreferences(currentDoc().preferences);
        const preferencesChanged = () => JSON.stringify(currentPreferences()) !== JSON.stringify(normalizePreferences(currentDoc().preferences));
        function renderComposerOptions() {
            const p = currentPreferences(), disabled = busy || project?.planning || automaticActive(project);
            return `<details class="cp-composer-settings" data-cp-options ${optionsOpen ? 'open' : ''}><summary aria-label="创作选项：${esc(preferenceSummary(p))}">${esc(preferenceSummary(p))}<span aria-hidden="true">⌄</span></summary><div class="cp-composer-panel"><label>创作目标<select data-cp-preference="output_kind" aria-label="创作目标" ${disabled ? 'disabled' : ''}>${[['', '交给 AI 判断'], ['image', '图片'], ['video', '视频']].map(([value, title]) => `<option value="${value}" ${p.output_kind === value ? 'selected' : ''}>${title}</option>`).join('')}</select></label><label>画面比例<select data-cp-preference="aspect_ratio" aria-label="画面比例" ${disabled ? 'disabled' : ''}>${[['', '交给 AI 判断'], ['16:9', '16:9 · 横屏'], ['9:16', '9:16 · 竖屏'], ['1:1', '1:1 · 方形']].map(([value, title]) => `<option value="${value}" ${p.aspect_ratio === value ? 'selected' : ''}>${title}</option>`).join('')}</select></label><p>随下一条消息应用，其他细节交给 AI。</p></div></details>`;
        }
        function canvasState() {
            const id = project?.id || '';
            if (!canvasStates.has(id)) canvasStates.set(id, { positions: parse(project?.canvas_layout, {}), revision: project?.layout_revision || 0, change: 0, pending: 0, failed: false, queue: Promise.resolve() });
            const state = canvasStates.get(id);
            if (!state.pending && (project?.layout_revision || 0) > state.revision) {
                state.positions = parse(project.canvas_layout, {}); state.revision = project.layout_revision;
            }
            return state;
        }
        const canvasLayout = () => layoutGraph(currentDoc(), assets, canvasState().positions);
        function refinementDraft(nodeID = selected) {
            const key = `${project?.id}:${nodeID}`;
            if (!refinementDrafts.has(key)) refinementDrafts.set(key, { choices: new Set(), custom: '', expanded: false });
            return refinementDrafts.get(key);
        }
        function saveLayout(positions, reset = false) {
            if (!project) return;
            const state = canvasState(), id = project.id, owner = epoch, change = ++state.change;
            state.positions = reset ? {} : { ...state.positions, ...positions }; state.pending++;
            const snapshot = { ...state.positions };
            state.queue = state.queue.then(async () => {
                if (owner !== epoch) return;
                try {
                    const body = reset ? { reset: true } : { positions: state.failed ? snapshot : positions };
                    const response = await api('PATCH', `/api/creation/projects/${encodeURIComponent(id)}/layout`, body);
                    if (owner !== epoch) return;
                    state.revision = Math.max(state.revision, response.layout_revision || 0);
                    if (change === state.change) { state.positions = parse(response.canvas_layout, state.positions); state.failed = false; }
                } catch (_) { if (owner === epoch) state.failed = true; }
                finally {
                    state.pending--;
                    if (owner === epoch && id === project?.id) updateLayoutStatus();
                }
            });
            updateLayoutStatus();
        }
        function updateLayoutStatus() {
            const state = canvasState(), label = element?.querySelector('[data-cp-layout-status]');
            if (label) label.textContent = state.pending ? '正在保存位置…' : state.failed ? '位置未保存，请重试' : '拖动节点排布 · 拖动空白处浏览';
            const retry = element?.querySelector('[data-cp-action="retry-layout"]'); if (retry) retry.hidden = !state.failed;
        }
        const button = (action, label, { id = '', primary = false, disabled = false, asset = '' } = {}) => `<button type="button" class="${primary ? 'btn-primary' : 'btn-secondary'}" data-cp-action="${action}" data-id="${esc(id)}" data-asset="${esc(asset)}" ${disabled || busy || project?.planning || (automaticActive(project) && !['automatic-stop','versions','new','select','assets','close-versions'].includes(action)) ? 'disabled' : ''}>${esc(label)}</button>`;
        function mount(target) { element = target; if (target) { Library.bindMedia(target); bind(); render(); } }
        function reset() { if (typeof document !== 'undefined') document.removeEventListener('keydown', fullscreenEscape); fullscreen = false; fullscreenReview = false; normalCanvas = null; assetPicker.reset(); projectsView = true; projectSearch = ''; renameID = ''; openRequest++; epoch++; viewEpoch++; visible = false; clearTimeout(timer); timer = null; project = null; projects = []; assets = []; runs = []; selected = ''; draft = ''; attachments = []; feedback = ''; picker = false; busy = false; versions = null; requestKeys.clear(); planningOpen.clear(); roundsOpen.clear(); preferenceDrafts.clear(); optionsOpen = false; canvasStates.clear(); refinementDrafts.clear(); dragging = null; pan = null; renderPending = false; suppressClick = null; pendingMessage = null; followMessages = false; pollError = '';  if (element) element.innerHTML = ''; }
        function setVisible(value) { if (!value && fullscreen) toggleFullscreen(false); visible = value; viewEpoch++; clearTimeout(timer); if (value) { render(); void poll(viewEpoch); } }
        async function poll(version) {
            if (!visible || version !== viewEpoch) return;
            try { await refresh(); } catch (error) { if (version === viewEpoch) { pollError = error.message; showMessage(pollError); } }
            if (visible && version === viewEpoch) timer = setTimeout(() => poll(version), project?.planning || automaticActive(project) || runs.some(r => ['queued', 'running'].includes(r.status)) ? 2200 : 6000);
        }
        async function refresh() {
            if (!user()) return;
            const owner = epoch, id = project?.id, opening = openRequest;
            if(projectsView || !id) {
                const p=await api('GET','/api/creation/projects');if(owner!==epoch||opening!==openRequest)return;
                const changed=JSON.stringify(projects)!==JSON.stringify(p.projects||[]);projects=p.projects||[];
                if(pollError){if(feedback===pollError)showMessage('');pollError='';}
                if(changed)render();return;
            }
            const [detail,r]=await Promise.all([api('GET',`/api/creation/projects/${encodeURIComponent(id)}`),api('GET',`/api/creation/runs?project_id=${encodeURIComponent(id)}`)]);
            if(owner!==epoch||opening!==openRequest||id!==project?.id)return;
            if (pollError) { if (feedback === pollError) showMessage(''); pollError = ''; }
            const before=JSON.stringify([project,assets,runs]),previousLayout=layoutState();
            if(detail?.project && detail.project.revision>=project.revision)project=detail.project;
            runs=r.runs||[];
            if(before!==JSON.stringify([project,assets,runs])||project?.planning){if(previousLayout!==layoutState()||!updatePlanningProgress())render();}
            const doc=currentDoc(),ids=new Set([...doc.asset_ids,...attachments]);
            for(const n of doc.plan.nodes){if(n.asset_id)ids.add(n.asset_id);for(const ref of n.references||[])if(ref.asset_id)ids.add(ref.asset_id);}
            for(const state of Object.values(doc.states)){if(state.selected_asset_id)ids.add(state.selected_asset_id);for(const a of state.candidates||[])ids.add(a);}
            for(const run of runs)for(const step of parse(run.progress,[]))for(const a of step.asset_ids||[])ids.add(a);
            const missing=[...ids].filter(a=>!assets.some(existing=>existing.id===a));
            if(missing.length){
                const responses=await Promise.all(Array.from({length:Math.ceil(missing.length/100)},(_,i)=>api('GET',`/api/creation/assets?ids=${encodeURIComponent(missing.slice(i*100,i*100+100).join(','))}`)));
                if(owner!==epoch||opening!==openRequest||id!==project?.id)return;
                const added=responses.flatMap(a=>a.assets||[]);if(added.length){assets=[...assets,...added];render();}
            }
            // The media service may return unchanged status for minutes; tick text only.
            for (const target of element?.querySelectorAll?.('[data-cp-media-run]') || []) {
                const run = runs.find(r => r.id === target.dataset.cpMediaRun), time = target.querySelector('time');
                if (run && time) { const label = mediaElapsed(run); if (time.textContent !== label) time.textContent = label; }
            }
        }
        function layoutState() {
            const { planning, ...doc } = currentDoc();
            return JSON.stringify([project?.id, project?.name, project?.planning, project?.error, doc, projects.map(p => [p.id, p.name]), assets, runs]);
        }
        function updatePlanningProgress() {
            const activity = currentDoc().planning, target = element?.querySelector('[data-cp-active-planning]');
            const details = target?.querySelector('details');
            if (!project?.planning || !activity || !details || details.dataset.cpPlanning !== `${activity.id}:running`) return false;
            const reading = captureReadingPosition(element), { seconds, label } = planningDuration(activity);
            const time = target.querySelector('time'); if (time && time.textContent !== label) time.textContent = label;
            for (const [selector, html] of [['[data-cp-plan-steps]', planningSteps(activity)], ['[data-cp-plan-live]', planningLive(activity, seconds)]]) {
                const part = target.querySelector(selector); if (part && part.innerHTML !== html) part.innerHTML = html;
            }
            const version = element.querySelector('.cp-version'); if (version) version.textContent = `v${project.revision} · 正在规划`;
            restoreReadingPosition(element, reading);
            return true;
        }
        function showMessage(text) { feedback = text; const target = element?.querySelector('[data-cp-feedback]'); if (target) target.textContent = text; }
        function selectDefault() { const doc = currentDoc(); if (!doc.plan.nodes.some(n => n.id === selected) && !selected.startsWith('asset:')) selected = doc.plan.nodes.find(n => !approved(doc.states[n.id]))?.id || doc.plan.nodes[0]?.id || ''; }
        function render() {
            if (!element) return;
            if (dragging || pan) { renderPending = true; return; }
            renderPending = false;
            selectDefault();
            if(projectsView){if (typeof document !== 'undefined') document.removeEventListener('keydown', fullscreenEscape); fullscreen = false; fullscreenReview = false; renderProjectLibrary();return;}
            const doc = currentDoc(), focused = typeof document !== 'undefined' && element.contains?.(document.activeElement) ? document.activeElement : null;
            const preferenceFocus = focused?.dataset?.cpPreference;
            const focusKind = focused?.hasAttribute('data-cp-draft') ? 'draft' : focused?.hasAttribute('data-cp-edit') ? 'edit' : focused?.hasAttribute('data-cp-refine') ? 'refine' : '';
            const start = focused?.selectionStart, end = focused?.selectionEnd;
            const viewport = element.querySelector('[data-cp-viewport]'), scroll = viewport ? { x: viewport.scrollLeft, y: viewport.scrollTop } : null;
            const reading = captureReadingPosition(element);
            element.querySelectorAll?.('[data-cp-planning]').forEach(details => planningOpen.set(details.dataset.cpPlanning, details.open));
            element.innerHTML = `<section class="cp-project"><header class="cp-project-head"><div><button type="button" class="creation-text-button" data-cp-action="project-list">← 项目列表</button><strong class="cp-project-name">${esc(project?.name || '新的创作')}</strong>${project ? `<span class="cp-version">v${project.revision} · ${automaticActive(project) ? '一键生成中' : project.planning ? '正在规划' : '自动保存'}</span>` : ''}</div><div>${project ? `<div class="cp-auto-controls">${automaticActive(project) ? button('automatic-stop', project.automatic_status === 'stopping' ? '正在停止…' : '停止一键生成', { disabled: project.automatic_status === 'stopping' }) : button('automatic-start', ['failed','interrupted','cancelled'].includes(project.automatic_status) ? '继续一键生成' : '一键生成', { primary: true, disabled: !!automaticBlock(project, runs) })}<small>保留已确认内容，AI 确定其余节点并生成</small></div>` + button('project-assets', '项目资产') + button('rename-project', '重命名', {id:project.id}) + button('delete-project', '删除项目', {id:project.id}) + button('versions', '历史方案') + button('save-template', '存为模板', { disabled: !doc.plan.nodes.length }) : ''}${button('new', '＋ 新创作')}</div></header>
            <div class="cp-workspace ${doc.plan.nodes.length ? '' : 'cp-start'}"><aside class="cp-dialogue"><header><strong>创作进程</strong><span>${project?.planning ? '正在整理方案…' : '想法与画布同步'}</span></header><div class="cp-messages" aria-live="polite">${renderConversation(doc)}${renderAutomatic(project, planningOpen.get(`auto:${doc.automation?.id}`) ?? true)}${renderDecisions(project, busy)}</div>
            <form class="cp-compose" data-cp-form><label for="cp-draft">${doc.plan.questions?.length ? '回复创作助手' : selected && !selected.startsWith('asset:') ? `针对：${esc(doc.plan.nodes.find(n => n.id === selected)?.title || '整个项目')}` : '描述你的创作想法'}</label>${attachments.length ? `<div class="cp-attachments">${attachments.map(id => `<button type="button" data-cp-action="detach" data-id="${esc(id)}">${esc(assets.find(a => a.id === id)?.name || '素材')} ×</button>`).join('')}</div>` : ''}<textarea id="cp-draft" data-cp-draft rows="4" maxlength="8000" placeholder="例如：用这几个人设做一支水墨武侠短片，最后有一点反转…" ${project?.planning || automaticActive(project) ? 'disabled' : ''}>${esc(draft)}</textarea><footer><div>${renderComposerOptions()}${button('upload', '＋ 上传')}${button('pick', '引用资产')}</div><button type="submit" class="btn-primary" ${busy || project?.planning || automaticActive(project) ? 'disabled' : ''}>${pendingMessage ? '发送中…' : project?.planning ? '规划中…' : '发送'}</button></footer><input type="file" data-cp-upload multiple accept="image/png,image/jpeg,image/webp,video/mp4,video/webm" hidden></form><p class="cp-feedback" role="status" data-cp-feedback>${esc(feedback || '')}</p></aside>
            <main class="cp-main${fullscreen ? ' is-canvas-fullscreen' : ''}${fullscreenReview ? ' is-review-open' : ''}">${doc.plan.nodes.length ? `<div class="cp-canvas-head"><div><strong>创作画布</strong><span>${doc.plan.nodes.length} 个节点 · ${doc.plan.nodes.filter(n => n.purpose === 'shot_reference').length} 张分镜 · ${doc.plan.nodes.filter(n => n.kind === 'video').length} 个视频</span></div><div><button data-cp-action="zoom-out" aria-label="缩小画布">−</button><span data-cp-zoom>${Math.round(zoom * 100)}%</span><button data-cp-action="zoom-in" aria-label="放大画布">＋</button><button data-cp-action="fit">查看全图</button><button data-cp-action="locate-selected">定位选中</button><button data-cp-action="arrange">自动排列</button><button type="button" data-cp-action="fullscreen" aria-pressed="${fullscreen}">${fullscreen ? '退出全屏 · Esc' : '全屏画布'}</button>${fullscreen ? `<button type="button" data-cp-action="canvas-review" aria-pressed="${fullscreenReview}">${fullscreenReview ? '收起审阅' : '查看审阅'}</button>` : ''}</div></div><div class="cp-canvas-help"><select data-cp-locate aria-label="定位画布节点"><option value="">定位节点…</option>${doc.plan.nodes.map(n => `<option value="${esc(n.id)}">${n.purpose === 'shot_reference' ? '分镜图 · ' : n.kind === 'video' ? '视频 · ' : ''}${esc(n.title)}</option>`).join('')}</select>${unboundShots(doc).length ? `<span class="cp-binding-warning">${unboundShots(doc).length} 张分镜图尚未连接到视频 ${button('connect-shots', '补齐视频依赖')}</span>` : ''}<span data-cp-layout-status role="status"></span><button type="button" class="creation-text-button" data-cp-action="retry-layout" hidden>重试保存位置</button></div><div class="cp-viewport" data-cp-viewport aria-label="创作画布，可拖动节点调整位置，拖动空白区域或滚动查看"><div class="cp-canvas-space" data-cp-space><div class="cp-graph" data-cp-graph></div></div></div><section class="cp-review" aria-label="节点审阅">${renderReview(doc)}</section>` : `<div class="cp-empty-canvas"><span>素材 → 方案 → 作品</span><h3>你的创作，会在这里展开</h3><p>对话后，人物参考、主视觉、脚本和作品会成为可查看、可修改的节点。</p><p>图片与视频生成都由你明确提交，确认前可以继续调整。</p></div>`}<div class="cp-project-extras">${picker ? '<section class="cp-picker"><header><h3>引用已有资产</h3><button data-cp-action="close-picker">关闭</button></header><div data-cp-asset-picker></div></section>' : ''}${versions ? renderVersions() : ''}${renderHistory()}</div></main></div></section>`;
            if(picker)assetPicker.mount(element.querySelector('[data-cp-asset-picker]'));
            const fitted = autoFit;
            drawCanvas(); updateLayoutStatus();
            if (scroll && !fitted) { const v = element.querySelector('[data-cp-viewport]'); if (v) { v.scrollLeft = scroll.x; v.scrollTop = scroll.y; } }
            if (focusKind) { const target = element.querySelector(`[data-cp-${focusKind}]`); target?.focus({ preventScroll: true }); target?.setSelectionRange(start, end); }
            if (preferenceFocus) element.querySelector(`[data-cp-preference="${preferenceFocus}"]`)?.focus({ preventScroll: true });
            restoreReadingPosition(element, reading, followMessages);
            followMessages = false;
        }
        function projectCards() {
            return projects.filter(p=>p.name.toLowerCase().includes(projectSearch.toLowerCase())).map(p=>`<article class="cp-project-card"><button type="button" class="cp-project-open" data-cp-action="open-project" data-id="${esc(p.id)}"><span class="cp-card-symbol" aria-hidden="true">◈</span><strong>${esc(p.name)}</strong><small>${p.planning?'正在规划':automaticActive(p)?'一键生成中':p.error?'需要处理':'创作项目'} · ${esc(new Date(p.updated_at||p.created_at).toLocaleDateString())}</small><span>进入创作 →</span></button><footer>${renameID===p.id?`<input data-cp-rename aria-label="项目新名称" maxlength="100" value="${esc(renameValue)}"><button data-cp-action="save-rename" data-id="${esc(p.id)}">保存</button><button data-cp-action="cancel-rename">取消</button>`:`<button data-cp-action="rename-project" data-id="${esc(p.id)}">重命名</button><button data-cp-action="delete-project" data-id="${esc(p.id)}">删除</button>`}</footer></article>`).join('')||'<p class="creation-empty">暂无匹配项目，可以新建一个创作。</p>';
        }
        function renderProjectLibrary(){
            const focus=element.ownerDocument?.activeElement,kind=focus?.hasAttribute?.('data-cp-rename')?'rename':focus?.hasAttribute?.('data-cp-search')?'search':'',start=focus?.selectionStart;
            element.innerHTML=`<section class="cp-project-library"><header><div><h3>我的创作项目</h3><p>从想法到作品，每个项目都有独立的画布与资产文件夹。</p></div><button class="btn-primary" data-cp-action="new">＋ 新创作</button></header><input type="search" data-cp-search aria-label="搜索创作项目" placeholder="搜索项目名称" value="${esc(projectSearch)}"><p class="cp-feedback" data-cp-feedback role="status">${esc(feedback)}</p><div class="cp-project-grid">${projectCards()}</div></section>`;
            if(kind){const target=element.querySelector(`[data-cp-${kind}]`);target?.focus({preventScroll:true});target?.setSelectionRange(start,start);}
        }
        function renderConversation(doc) {
            const rounds = conversationRounds(doc);
            const planningHTML = activity => renderPlanning(activity, planningOpen.get(`${activity?.id}:${activity?.status}`));
            const history = rounds.map((round, index) => {
                const latest = index === rounds.length - 1, key = `${project?.id}:${round.id}`;
                const title = doc.plan.nodes.find(n => n.id === round.nodeID)?.title || (round.nodeID ? '已移除节点' : '整体创作');
                const activity = round.active || round.activity;
                const failed = ['failed', 'interrupted'].includes(activity?.status) || latest && project?.error && !project.planning;
                const status = latest && project?.planning ? '正在规划' : failed ? '未完成' : activity ? '已完成' : '对话';
                const prompt = round.messages.find(m => m.role === 'user')?.content || '创作规划';
                let errorShown = false;
                const body = round.messages.map(message => {
                    const error = ['failed', 'interrupted'].includes(message.planning?.status) || latest && message.role === 'assistant' && message.content === project?.error;
                    errorShown ||= error;
                    return `<article class="cp-message ${message.role === 'user' ? 'cp-user' : 'cp-assistant'}"><small>${message.role === 'user' ? '你' : '创作助手'}</small>${planningHTML(message.planning)}<div ${error ? 'class="cp-round-error" role="alert"' : ''}>${esc(message.content)}</div>${message.asset_ids?.length ? `<span class="cp-message-assets">${message.asset_ids.map(id => esc(assets.find(a => a.id === id)?.name || '素材')).join(' · ')}</span>` : ''}</article>`;
                }).join('');
                return `<details class="cp-round" data-cp-turn="${esc(key)}" ${roundsOpen.get(key) ?? latest ? 'open' : ''}><summary><span><strong>${esc(title)}</strong><small>第 ${index + 1} 轮 · ${status}</small><span class="cp-round-preview">${esc(prompt.slice(0, 72))}</span></span><span aria-hidden="true">⌄</span></summary><div class="cp-round-body">${body}${round.active ? `<div data-cp-active-planning>${planningHTML({ ...round.active, status: project?.planning ? 'running' : 'interrupted' })}</div>` : ''}${latest && project?.error && !project.planning ? `${!errorShown ? `<p class="cp-round-error" role="alert">${esc(project.error)}</p>` : ''}${button('retry-plan', '重试这次规划')}` : ''}</div></details>`;
            }).join('');
            if (history || pendingMessage) return history + (pendingMessage ? `<article class="cp-message cp-user"><small>你 · 发送中</small><div>${esc(pendingMessage)}</div></article><p class="cp-thinking" role="status">正在提交创作想法…</p>` : '');
            if (project?.error) return `<p class="cp-round-error" role="alert">${esc(project.error)}</p>`;
            return `<div class="cp-welcome"><span>从一个想法开始</span><h3>这次，想创作什么？</h3><p>说说故事、画面或想实现的效果。提供已有素材，创作助手会安排步骤，并把需要你审阅的内容放到画布。</p><div>${button('example-video', '用角色素材创作一支短片')}${button('example-image', '创作一组产品场景图')}</div></div>`;
        }
        function renderReview(doc) {
            if (selected.startsWith('asset:')) {
                const asset = assets.find(a => `asset:${a.id}` === selected);
                return asset ? `<header><h3>${esc(asset.name)}</h3><span>原始素材</span></header>${asset.mime_type.startsWith('video/') ? `${Library.media(asset.id,asset.name,true,mediaURL)}<p>视频可作为项目资产保存；当前生成服务不支持视频参考输入。</p>` : Library.media(asset.id,asset.name,false,mediaURL)}<p>原文件保存在网盘「资产」中。</p>` : '';
            }
            const node = doc.plan.nodes.find(n => n.id === selected); if (!node) return '';
            const state = doc.states[node.id] || {}, blocked = generationBlock(project, node, runs), upstreamReady = dependenciesReady(doc, node);
            const candidates = [...new Set([node.asset_id, ...(state.candidates || [])].filter(Boolean))];
            const run = runs.find(r => r.id === state.run_id);
            const buttons = node.kind === 'text' ? button('approve', approved(state) ? '已确认 · 再次确认' : '确认这份内容', { id: node.id, primary: true, disabled: !upstreamReady }) : node.kind === 'video' ? `${button('approve', approved(state) ? '方案已确认' : '确认脚本与参考关系', { id: node.id, disabled: !upstreamReady })}${button('generate', '确认生成视频', { id: node.id, primary: true, disabled: !!blocked })}` : !node.asset_id ? button('generate', `${state.candidates?.length ? '再生成' : '生成'} ${node.count} 张${node.purpose === 'output' ? '图片' : '候选'}`, { id: node.id, primary: true, disabled: !!blocked }) : '';
            return `<header><div><h3>${esc(node.title)}</h3><span>版本 ${state.revision || 1} · ${esc(nodeStatus(doc, node, runs))}</span></div>${button('edit', editing ? '收起编辑' : '手动编辑', { id: node.id })}</header>
            ${renderRefinements(node)}
            ${renderMediaProgress(run)}
            ${renderShotStrip(doc, node, mediaURL)}
            ${editing ? `<label class="cp-edit-label">修改后交给创作助手同步相关节点<textarea data-cp-edit rows="8" maxlength="7000">${esc(editText)}</textarea></label>${button('save-edit', '更新此节点及相关方案', { id: node.id, primary: true })}` : `<div class="cp-review-text">${esc(node.content)}</div>`}
            ${candidates.length ? `<div class="cp-candidates">${candidates.map((id, i) => node.kind === 'video' ? `<article>${Library.media(id,node.title,true,mediaURL)}<a href="${esc(mediaURL(id))}" target="_blank" rel="noopener">打开视频</a></article>` : `<article class="${state.selected_asset_id === id && approved(state) ? 'is-chosen' : ''}">${Library.media(id,`${node.title} · 候选 ${i + 1}`,false,mediaURL)}${button('choose', state.selected_asset_id === id && approved(state) ? '已选用 · 再次确认' : `选用候选 ${i + 1} 并确认`, { id: node.id, asset: id, disabled: !upstreamReady })}</article>`).join('')}</div>` : ''}
            ${node.references?.length ? `<div class="cp-reference-review"><h4>参考素材的用途</h4><ul>${renderReferences(doc, node, assets)}</ul></div>` : ''}
            ${node.depends_on?.length ? `<p class="cp-dependencies">内容依据：${node.depends_on.map(id => esc(doc.plan.nodes.find(n => n.id === id)?.title || id)).join('、')}</p>` : ''}
            ${node.kind !== 'text' ? `<details class="cp-technical"><summary>查看生成方案与参数</summary><p>${esc(node.aspect_ratio)}${node.kind === 'video' ? ` · ${node.duration_seconds} 秒 · 分镜 skill` : ` · ${node.count} 张`} · 当前已配置的 Spark 生成服务</p><pre>${esc(node.prompt)}</pre></details><p class="cp-cost">本次提交${node.kind === 'video' ? ` 1 个 ${node.duration_seconds} 秒视频` : ` ${node.count} 张图片`}；费用与完成时间以生成服务为准。</p>` : ''}
            ${run?.error ? `<p class="cp-error">${esc(run.error)}</p>` : ''}<footer class="cp-review-actions"><span>${esc(blocked || (node.kind === 'video' ? '提交时固定本次脚本与素材版本' : '确认后可继续下游创作'))}</span><div>${buttons}</div></footer>`;
        }
        function renderRefinements(node) {
            const suggestions = revisionSuggestions(node), state = refinementDraft(node.id), disabled = busy || project?.planning;
            return `<section class="cp-refinements" aria-label="AI 修改方向"><header><div><h4>想往哪个方向调整？</h4><p>可以多选，也可以直接写下你的想法。</p></div><span>${state.choices.size ? `已选 ${state.choices.size} 项` : '让 AI 帮你改'}</span></header>
            <div class="cp-refinement-options">${suggestions.slice(0, state.expanded ? suggestions.length : 6).map((suggestion, i) => `<button type="button" data-cp-action="refine-choice" data-id="${i}" aria-pressed="${state.choices.has(suggestion.instruction)}" ${disabled ? 'disabled' : ''}><strong>${esc(suggestion.label)}</strong><small>${esc(suggestion.instruction)}</small></button>`).join('')}</div>
            ${suggestions.length > 6 ? `<button type="button" class="creation-text-button" data-cp-action="refine-more" aria-expanded="${state.expanded}" ${disabled ? 'disabled' : ''}>${state.expanded ? '收起更多方向' : `更多修改方向（${suggestions.length - 6}）`}</button>` : ''}
            <label class="cp-refine-custom">补充修改方向<textarea data-cp-refine rows="2" maxlength="2000" placeholder="例如：保留结尾，让白露的出场更俏皮，前半段节奏再快一点…" ${disabled ? 'disabled' : ''}>${esc(state.custom)}</textarea></label>
            <footer><span>修改后重新审阅，再决定生成</span>${button('refine-submit', '按这些方向优化', { id: node.id, primary: true, disabled: !state.choices.size && !state.custom.trim() })}</footer></section>`;
        }
        function renderVersions() {
            return `<section class="cp-versions"><header><h3>历史方案 · 只读</h3>${button('close-versions', '关闭')}</header>${versions.map(v => { const d = parse(v.plan, {}); return `<details><summary>v${v.revision} · ${esc(new Date(v.created_at).toLocaleString())}</summary><p>${esc(d.plan?.summary)}</p>${(d.plan?.nodes || []).map(n => `<article><strong>${esc(n.title)}</strong><span>${approved(d.states?.[n.id]) ? '已确认' : '待审阅'}</span><pre>${esc(n.content || n.prompt)}</pre></article>`).join('')}</details>`; }).join('') || '<p>提出方案或确认内容后，会保存对应的历史版本。</p>'}</section>`;
        }
        function renderHistory() {
            const items = runs.filter(r => r.project_id === project?.id); if (!items.length) return '';
            return `<section class="cp-history"><h3>生成记录</h3>${items.map(run => { const progress = parse(run.progress, []); return `<article><header><strong>${esc(run.name)}</strong><span>提交版本 v${run.project_revision} · ${esc(statusNames[run.status] || run.status)}</span>${['queued', 'running'].includes(run.status) ? button('stop', '完成当前生成后停止', { id: run.id }) : ''}</header>${run.error ? `<p class="cp-error">${esc(run.error)}</p>` : ''}<div>${progress.flatMap(p => p.asset_ids || []).map(id => { const a = assets.find(a => a.id === id); if(!a)return '<span class="creation-muted">资产未加载或已删除</span>'; return a.mime_type.startsWith('video/') ? Library.media(id,a.name,true,mediaURL) : `<a href="${esc(mediaURL(id))}" target="_blank" rel="noopener">${Library.media(id,'生成结果',false,mediaURL)}</a>`; }).join('')}</div><details><summary>查看本次提交的方案</summary><pre>${esc(parse(run.snapshot, {}).plan?.summary || run.name)}</pre>${(parse(run.snapshot, {}).plan?.nodes || []).filter(n => n.kind === 'text').map(n => `<h4>${esc(n.title)}</h4><pre>${esc(n.content)}</pre>`).join('')}</details></article>`; }).join('')}</section>`;
        }
        function drawCanvas() {
            const target = element?.querySelector('[data-cp-graph]'); if (!target) return;
            const doc = currentDoc(), layout = canvasLayout();
            const viewport = element.querySelector('[data-cp-viewport]');
            if (autoFit) { zoom = canvasFit(layout, viewport?.clientWidth || 820, viewport?.clientHeight || 510); autoFit = false; if (viewport) { viewport.scrollLeft = 0; viewport.scrollTop = 0; } }
            const paths = canvasPaths(layout);
            target.style.width = `${layout.width}px`; target.style.height = `${layout.height}px`; target.style.transform = `scale(${zoom})`;
            target.innerHTML = `<svg class="cp-edges" width="${layout.width}" height="${layout.height}" aria-hidden="true">${paths}</svg>${layout.nodes.map(item => {
                const { data: n } = item, isAsset = item.kind === 'asset', state = doc.states[item.id] || {};
                const assetID = isAsset ? n.id : state.selected_asset_id || state.candidates?.[0] || n.asset_id;
                const title = isAsset ? n.name : n.title, video = isAsset ? n.mime_type.startsWith('video/') : n.kind === 'video';
                const image = assetID && !video ? Library.media(assetID,title,false,mediaURL) : `<div class="cp-node-copy">${esc(isAsset ? '视频素材' : n.kind === 'text' ? n.content : n.content || (video ? '确认方案后生成视频' : '生成候选后在此审阅'))}</div>`;
                return `<button type="button" class="cp-artifact ${selected === item.id ? 'is-selected' : ''} ${isAsset ? 'cp-source' : ''}" data-cp-action="select" data-id="${esc(item.id)}" aria-pressed="${selected === item.id}" title="拖动调整位置；点击查看；Alt + 方向键移动" style="left:${item.x}px;top:${item.y}px;width:${item.width}px;height:${item.height}px"><header><strong>${esc(title)}</strong><span>${esc(isAsset ? '已提供' : nodeStatus(doc, n, runs))}</span></header>${image}<footer>${esc(isAsset ? '原始资产' : ({ character:'角色人设',scene:'场景参考',shot_reference:'分镜图',key_visual:'主视觉' })[n.purpose] || ({ text: '文本', image: '图片', video: '视频' })[n.kind])}${!isAsset && state.candidates?.length ? ` · ${state.candidates.length} 个产出` : ''}${!isAsset && n.purpose === 'script' ? ' · 动作 / 运镜 / 声音' : ''}</footer></button>`;
            }).join('')}`;
            const space = element.querySelector('[data-cp-space]'); space.style.width = `${layout.width * zoom}px`; space.style.height = `${layout.height * zoom}px`;
            const label = element.querySelector('[data-cp-zoom]'); if (label) label.textContent = `${Math.round(zoom * 100)}%`;
        }
        function canvasPaths(layout) {
            return layout.edges.map(edge => {
                const a = layout.nodes.find(n => n.id === edge.from), b = layout.nodes.find(n => n.id === edge.to); if (!a || !b) return '';
                const x1 = a.x + a.width, y1 = a.y + a.height / 2, x2 = b.x, y2 = b.y + b.height / 2, middle = (x1 + x2) / 2;
                return `<g class="${selected === edge.to || selected === edge.from ? 'is-active' : ''}"><path d="M${x1},${y1} C${middle},${y1} ${middle},${y2} ${x2},${y2}"/><text x="${middle}" y="${(y1 + y2) / 2 - 8}" text-anchor="middle">${esc(edge.label)}</text></g>`;
            }).join('');
        }
        function updateCanvasGeometry() {
            const target = element?.querySelector('[data-cp-graph]'); if (!target) return;
            const layout = canvasLayout();
            target.style.width = `${layout.width}px`; target.style.height = `${layout.height}px`;
            for (const card of target.querySelectorAll('[data-cp-action="select"]')) {
                const node = layout.nodes.find(n => n.id === card.dataset.id);
                if (node) { card.style.left = `${node.x}px`; card.style.top = `${node.y}px`; }
            }
            const edges = target.querySelector('svg');
            if (edges) { edges.setAttribute('width', layout.width); edges.setAttribute('height', layout.height); edges.innerHTML = canvasPaths(layout); }
            const space = element.querySelector('[data-cp-space]'); if (space) { space.style.width = `${layout.width * zoom}px`; space.style.height = `${layout.height * zoom}px`; }
        }
        async function newProject(templateID = '') {
            const version = epoch, initialPreferences = project ? null : currentPreferences();
            const response = await api('POST', '/api/creation/projects', { template_id: templateID });
            if (version !== epoch) return null;
            projectsView=false;openRequest++;assets=[];runs=[];project = response.project; projects = [project, ...projects.filter(p => p.id !== project.id)];
            if (initialPreferences && (initialPreferences.output_kind || initialPreferences.aspect_ratio)) preferenceDrafts.set(project.id, initialPreferences);
            optionsOpen = false;
            selected = ''; draft = ''; attachments = []; editing = false; versions = null; feedback = ''; autoFit = true; render();
            return project;
        }
        async function send(text = draft, nodeID = currentDoc().plan.questions?.length || selected.startsWith('asset:') ? '' : selected) {
            if (automaticActive(project)) throw new Error('先停止一键生成，再修改创作要求');
            const preferences = { ...currentPreferences() };
            if (!text.trim() && preferencesChanged()) nodeID = '';
            const message = text.trim() || (currentDoc().plan.nodes.length && preferencesChanged() ? '请按所选创作目标和画面比例调整方案，保留未受影响的已确认内容。' : ''); if (!message) throw new Error('先说说你的创作想法');
            const savedAttachments = [...attachments], owner = epoch;
            pendingMessage = message; followMessages = true; render();
            try {
                if (!project) {
                    if (!await newProject()) return;
                    draft = message; attachments = savedAttachments;
                }
                if (owner !== epoch) return;
                const id = project.id, key = JSON.stringify([id, message, nodeID, savedAttachments, preferences]);
                if (!requestKeys.has(key)) requestKeys.set(key, uid());
                const response = await api('POST', `/api/creation/projects/${encodeURIComponent(id)}/messages`, { revision: project.revision, message, preferences, node_id: nodeID, asset_ids: savedAttachments, request_id: requestKeys.get(key) });
                if (owner !== epoch || id !== project?.id) return;
                project = response.project; preferenceDrafts.set(id, preferences); optionsOpen = false; requestKeys.delete(key); draft = ''; attachments = []; editing = false; feedback = '';
                if (visible) { clearTimeout(timer); timer = setTimeout(() => poll(viewEpoch), 1000); }
            } finally {
                if (owner === epoch) { pendingMessage = null; render(); }
            }
        }

        async function action(name, id, assetID) {
            const version = epoch, projectID = project?.id;
            if (['automatic-start', 'generate'].includes(name) && preferencesChanged()) throw new Error('创作选项尚未应用，请先发送，让助手更新方案');
            if (name === 'retry-plan') { const message = [...currentDoc().messages].reverse().find(m => m.role === 'user'); if (message) await send(message.content, message.node_id || ''); return; }
            if (name === 'new') { projectsView=false;openRequest++;assets=[];runs=[]; preferenceDrafts.delete(''); optionsOpen = false; project = null; selected = ''; draft = ''; attachments = []; versions = null; feedback = ''; editing = false; render(); return; }
            if(name==='project-list'){projectsView=true;openRequest++;renameID='';render();await refresh();return;}
            if(name==='open-project'){
                const request=++openRequest;const response=await api('GET',`/api/creation/projects/${encodeURIComponent(id)}`);
                if(version!==epoch||request!==openRequest)return;
                project=response.project;projectsView=false;selected='';draft='';attachments=[];assets=[];runs=[];picker=false;versions=null;editing=false;feedback='';autoFit=true;optionsOpen=false;render();await refresh();return;
            }
            if(name==='project-assets'){onAssets(projectID);return;}
            if(name==='rename-project'){renameID=id;renameValue=((project?.id===id?project:projects.find(p=>p.id===id)))?.name||'';projectsView=true;render();element.querySelector('[data-cp-rename]')?.focus();return;}
            if(name==='cancel-rename'){renameID='';render();return;}
            if(name==='save-rename'){
                const row=(project?.id===id?project:projects.find(p=>p.id===id));
                const response=await api('PATCH',`/api/creation/projects/${encodeURIComponent(id)}`,{name:renameValue.trim(),revision:row.revision});
                if(version!==epoch)return;
                projects=projects.map(p=>p.id===id?response.project:p);if(project?.id===id)project=response.project;renameID='';feedback='项目已重命名';render();return;
            }
            if(name==='delete-project'){
                const row=(project?.id===id?project:projects.find(p=>p.id===id));
                if(!await confirm(`删除项目「${row.name}」及对话、画布和生成记录？图片与视频会保留在「未归属资产」。`)||version!==epoch)return;
                await api('DELETE',`/api/creation/projects/${encodeURIComponent(id)}?revision=${row.revision}`);
                if(version!==epoch)return;
                if(project?.id===id){project=null;assets=[];runs=[];selected='';draft='';attachments=[];}
                projects=projects.filter(p=>p.id!==id);projectsView=true;feedback='项目已删除，资产已保留';render();return;
            }
            if (name === 'fullscreen') { toggleFullscreen(); return; }
            if (name === 'canvas-review') { fullscreenReview = !fullscreenReview; render(); return; }
            if (name === 'locate-selected') { focusCanvasNode(selected); return; }
            if (name === 'connect-shots') {
                if (project?.planning || automaticActive(project)) return;
                const nodes = unboundShots(currentDoc()); if (!nodes.length) return;
                selected = ''; draft = `请补齐这些分镜图与对应视频的真实依赖：${nodes.map(n => n.title + '（' + n.id + '）').join('、')}。按原脚本的视频交付数量与镜头时段匹配，视频 references 的 shot_ids 必须绑定对应 storyboard/shot_ids，同时补齐 depends_on。已有未确认视频优先更新；已确认视频和产物保留，必要时新增待审阅的分镜版视频节点，不覆盖旧版。复用已确认分镜图，不重新生图；只整理方案，不自动生成图片或视频。`;
                await send(); return;
            }
            if (name === 'select') { selected = id; editing = false; if (fullscreen) fullscreenReview = true; render(); return; }
            if (name === 'arrange') { saveLayout({}, true); autoFit = true; drawCanvas(); return; }
            if (name === 'retry-layout') { const positions = canvasState().positions; saveLayout(positions, !Object.keys(positions).length); return; }
            if (name === 'zoom-in' || name === 'zoom-out' || name === 'fit') { if (name === 'fit') autoFit = true; else zoom = Math.min(1.6, Math.max(.025, zoom + (name === 'zoom-in' ? .15 : -.15))); drawCanvas(); return; }
            if (name === 'pick' || name === 'close-picker') { picker = name === 'pick'; render(); if(picker)await assetPicker.show(); return; }
            if (name === 'attach') { attachments = attachments.includes(id) ? attachments.filter(a => a !== id) : [...attachments, id]; render(); return; }
            if (name === 'detach') { attachments = attachments.filter(a => a !== id); render(); return; }
            if (name === 'upload') { element.querySelector('[data-cp-upload]')?.click(); return; }
            if (name === 'assets') { onAssets(); return; }
            if (name === 'close-versions') { versions = null; render(); return; }
            if (name === 'example-video' || name === 'example-image') { draft = name === 'example-video' ? '我想用这些角色素材创作一支15秒短片，请帮我完善故事、主视觉和分镜，确认后再生成。' : '我想为这款产品创作一组场景图，请先帮我确定视觉风格和创作方案。'; render(); element.querySelector('[data-cp-draft]')?.focus(); return; }
            if (name === 'edit') { editing = !editing; const node = currentDoc().plan.nodes.find(n => n.id === selected); editText = node?.content || node?.prompt || ''; render(); return; }
            if (name === 'refine-choice') {
                const node = currentDoc().plan.nodes.find(n => n.id === selected), suggestion = node && revisionSuggestions(node)[Number(id)];
                if (!suggestion) return;
                const state = refinementDraft(); if (state.choices.has(suggestion.instruction)) state.choices.delete(suggestion.instruction); else state.choices.add(suggestion.instruction);
                render(); return;
            }
            if (name === 'refine-more') { refinementDraft().expanded = !refinementDraft().expanded; render(); return; }
            if (name === 'refine-submit') {
                const node = currentDoc().plan.nodes.find(n => n.id === id); if (!node) return;
                const state = refinementDraft(id), message = refinementMessage(node, state.choices, state.custom);
                const unsentDraft = draft;
                await send(message, id);
                if (version === epoch && projectID === project?.id) { refinementDrafts.delete(`${projectID}:${id}`); draft = unsentDraft; }
                return;
            }
            if (name === 'save-edit') { if (!editText.trim()) throw new Error('请输入修改内容'); await send(`将这个节点的创作内容改为以下内容，保留明确指定的原文并同步受影响的下游方案，其他节点保持不变：\n${editText}`, id); return; }
            if (name === 'answer') { const [i, j] = id.split(':').map(Number), question = currentDoc().plan.questions[i]; await send(`关于“${question.question}”，我选择：${question.options[j]}`, ''); return; }
            if (name === 'versions') { const response = await api('GET', `/api/creation/projects/${encodeURIComponent(projectID)}/versions`); if (version === epoch && projectID === project?.id) { versions = response.versions || []; render(); } return; }
            if (name === 'save-template') { await api('POST', `/api/creation/projects/${encodeURIComponent(projectID)}/template`, {}); if (version === epoch) { showMessage('已保存创作模板，复用时会重新匹配素材'); onTemplates(false); } return; }
            if (name === 'automatic-start' || name === 'automatic-stop') {
                if (name === 'automatic-start' && (draft.trim() || attachments.length)) throw new Error('先发送输入框里的想法或素材，再一键生成，避免遗漏你的要求');
                const key = `automatic:${projectID}`;
                if (!requestKeys.has(key)) requestKeys.set(key, uid());
                let response;
                try { response = await api('POST', `/api/creation/projects/${encodeURIComponent(projectID)}/automatic${name === 'automatic-stop' ? '/stop' : ''}`, name === 'automatic-stop' ? {} : { revision: project.revision, request_id: requestKeys.get(key) }); }
                catch (error) { if ([400,404,409].includes(error.httpStatus)) requestKeys.delete(key); throw error; }
                if (version === epoch && projectID === project?.id) {
                    requestKeys.delete(key); project = response.project; feedback = name === 'automatic-stop' ? '正在停止；当前提交会先保存，不再生成后续节点。' : '已启动一键生成。已确认内容和已有产物会保留。';
                    if (visible) { clearTimeout(timer); timer = setTimeout(() => poll(viewEpoch), 1000); }
                    render();
                }
                return;
            }
            if (name === 'stop') { await api('POST', `/api/creation/runs/${encodeURIComponent(id)}/cancel`, {}); if (version === epoch) await refresh(); return; }
            let response;
            if (name === 'approve' || name === 'choose') response = await api('POST', `/api/creation/projects/${encodeURIComponent(projectID)}/review`, { revision: project.revision, node_id: id, asset_id: assetID || '' });
            if (name === 'generate') {
                const key = `generate:${projectID}:${id}`;
                if (!requestKeys.has(key)) requestKeys.set(key, uid());
                try { response = await api('POST', `/api/creation/projects/${encodeURIComponent(projectID)}/generate`, { revision: project.revision, node_id: id, request_id: requestKeys.get(key) }); }
                catch (error) { if ([400, 404, 409].includes(error.httpStatus)) requestKeys.delete(key); throw error; }
                if (version === epoch) { requestKeys.delete(key); if (response.run) runs = [response.run, ...runs.filter(r => r.id !== response.run.id)]; }
            }
            if (response && version === epoch && projectID === project?.id) { project = response.project; feedback = name === 'generate' ? '已提交生成，结果会自动归入资产。离开页面后仍会继续。' : '已确认。修改上游内容时，相关下游会重新进入待审阅。'; render(); }
        }
        async function perform(fn) {
            if (busy) return;
            const version = epoch; busy = true;
            try { await fn(); }
            catch (error) { if (version === epoch) { feedback = error.message || '操作失败，请重试'; if (error.httpStatus === 409) { try { await refresh(); } catch (_) {} } } }
            finally { if (version === epoch) { busy = false; render(); } }
        }
        function bind() {
            element.addEventListener('toggle', event => { if (event.target.hasAttribute?.('data-cp-options') && element.contains?.(event.target)) optionsOpen = event.target.open; }, true);
            element.addEventListener('click', event => {
                if (!event.target.closest('[data-cp-options]')) { const options = element.querySelector('[data-cp-options]'); if (options) options.open = false; optionsOpen = false; }
                const summary = event.target.closest('summary'), round = summary?.parentElement;
                if (round?.hasAttribute?.('data-cp-options')) optionsOpen = !round.open;
                if (round?.hasAttribute?.('data-cp-turn')) roundsOpen.set(round.dataset.cpTurn, !round.open);
                const target = event.target.closest('[data-cp-action]');
                if (suppressClick) { const suppressed = suppressClick; suppressClick = null; if (target?.dataset.cpAction === 'select' && target.dataset.id === suppressed.id && Date.now() < suppressed.until) { event.preventDefault?.(); return; } }
                if (target && !target.disabled) void perform(() => action(target.dataset.cpAction, target.dataset.id, target.dataset.asset));
            });
            element.addEventListener('submit', event => { if (event.target.hasAttribute('data-cp-form')) { event.preventDefault(); void perform(() => send()); } });
            element.addEventListener('input', event => {
                if(event.target.hasAttribute('data-cp-search')){projectSearch=event.target.value;const grid=element.querySelector('.cp-project-grid');if(grid)grid.innerHTML=projectCards();}
                if(event.target.hasAttribute('data-cp-rename'))renameValue=event.target.value;
                if (event.target.hasAttribute('data-cp-draft')) draft = event.target.value;
                if (event.target.hasAttribute('data-cp-edit')) editText = event.target.value;
                if (event.target.hasAttribute('data-cp-refine')) {
                    const state = refinementDraft(); state.custom = event.target.value;
                    const submit = element.querySelector('[data-cp-action="refine-submit"]'); if (submit) submit.disabled = busy || project?.planning || (!state.choices.size && !state.custom.trim());
                }
            });
            element.addEventListener('change', event => {
                const el = event.target;
                if (el.hasAttribute('data-cp-locate') && el.value) { selected = el.value; editing = false; render(); focusCanvasNode(selected); return; }
                if (el.hasAttribute('data-cp-preference') && !busy && !project?.planning && !automaticActive(project)) {
                    const key = el.dataset.cpPreference;
                    if (!['output_kind', 'aspect_ratio'].includes(key)) return;
                    preferenceDrafts.set(project?.id || '', normalizePreferences({ ...currentPreferences(), [key]: el.value }));
                    render();
                }
                if (el.hasAttribute('data-cp-upload')) void perform(async () => {
                    const version = epoch;
                    if(!project){const savedDraft=draft,savedAttachments=[...attachments];if(!await newProject())return;draft=savedDraft;attachments=savedAttachments;}
                    const uploadProjectID=project.id;
                    for (const file of Array.from(el.files || [])) {
                        if (file.size > 64 * 1024 * 1024) throw new Error(`${file.name} 超过64 MiB`);
                        const data = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = () => reject(new Error('文件读取失败')); reader.readAsDataURL(file); });
                        if (version !== epoch) return;
                        const result = await api('POST', '/api/creation/assets', { name: file.name, mime_type: file.type, content: data.split(',')[1], project_id:uploadProjectID });
                        if (version !== epoch) return;
                        attachments.push(result.asset.id);
                    }
                    await refresh(); feedback = '素材已上传，发送创作想法时会一起交给助手。';
                });
            });
            element.addEventListener('pointerdown', event => {
                if (dragging || pan || (event.button !== undefined && event.button !== 0)) return;
                const view = event.target.closest('[data-cp-viewport]'); if (!view) return;
                const card = event.target.closest('[data-cp-action="select"]');
                if (card) {
                    const node = canvasLayout().nodes.find(n => n.id === card.dataset.id); if (!node) return;
                    dragging = { id: node.id, origin: { x: node.x, y: node.y }, prior: canvasState().positions[node.id], x: event.clientX, y: event.clientY, left: view.scrollLeft, top: view.scrollTop, view, card, pointer: event.pointerId, moved: false };
                    card.setPointerCapture?.(event.pointerId); event.preventDefault(); return;
                }
                if (event.target.closest('button') || event.pointerType === 'touch') return;
                pan = { x: event.clientX, y: event.clientY, left: view.scrollLeft, top: view.scrollTop, view, pointer: event.pointerId };
                view.setPointerCapture?.(event.pointerId); view.classList.add('is-panning');
            });
            element.addEventListener('pointermove', event => {
                if (dragging && event.pointerId === dragging.pointer) {
                    const d = dragging, dx = event.clientX - d.x, dy = event.clientY - d.y;
                    if (!d.moved && Math.hypot(dx, dy) < 4) return;
                    d.moved = true; d.card.classList.add('is-dragging');
                    const position = movedPosition(d.origin, dx + d.view.scrollLeft - d.left, dy + d.view.scrollTop - d.top, zoom);
                    canvasState().positions[d.id] = position; updateCanvasGeometry();
                } else if (pan && event.pointerId === pan.pointer) { pan.view.scrollLeft = pan.left - (event.clientX - pan.x); pan.view.scrollTop = pan.top - (event.clientY - pan.y); }
            });
            const endPointer = (event, cancelled = false) => {
                if (dragging && event.pointerId === dragging.pointer) {
                    const d = dragging; dragging = null; d.card.classList.remove('is-dragging'); d.card.releasePointerCapture?.(event.pointerId);
                    if (d.moved) {
                        if (cancelled) { if (d.prior) canvasState().positions[d.id] = d.prior; else delete canvasState().positions[d.id]; updateCanvasGeometry(); }
                        else { saveLayout({ [d.id]: canvasState().positions[d.id] }); suppressClick = { id: d.id, until: Date.now() + 500 }; }
                    }
                }
                if (pan && event.pointerId === pan.pointer) { const p = pan; pan = null; p.view.classList.remove('is-panning'); p.view.releasePointerCapture?.(event.pointerId); }
                if (renderPending) render();
            };
            element.addEventListener('pointerup', event => endPointer(event));
            element.addEventListener('pointercancel', event => endPointer(event, true));
            element.addEventListener('lostpointercapture', event => endPointer(event, true));
            element.addEventListener('keydown', event => {
                if (event.key === 'Escape' && fullscreen) { event.preventDefault(); toggleFullscreen(false); return; }
                if (event.key === 'Escape' && optionsOpen) { const options = element.querySelector('[data-cp-options]'); if (options) { options.open = false; options.querySelector('summary')?.focus({ preventScroll: true }); } optionsOpen = false; }

                const offsets = { ArrowLeft: [-20, 0], ArrowRight: [20, 0], ArrowUp: [0, -20], ArrowDown: [0, 20] };
                const card = event.target.closest('[data-cp-action="select"]');
                if (!card || !event.altKey || !offsets[event.key]) return;
                event.preventDefault(); const node = canvasLayout().nodes.find(n => n.id === card.dataset.id); if (!node) return;
                const [dx, dy] = offsets[event.key]; saveLayout({ [node.id]: movedPosition(node, dx, dy, 1) }); updateCanvasGeometry();
            });
        }
        return { mount, reset, setVisible, newProject: template => perform(() => newProject(template)), refresh };
    }
    return { canvasFit, canvasFocus, unboundShots, shotCards, renderShotStrip, normalizePreferences, preferenceSummary, renderDecisions, automaticActive, automaticBlock, renderAutomatic, conversationRounds, captureReadingPosition, restoreReadingPosition, renderPlanning, renderMediaProgress, documentOf, approved, dependenciesReady, generationBlock, layoutGraph, movedPosition, revisionSuggestions, refinementMessage, renderReferences, nodeStatus, createController };
});
