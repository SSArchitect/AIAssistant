(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    root.CreationUI = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const clone = value => JSON.parse(JSON.stringify(value));
    const parse = (value, fallback) => { try { return JSON.parse(value); } catch (_) { return fallback; } };
    const uid = () => globalThis.crypto?.randomUUID?.() || `node-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const statuses = { queued: '等待运行', running: '生成中', stopping: '正在停止', completed: '已完成', failed: '失败', interrupted: '已中断', cancelled: '已停止', pending: '等待上游', skipped: '未执行' };
    function newNode(kind = 'image', id = uid()) {
        return { id, kind, name: kind === 'image' ? '生成图片' : '生成视频', prompt: '', count: 1, aspect_ratio: '16:9', duration_seconds: 5, character_style: '', inputs: [], asset_ids: [] };
    }
    const story = newNode('image', 'frames'); story.name = '创作三张分镜'; story.count = 3; story.prompt = '为同一主题创作一张电影感分镜，统一主体与色调，画面清晰、有叙事感。主题：';
    const motion = newNode('video', 'motion'); motion.name = '分镜生成视频'; motion.inputs = ['frames']; motion.prompt = '参考这些分镜中的主体与视觉风格，生成流畅连贯的短片，镜头缓慢推进，自然运动。';
    const original = newNode('image', 'original'); original.name = '创作原图'; original.prompt = '生成一幅构图简洁、光线柔和的画面。主体：';
    const refine = newNode('image', 'refine'); refine.name = '二次创作'; refine.inputs = ['original']; refine.prompt = '保留参考图片主体与构图，改为精致的水彩插画，柔和纸张纹理。';
    const builtin = [
        { id: 'builtin-story', kind: 'workflow_template', name: '分镜 → 短片', description: '三张图片 · 多图参考生视频', graph: { nodes: [story, motion] } },
        { id: 'builtin-refine', kind: 'workflow_template', name: '原图 → 二次创作', description: '先生成，再改变风格', graph: { nodes: [original, refine] } },
        { id: 'builtin-product', kind: 'image_template', name: '产品摄影', description: '柔和棚拍光线与简洁背景', graph: { nodes: [{ ...newNode('image', 'product'), name: '产品摄影', prompt: '专业产品摄影，简洁背景，柔和棚拍光线，真实材质，清晰细节。产品：' }] } },
        { id: 'builtin-anime', kind: 'image_template', name: '人物动漫化', description: '需要一张人物参考图', graph: { nodes: [{ ...newNode('image', 'anime'), name: '人物动漫化', prompt: '保留人物身份、姿态和构图，转为精致动漫风格。', character_style: 'anime' }] } },
        { id: 'builtin-chibi', kind: 'image_template', name: 'Q 版人物', description: '需要一张人物参考图', graph: { nodes: [{ ...newNode('image', 'chibi'), name: 'Q 版人物', prompt: '保留人物特征，转为可爱的 Q 版角色。', character_style: 'chibi', aspect_ratio: '1:1' }] } },
        { id: 'builtin-cinema', kind: 'video_template', name: '电影感运镜', description: '适用于文生视频或图片参考', graph: { nodes: [{ ...newNode('video', 'cinema'), name: '电影感运镜', prompt: '电影质感，镜头缓慢推进，自然光线，主体动作流畅，保留参考图中的细节。场景：' }] } },
    ];
    function graphOf(definition) { return clone(definition.graph || parse(definition.definition, { nodes: [] })); }
    function instantiate(definition) {
        const graph = graphOf(definition), ids = new Map(graph.nodes.map(n => [n.id, uid()]));
        graph.nodes = graph.nodes.map(n => ({ ...n, id: ids.get(n.id), inputs: (n.inputs || []).map(id => ids.get(id)).filter(Boolean), asset_ids: [] }));
        return graph;
    }
    function applyNodeTemplate(node, template) {
        const source = graphOf(template).nodes[0];
        if (!source || source.kind !== node.kind) throw new Error('模板与节点类型不匹配');
        return { ...source, id: node.id, inputs: [...node.inputs], asset_ids: [...node.asset_ids] };
    }
    function removeNode(graph, id) { return { nodes: graph.nodes.filter(n => n.id !== id).map(n => ({ ...n, inputs: n.inputs.filter(input => input !== id) })) }; }
    function validateGraph(graph) {
        if (!graph.nodes.length) return '请添加至少一个节点';
        const seen = new Map();
        for (const n of graph.nodes) {
            if (!n.prompt.trim()) return `${n.name}：请输入提示词`;
            if (seen.has(n.id)) return '节点 ID 重复';
            if (!['image', 'video'].includes(n.kind) || !Number.isInteger(n.count) || n.count < 1 || n.count > 9 || (n.kind === 'video' && n.count !== 1)) return '节点类型或产出数量无效';
            let count = n.asset_ids.length;
            if (new Set(n.asset_ids).size !== n.asset_ids.length || new Set(n.inputs).size !== n.inputs.length) return '输入引用重复';
            for (const id of n.inputs) { const source = seen.get(id); if (!source || source.kind !== 'image') return '输入只能引用前面图片节点的结果'; count += source.count; }
            if (count > (n.kind === 'image' ? 1 : 9)) return `${n.name}：输入图片过多，生图最多 1 张，视频最多 9 张`;
            if (n.character_style && count !== 1) return `${n.name}：人物风格模板需要一张参考图片`;
            seen.set(n.id, n);
        }
        return '';
    }
    function renderNode(node, index, graph, assets, templates) {
        const options = graph.nodes.slice(0, index).filter(n => n.kind === 'image');
        const imageAssets = assets.filter(a => ['image/png', 'image/jpeg', 'image/webp'].includes(a.mime_type) && a.size <= 16 * 1024 * 1024);
        return `<article class="creation-node" data-node="${esc(node.id)}"><header><span class="creation-step">${String(index + 1).padStart(2, '0')}</span><span class="creation-kind">${node.kind === 'image' ? '图片' : '视频'}</span><input aria-label="节点名称" data-field="name" value="${esc(node.name)}" maxlength="100"><button type="button" class="creation-icon" data-action="remove-node" data-id="${esc(node.id)}" aria-label="删除节点">×</button></header>
        <div class="creation-node-body"><label>效果模板<select data-node-template><option value="">选择模板，填入效果与参数</option>${templates.filter(t => t.kind === `${node.kind}_template`).map(t => `<option value="${esc(t.id)}">${esc(t.name)}</option>`).join('')}</select></label>
        <label>提示词<textarea data-field="prompt" rows="3" maxlength="4000" placeholder="描述这个节点需要产出的画面…">${esc(node.prompt)}</textarea></label>
        <div class="creation-options"><label>画幅<select data-field="aspect_ratio">${['16:9', '9:16', '1:1'].map(r => `<option ${r === node.aspect_ratio ? 'selected' : ''}>${r}</option>`).join('')}</select></label>${node.kind === 'image' ? `<label>图片数量<input data-field="count" type="number" min="1" max="9" value="${node.count}"></label><label>人物效果<select data-field="character_style">${[['', '常规'], ['anime', '动漫'], ['chibi', 'Q 版']].map(([v, label]) => `<option value="${v}" ${node.character_style === v ? 'selected' : ''}>${label}</option>`).join('')}</select></label>` : `<label>时长（秒）<input data-field="duration_seconds" type="number" min="1" max="15" value="${node.duration_seconds}"></label>`}</div>
        <details class="creation-inputs" ${node.inputs.length || node.asset_ids.length ? 'open' : ''}><summary>参考图片 · ${node.inputs.length} 个上游节点 / ${node.asset_ids.length} 个资产</summary><p>生图最多 1 张；视频最多 9 张。多张图片将作为视频的视觉参考。</p>${options.map(n => `<label class="creation-check"><input type="checkbox" data-input="inputs" value="${esc(n.id)}" ${node.inputs.includes(n.id) ? 'checked' : ''}>节点 ${graph.nodes.indexOf(n) + 1} · ${esc(n.name)}（${n.count} 张）</label>`).join('')}${imageAssets.map(a => `<label class="creation-check"><input type="checkbox" data-input="asset_ids" value="${esc(a.id)}" ${node.asset_ids.includes(a.id) ? 'checked' : ''}>资产 · ${esc(a.name)}</label>`).join('')}${!options.length && !imageAssets.length ? '<p>可在「资产」上传图片，或先添加一个图片节点。</p>' : ''}</details>
        <button class="creation-text-button" type="button" data-action="save-node-template" data-id="${esc(node.id)}">将此节点存为效果模板</button></div></article>`;
    }
    function renderAsset(asset, mediaURL) {
        const url = esc(mediaURL(asset.id));
        return `<article class="creation-asset"><div class="creation-asset-preview">${asset.mime_type.startsWith('video/') ? `<video controls playsinline preload="metadata" src="${url}"></video>` : `<img loading="lazy" src="${url}" alt="${esc(asset.name)}">`}</div><div class="creation-asset-info"><strong title="${esc(asset.name)}">${esc(asset.name)}</strong><span>${({ generated: '生成', upload: '上传', drive: '网盘' })[asset.source] || '网盘'} · ${(asset.size / 1024 / 1024).toFixed(1)} MB</span><a href="${url}" target="_blank" rel="noopener" download="${esc(asset.name)}">打开 / 下载</a></div></article>`;
    }
    function renderRun(run, assets, mediaURL) {
        const progress = parse(run.progress, []);
        return `<article class="creation-run"><header><strong>${esc(run.name)}</strong><span class="creation-status ${esc(run.status)}">${esc(statuses[run.status] || run.status)}</span></header><small>${esc(new Date(run.created_at).toLocaleString())}</small><ol>${progress.map((p, i) => `<li>${i + 1}. ${esc(statuses[p.status] || p.status)}${p.asset_ids.length ? ` · ${p.asset_ids.length} 个产出` : ''}</li>`).join('')}</ol>${run.error ? `<p class="creation-error">${esc(run.error)}</p>` : ''}${['running', 'queued'].includes(run.status) ? `<button class="btn-secondary" data-action="stop" data-id="${esc(run.id)}">完成当前生成后停止</button>` : ''}<div class="creation-results">${assets.filter(a => a.run_id === run.id).map(a => renderAsset(a, mediaURL)).join('')}</div></article>`;
    }
    function createController({ element, api, user, mediaURL, openDrive, confirm = async () => false }) {
        let epoch = 0, visibilityEpoch = 0, visible = false, timer = null, busy = false, tab = 'projects', definitions = [], assets = [], runs = [], draft = null, feedback = '', folderID = '', importItems = null;
        let search = '', mediaFilter = '', sourceFilter = '';
        const templates = () => [...builtin, ...definitions.filter(d => d.kind !== 'workflow')];
        let refreshFailed = false;
        const projectController = globalThis.CreationProjects?.createController({ api, user, mediaURL, onAssets: () => { tab = 'assets'; render(); }, onTemplates: () => { void refresh(); } });
        function reset() { projectController?.reset(); tab = 'projects'; epoch++; visibilityEpoch++; visible = false; search = ''; mediaFilter = ''; sourceFilter = ''; clearTimeout(timer); timer = null; busy = false; definitions = []; assets = []; runs = []; draft = null; feedback = ''; folderID = ''; importItems = null; element.innerHTML = ''; }
        function render() {
            projectController?.setVisible(false);
            const count = definitions.filter(d => d.kind === 'workflow').length;
            element.innerHTML = `<div class="creation-page ${tab === 'projects' ? 'is-projects' : ''}"><div class="creation-heading"><div><span class="creation-eyebrow">CREATIVE STUDIO</span><h2>让灵感，一步步成形。</h2><p>聊聊你的想法，让 AI 安排每一步创作。</p></div><button class="btn-primary" data-action="project-new">＋ 新创作</button></div><div class="creation-tabs" role="tablist">${[['projects', '创作项目', ''], ['templates', '模板', templates().length], ['assets', '资产', assets.length], ['workflows', '工作流编辑', count]].map(([id, label, n]) => `<button role="tab" aria-selected="${tab === id}" data-tab="${id}">${label}<span>${n}</span></button>`).join('')}</div><p class="creation-feedback" role="status">${esc(feedback)}</p><div class="creation-body"></div></div>`;
            const body = element.querySelector('.creation-body');
            if (!user()) { body.innerHTML = '<p class="creation-empty">登录后即可保存工作流、模板与创作资产。</p>'; return; }
            if (tab === 'projects') {
                body.innerHTML = '<div class="creation-project-host"></div>';
                projectController?.mount(body.querySelector('.creation-project-host'));
                projectController?.setVisible(visible);
            } else if (tab === 'templates') {
                body.innerHTML = ['project_template', 'workflow_template', 'image_template', 'video_template'].map(kind => `<h3 class="creation-section-title">${({ project_template: '创作项目模板', workflow_template: '工作流模板', image_template: '生图效果', video_template: '视频效果' })[kind]}</h3><div class="creation-template-grid">${templates().filter(t => t.kind === kind).map(t => `<article class="creation-template"><span class="creation-template-symbol">${kind === 'workflow_template' ? '◈ → ◇' : kind === 'image_template' ? '▧' : '▷'}</span><h3>${esc(t.name)}</h3><p>${esc(t.description || `${graphOf(t).nodes.length} 个节点 · 我的模板`)}</p><button class="btn-secondary" data-action="project-template" data-id="${esc(t.id)}">用这个模板创作</button>${kind !== 'project_template' ? `<button class="creation-text-button" data-action="use-template" data-id="${esc(t.id)}">手动编辑</button>` : ''}${!t.id.startsWith('builtin-') ? `<button class="creation-text-button" data-action="delete" data-id="${esc(t.id)}">删除</button>` : ''}</article>`).join('')}</div>`).join('');
            } else if (tab === 'assets') {
                body.innerHTML = `<div class="creation-assets-toolbar"><div><h3>我的资产</h3><p>文件保存在网盘「资产」中，创作记录关联原文件。</p></div><button class="btn-primary" type="button" data-action="upload">上传图片 / 视频</button><input type="file" multiple accept="image/png,image/jpeg,image/webp,video/mp4,video/webm" data-upload hidden><button class="btn-secondary" data-action="import">从网盘归入</button><button class="btn-secondary" data-action="drive">打开资产文件夹</button></div><p class="creation-muted">支持 PNG、JPEG、WebP、MP4、WebM，单文件最大 64 MiB；节点参考图片最大 16 MiB。</p><div class="creation-options"><input aria-label="搜索资产" data-search placeholder="搜索资产名称" value="${esc(search)}"><select aria-label="媒体类型" data-media-filter><option value="">全部类型</option><option value="image/" ${mediaFilter === 'image/' ? 'selected' : ''}>图片</option><option value="video/" ${mediaFilter === 'video/' ? 'selected' : ''}>视频</option></select><select aria-label="资产来源" data-source-filter>${[['', '全部来源'], ['generated', '生成'], ['upload', '上传'], ['drive', '网盘']].map(([v, name]) => `<option value="${v}" ${sourceFilter === v ? 'selected' : ''}>${name}</option>`).join('')}</select></div><div class="creation-import"></div><div class="creation-asset-grid"></div>`;
                renderAssets();
                if (importItems) body.querySelector('.creation-import').innerHTML = `<h3>选择文件，移入网盘「资产」文件夹</h3>${importItems.length ? importItems.map(i => `<button class="btn-secondary" data-action="import-file" data-id="${esc(i.id)}">${esc(i.name)}</button>`).join('') : '<p>暂无可归入的媒体文件。</p>'}<button class="creation-text-button" data-action="close-import">关闭</button>`;
            } else {
                body.innerHTML = `<div class="creation-workspace"><aside class="creation-library"><h3>我的工作流</h3>${definitions.filter(d => d.kind === 'workflow').map(d => `<div class="creation-workflow-row ${draft?.id === d.id ? 'active' : ''}"><button data-action="edit" data-id="${esc(d.id)}"><strong>${esc(d.name)}</strong><small>${graphOf(d).nodes.length} 个节点</small></button><button class="creation-icon" aria-label="删除工作流" data-action="delete" data-id="${esc(d.id)}">×</button></div>`).join('') || '<p>从空白开始，或选择一个模板。</p>'}<button class="creation-text-button" data-tab="templates">浏览模板 →</button></aside><div class="creation-canvas">${draft ? `<div class="creation-editor-head"><input aria-label="工作流名称" data-workflow-name maxlength="100" value="${esc(draft.name)}"><div><button class="btn-secondary" data-action="save">保存</button><button class="btn-secondary" data-action="save-template">存为模板</button><button class="btn-primary" data-action="run">运行工作流</button></div></div><p class="creation-muted">按顺序运行 · 结果自动归入资产 · 离开页面后继续执行</p><div class="creation-flow">${draft.graph.nodes.map((n, i) => renderNode(n, i, draft.graph, assets, templates())).join('<div class="creation-connector" aria-hidden="true">↓</div>')}</div><div class="creation-add"><button class="btn-secondary" data-action="add-image">＋ 图片节点</button><button class="btn-secondary" data-action="add-video">＋ 视频节点</button></div>` : `<div class="creation-empty"><div class="creation-empty-symbol">◈ → ◇ → ▷</div><h3>连接你的创作步骤</h3><p>批量创作分镜、将图片制作成视频，或在原图上继续创作。</p><button class="btn-primary" data-action="new">新建工作流</button><button class="btn-secondary" data-tab="templates">从模板开始</button></div>`}</div></div><section class="creation-history"><h3>最近运行</h3><div class="creation-runs"></div></section>`;
                renderRuns();
            }
            element.querySelectorAll('button').forEach(b => { if (!b.closest('.creation-project-host')) b.disabled = busy; });
        }
        function replaceIfChanged(target, html) { if (target && target._creationHTML !== html) { target.innerHTML = html; target._creationHTML = html; } }
        function renderAssets() {
            const target = element.querySelector('.creation-asset-grid');
            if (target) replaceIfChanged(target, assets.filter(a => a.name.toLowerCase().includes(search.toLowerCase()) && a.mime_type.startsWith(mediaFilter) && (!sourceFilter || a.source === sourceFilter)).map(a => renderAsset(a, mediaURL)).join('') || '<p class="creation-empty">暂无匹配的资产。上传素材或运行工作流后，结果会出现在这里。</p>');
        }
        function renderRuns() { const target = element.querySelector('.creation-runs'); if (target) replaceIfChanged(target, runs.map(r => renderRun(r, assets, mediaURL)).join('') || '<p class="creation-muted">还没有运行记录。</p>'); }
        function message(value, transient = false) { feedback = value; refreshFailed = transient; const node = element.querySelector('.creation-feedback'); if (node) node.textContent = feedback; }
        async function refresh(full = false) {
            if (!user()) { render(); return; }
            const version = epoch;
            const [d, a, r] = await Promise.all([api('GET', '/api/creation/definitions'), api('GET', '/api/creation/assets'), api('GET', '/api/creation/runs')]);
            if (epoch !== version) return;
            if (refreshFailed) message('');
            definitions = d.definitions || []; assets = a.assets || []; folderID = a.folder_id; runs = r.runs || [];
            if (full) render(); else { renderRuns(); if (tab === 'assets') renderAssets(); }
        }
        async function poll(version = visibilityEpoch) {
            clearTimeout(timer);
            if (!visible) return;
            try { await refresh(); } catch (error) { if (version === visibilityEpoch) message(error.message, true); }
            if (visible && version === visibilityEpoch) timer = setTimeout(() => poll(version), 5000);
        }
        async function setVisible(value) {
            visible = value; const version = ++visibilityEpoch; clearTimeout(timer);
            if (!value) { projectController?.setVisible(false); return; }
            render(); try { await refresh(true); } catch (error) { if (version === visibilityEpoch) message(error.message, true); }
            if (visible && version === visibilityEpoch) timer = setTimeout(() => poll(version), 5000);
        }
        async function save(kind = 'workflow', graph = draft.graph, name = draft.name) {
            const version = epoch, currentDraft = draft;
            const updating = kind === 'workflow' && draft.id;
            const response = await api(updating ? 'PUT' : 'POST', `/api/creation/definitions${updating ? `/${encodeURIComponent(draft.id)}` : ''}`, { name, kind, graph });
            if (version !== epoch || currentDraft !== draft) return null;
            if (kind === 'workflow') draft.id = response.definition.id;
            return response.definition;
        }
        async function action(name, id) {
            if (name === 'project-new' || name === 'project-template') { tab = 'projects'; render(); await projectController?.newProject(name === 'project-template' ? id : ''); return; }
            if (name === 'new') { draft = { name: '未命名工作流', graph: { nodes: [newNode()] } }; tab = 'workflows'; render(); return; }
            if (name === 'edit') { const d = definitions.find(d => d.id === id); draft = { id, name: d.name, graph: graphOf(d) }; render(); return; }
            if (name === 'add-image' || name === 'add-video') { if (draft.graph.nodes.length >= 20) throw new Error('最多 20 个节点'); draft.graph.nodes.push(newNode(name === 'add-image' ? 'image' : 'video')); render(); return; }
            if (name === 'remove-node') { draft.graph = removeNode(draft.graph, id); render(); return; }
            if (name === 'use-template') {
                const t = templates().find(t => t.id === id);
                if (t.kind === 'workflow_template') draft = { name: `${t.name} · 新创作`, graph: instantiate(t) };
                else { if (!draft) draft = { name: '未命名工作流', graph: { nodes: [] } }; if (draft.graph.nodes.length >= 20) throw new Error('最多 20 个节点'); draft.graph.nodes.push(...instantiate(t).nodes); }
                tab = 'workflows'; render(); return;
            }
            if (name === 'upload') { element.querySelector('[data-upload]')?.click(); return; }
            if (name === 'drive') { await openDrive(folderID); return; }
            if (name === 'close-import') { importItems = null; render(); return; }
            const version = epoch;
            if (name === 'delete') {
                if (!await confirm('删除此工作流或模板？运行记录和资产会保留。') || epoch !== version) return;
                await api('DELETE', `/api/creation/definitions/${encodeURIComponent(id)}`);
                if (epoch !== version) return;
                if (draft?.id === id) draft = null;
            } else if (name === 'save') { await save(); if (epoch !== version) return; message('工作流已保存'); }
            else if (name === 'save-template') { await save('workflow_template', draft.graph, `${draft.name} · 模板`); if (epoch !== version) return; message('工作流模板已保存，复用时重新选择输入资产'); }
            else if (name === 'save-node-template') { const n = draft.graph.nodes.find(n => n.id === id); await save(`${n.kind}_template`, { nodes: [n] }, n.name); if (epoch !== version) return; message('效果模板已保存'); }
            else if (name === 'run') {
                const error = validateGraph(draft.graph); if (error) throw new Error(error);
                const saved = await save(); if (!saved || epoch !== version) return;
                await api('POST', '/api/creation/runs', { workflow_id: saved.id });
                if (epoch !== version) return;
                message('工作流已启动，产出会逐步归入资产');
            } else if (name === 'stop') { await api('POST', `/api/creation/runs/${encodeURIComponent(id)}/cancel`, {}); if (epoch !== version) return; message('当前生成完成并归档后停止'); }
            else if (name === 'import') {
                const result = await api('GET', '/api/drive/tree'); if (epoch !== version) return;
                importItems = (result.flat_items || []).filter(i => i.type === 'file' && /^(image|video)\//.test(i.mime_type || '') && !assets.some(a => a.drive_item_id === i.id));
            } else if (name === 'import-file') { await api('POST', '/api/creation/assets/import', { drive_item_id: id }); if (epoch !== version) return; importItems = importItems.filter(i => i.id !== id); message('已归入网盘资产文件夹'); }
            if (epoch === version) await refresh(true);
        }
        async function perform(fn) {
            if (busy) return;
            const version = epoch; busy = true; element.querySelectorAll('button').forEach(b => { if (!b.closest('.creation-project-host')) b.disabled = true; });
            try { await fn(); } catch (error) { if (version === epoch) message(error.message || '操作失败'); }
            finally { if (version === epoch) { busy = false; element.querySelectorAll('button').forEach(b => { if (!b.closest('.creation-project-host')) b.disabled = false; }); } }
        }
        element.addEventListener('click', event => {
            const target = event.target.closest('[data-tab], [data-action]'); if (!target || busy) return;
            if (target.dataset.tab) { tab = target.dataset.tab; render(); return; }
            void perform(() => action(target.dataset.action, target.dataset.id));
        });
        element.addEventListener('input', event => {
            const el = event.target;
            if (el.hasAttribute('data-workflow-name') && draft) draft.name = el.value;
            if (el.hasAttribute('data-search')) { search = el.value; renderAssets(); }
            const n = draft?.graph.nodes.find(n => n.id === el.closest('[data-node]')?.dataset.node);
            if (n && el.dataset.field) n[el.dataset.field] = ['count', 'duration_seconds'].includes(el.dataset.field) ? Number(el.value) : el.value;
        });
        element.addEventListener('change', event => {
            const el = event.target, n = draft?.graph.nodes.find(n => n.id === el.closest('[data-node]')?.dataset.node);
            if (n && el.dataset.input) {
                n[el.dataset.input] = Array.from(el.closest('[data-node]').querySelectorAll(`[data-input="${el.dataset.input}"]:checked`), x => x.value);
                el.closest('[data-node]').querySelector('summary').textContent = `参考图片 · ${n.inputs.length} 个上游节点 / ${n.asset_ids.length} 个资产`;
            }
            if (n && el.hasAttribute('data-node-template') && el.value) { draft.graph.nodes[draft.graph.nodes.indexOf(n)] = applyNodeTemplate(n, templates().find(t => t.id === el.value)); render(); }
            if (el.hasAttribute('data-media-filter')) { mediaFilter = el.value; renderAssets(); }
            if (el.hasAttribute('data-source-filter')) { sourceFilter = el.value; renderAssets(); }
            if (el.hasAttribute('data-upload')) void perform(async () => {
                const version = epoch;
                for (const file of Array.from(el.files || [])) {
                    if (file.size > 64 * 1024 * 1024) throw new Error(`${file.name} 超过 64 MiB`);
                    const data = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = () => reject(new Error('文件读取失败')); reader.readAsDataURL(file); });
                    if (epoch !== version) return;
                    await api('POST', '/api/creation/assets', { name: file.name, mime_type: file.type, content: data.split(',')[1] });
                    if (epoch !== version) return;
                    message(`已上传 ${file.name}`);
                }
                await refresh(true);
            });
        });
        return { reset, setVisible };
    }
    return { newNode, builtin, graphOf, instantiate, applyNodeTemplate, removeNode, validateGraph, renderNode, renderAsset, renderRun, createController };
});
