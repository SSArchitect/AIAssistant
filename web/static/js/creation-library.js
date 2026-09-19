(function (root, factory) {
    const api = factory(); if (typeof module === 'object' && module.exports) module.exports = api; root.CreationLibrary = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';
    const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    function thumbnailURL(url) { return url.replace(/\/content(?=\?|$)/, '/thumbnail'); }
    function media(id, name, video, mediaURL) {
        const url = esc(mediaURL(id));
        return video ? `<div class="creation-media-video"><button type="button" class="btn-secondary" data-creation-video="${url}" aria-label="预览视频：${esc(name)}">▷ 预览视频</button><small>点击后加载</small></div>` : `<img loading="lazy" decoding="async" draggable="false" tabindex="0" src="${esc(thumbnailURL(mediaURL(id)))}" data-creation-full="${url}" alt="${esc(name)}" title="悬停或点击查看原图">`;
    }
    function bindMedia(element) {
        const loadImage = event => { const target = event.target.closest?.('[data-creation-full]'); if (target && !target.dataset.fullLoaded) { target.dataset.fullLoaded = 'true'; target.src = target.dataset.creationFull; } };
        element.addEventListener('mouseover', loadImage); element.addEventListener('focusin', loadImage);
        element.addEventListener('click', event => {
            loadImage(event);
            const button = event.target.closest?.('[data-creation-video]'); if (!button) return;
            event.preventDefault(); event.stopPropagation();
            const video = button.ownerDocument.createElement('video'); video.controls = true; video.playsInline = true; video.preload = 'metadata'; video.src = button.dataset.creationVideo;
            button.parentElement.replaceChildren(video); video.focus();
        });
    }
    function createController({ api, user, mediaURL, confirm = async () => false, openDrive = () => {}, onAttach = null }) {
        let element, epoch = 0, request = 0, folders = [], folder = null, assets = [], total = 0, selected = new Set(), search = '', kind = '', source = '', feedback = '', loading = false, busy = false, searchTimer, importItems = null;
        const pageSize = 48;
        const valid = (e, r) => epoch === e && request === r;
        function reset() { epoch++; request++; clearTimeout(searchTimer); folders=[];folder=null;assets=[];selected.clear();total=0;search='';kind='';source='';feedback='';loading=false;busy=false;importItems=null;if(element)element.innerHTML=''; }
        function mount(target) { element=target;if(target){bind();render();} }
        async function show(projectID) { const e=epoch; if (projectID !== undefined) { await loadFolders(); if(e!==epoch)return; folder=folders.find(f=>f.project_id===projectID);if(folder)await loadAssets(); } else { folder=null;await loadFolders(); } }
        async function loadFolders() {
            const e=epoch,r=++request;loading=true;feedback='';render();
            try { const data=await api('GET','/api/creation/asset-folders');if(!valid(e,r))return;folders=data.folders||[]; }
            catch(error){if(valid(e,r))feedback=error.message;}
            finally{if(valid(e,r)){loading=false;render();}}
        }
        async function loadAssets(more=false) {
            if(!folder)return;
            const e=epoch,r=++request,offset=more?assets.length:0;
            if(!more){assets=[];selected.clear();total=0;}loading=true;feedback='';render();
            const query=new URLSearchParams({project_id:folder.project_id,q:search,media:kind,source,limit:String(pageSize),offset:String(offset)});
            try { const data=await api('GET',`/api/creation/assets?${query}`);if(!valid(e,r))return;assets=more?[...assets,...(data.assets||[])]:data.assets||[];total=data.total??assets.length;folder.folder_id=data.folder_id; }
            catch(error){if(valid(e,r))feedback=error.message;}
            finally{if(valid(e,r)){loading=false;render();}}
        }
        function render() {
            if(!element)return;
            const focus=element.ownerDocument?.activeElement,focused=focus?.hasAttribute?.('data-cl-search'),start=focus?.selectionStart;
            element.innerHTML=`<section class="creation-library-browser" aria-label="${onAttach?'选择创作资产':'项目资产'}"><header class="creation-assets-toolbar"><div>${folder?'<button type="button" class="creation-text-button" data-cl-action="folders">← 全部文件夹</button>':''}<h3>${esc(folder?.name||'项目资产文件夹')}</h3><p>${folder?'图片以缩略图展示，悬停或点击查看原图；视频按需预览。':'按项目整理素材与作品，打开文件夹后加载资产。'}</p></div>${folder&&!onAttach?'<button class="btn-primary" data-cl-action="upload">上传图片 / 视频</button><button class="btn-secondary" data-cl-action="import">从网盘归入</button><button class="btn-secondary" data-cl-action="drive">打开网盘文件夹</button><input type="file" data-cl-upload multiple accept="image/png,image/jpeg,image/webp,video/mp4,video/webm" hidden>':''}<button class="creation-text-button" data-cl-action="refresh">刷新</button></header>
            <div class="creation-options cl-search"><input type="search" data-cl-search aria-label="${folder?'搜索资产':'搜索项目文件夹'}" placeholder="${folder?'搜索此文件夹的资产':'搜索项目文件夹'}" value="${esc(search)}">${folder?`<select data-cl-kind aria-label="媒体类型">${[['','全部类型'],['image/','图片'],['video/','视频']].map(([id,label])=>`<option value="${id}" ${kind===id?'selected':''}>${label}</option>`).join('')}</select><select data-cl-source aria-label="资产来源">${[['','全部来源'],['generated','生成'],['upload','上传'],['drive','网盘']].map(([id,label])=>`<option value="${id}" ${source===id?'selected':''}>${label}</option>`).join('')}</select>`:''}</div>
            <p class="creation-feedback" role="status">${esc(feedback)}${loading?' 正在加载…':''}</p>
            ${folder?`<div class="cl-selection"><label><input type="checkbox" data-cl-all ${assets.length&&selected.size===assets.length?'checked':''}> 选择已加载的 ${assets.length} 项</label><span data-cl-count>已选 ${selected.size} 项 · 共 ${total} 项</span><button class="btn-secondary" data-cl-action="${onAttach?'attach':'delete'}" ${!selected.size||busy?'disabled':''}>${onAttach?'引用选中资产':'删除选中资产'}</button></div><div class="creation-asset-grid">${assets.map(a=>`<article class="creation-asset"><label class="cl-select"><input type="checkbox" data-cl-select="${esc(a.id)}" ${selected.has(a.id)?'checked':''}>选择</label><div class="creation-asset-preview">${media(a.id,a.name,a.mime_type.startsWith('video/'),mediaURL)}</div><div class="creation-asset-info"><strong title="${esc(a.name)}">${esc(a.name)}</strong><span>${({generated:'生成',upload:'上传',drive:'网盘'})[a.source]||'网盘'} · ${(a.size/1024/1024).toFixed(1)} MB</span><a href="${esc(mediaURL(a.id))}" target="_blank" rel="noopener">打开 / 下载原文件</a></div></article>`).join('')||(!loading?'<p class="creation-muted">暂无匹配的资产。</p>':'')}</div>${assets.length<total?'<button class="btn-secondary cl-more" data-cl-action="more">加载更多</button>':''}`:`<div class="cl-folders">${folders.filter(f=>f.name.toLowerCase().includes(search.toLowerCase())).map(f=>`<button data-cl-action="folder" data-id="${esc(f.project_id)}"><span class="cl-folder-icon" aria-hidden="true">▱</span><strong>${esc(f.name)}</strong><small>${f.count} 个资产</small><span aria-hidden="true">→</span></button>`).join('')||(!loading?'<p>暂无匹配的文件夹。</p>':'')}</div>`}
            ${importItems?`<section class="creation-import"><h4>选择网盘文件</h4>${importItems.map(i=>`<button class="btn-secondary" data-cl-action="import-file" data-id="${esc(i.id)}">${esc(i.name)}</button>`).join('')||'<p>没有可归入的媒体文件。</p>'}<button data-cl-action="close-import">关闭</button></section>`:''}</section>`;
            if(busy||loading)element.querySelectorAll?.('[data-cl-action="more"], [data-cl-action="delete"], [data-cl-action="attach"], [data-cl-action="upload"], [data-cl-action="import"]').forEach(b=>b.disabled=true);
            if(focused){const input=element.querySelector('[data-cl-search]');input?.focus({preventScroll:true});input?.setSelectionRange(start,start);}
        }
        async function act(action,id) {
            if(action==='folder'){folder=folders.find(f=>f.project_id===id);search='';kind='';source='';await loadAssets();return;}
            if(action==='folders'){folder=null;search='';selected.clear();assets=[];importItems=null;await loadFolders();return;}
            if(action==='refresh'){await(folder?loadAssets():loadFolders());return;}
            if(action==='more'){await loadAssets(true);return;}
            if(action==='upload'){element.querySelector('[data-cl-upload]')?.click();return;}
            if(action==='drive'){await openDrive(folder.folder_id);return;}
            if(action==='close-import'){importItems=null;render();return;}
            const e=epoch,r=request,projectID=folder?.project_id;
            if(action==='delete'){
                if(!selected.size)return;if(selected.size>100)throw new Error('每次最多删除 100 项，请减少选择');
                const ids=[...selected];if(!await confirm(`删除选中的 ${ids.length} 个资产？网盘原文件也会删除。正在使用的参考图会保留并提示。`)||!valid(e,r))return;
                await api('POST','/api/creation/assets/delete',{ids});if(valid(e,r))await loadAssets();
            }else if(action==='attach'){const chosen=assets.filter(a=>selected.has(a.id));if(chosen.length)await onAttach(chosen);}
            else if(action==='import'){const data=await api('GET','/api/drive/tree');if(valid(e,r)){importItems=(data.flat_items||[]).filter(i=>i.type==='file'&&/^(image|video)\//.test(i.mime_type||'')&&!assets.some(a=>a.drive_item_id===i.id));render();}}
            else if(action==='import-file'){await api('POST','/api/creation/assets/import',{drive_item_id:id,project_id:projectID});if(valid(e,r)){importItems=importItems.filter(i=>i.id!==id);await loadAssets();}}
        }
        async function perform(fn){if(busy)return;const e=epoch;busy=true;try{await fn();}catch(error){if(epoch===e)feedback=error.message||'操作失败';}finally{if(epoch===e){busy=false;render();}}}
        function bind(){
            bindMedia(element);
            element.addEventListener('click',event=>{const target=event.target.closest('[data-cl-action]');if(target&&!target.disabled&&!busy)void perform(()=>act(target.dataset.clAction,target.dataset.id));});
            element.addEventListener('input',event=>{if(!event.target.hasAttribute('data-cl-search'))return;search=event.target.value;clearTimeout(searchTimer);if(folder){request++;searchTimer=setTimeout(()=>loadAssets(),250);}else render();});
            element.addEventListener('change',event=>{
                const el=event.target;
                if(el.hasAttribute('data-cl-select')){el.checked?selected.add(el.dataset.clSelect):selected.delete(el.dataset.clSelect);updateSelection();}
                if(el.hasAttribute('data-cl-all')){selected=el.checked?new Set(assets.map(a=>a.id)):new Set();element.querySelectorAll('[data-cl-select]').forEach(x=>x.checked=el.checked);updateSelection();}
                if(el.hasAttribute('data-cl-kind')){kind=el.value;void loadAssets();}
                if(el.hasAttribute('data-cl-source')){source=el.value;void loadAssets();}
                if(el.hasAttribute('data-cl-upload'))void perform(async()=>{
                    const e=epoch,r=request,projectID=folder.project_id;
                    for(const file of Array.from(el.files||[])){
                        if(file.size>64*1024*1024)throw new Error(`${file.name} 超过 64 MiB`);
                        const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error('文件读取失败'));reader.readAsDataURL(file);});
                        if(!valid(e,r))return;
                        await api('POST','/api/creation/assets',{name:file.name,mime_type:file.type,content:data.split(',')[1],project_id:projectID});
                        if(!valid(e,r))return;
                    }await loadAssets();
                });
            });
        }
        function updateSelection(){const count=element.querySelector('[data-cl-count]');if(count)count.textContent=`已选 ${selected.size} 项 · 共 ${total} 项`;const all=element.querySelector('[data-cl-all]');if(all){all.checked=!!assets.length&&selected.size===assets.length;all.indeterminate=!!selected.size&&selected.size<assets.length;}const action=element.querySelector(`[data-cl-action="${onAttach?'attach':'delete'}"]`);if(action)action.disabled=!selected.size||busy;}
        return {mount,show,reset};
    }
    return {media,thumbnailURL,bindMedia,createController};
});
