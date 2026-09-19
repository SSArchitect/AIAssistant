'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const L=require('../web/static/js/creation-library.js');
const P=require('../web/static/js/creation-projects.js');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const mediaURL=id=>`/api/creation/assets/${id}/content?account_session=test`;
function element(){
 const handlers={};const el={innerHTML:'',querySelector:()=>null,querySelectorAll:()=>[],addEventListener(name,fn){(handlers[name]??=[]).push(fn);}};
 return {el,emit(name,target){for(const fn of handlers[name]||[])fn({target,preventDefault(){},stopPropagation(){}});},click(action,id=''){this.emit('click',{closest:selector=>selector==='[data-cl-action]'?{dataset:{clAction:action,id},disabled:false}:selector==='[data-cp-action]'?{dataset:{cpAction:action,id},disabled:false}:null});},input(key,value){this.emit('input',{hasAttribute:name=>name===key,value});},select(id,checked=true){this.emit('change',{hasAttribute:key=>key==='data-cl-select',dataset:{clSelect:id},checked});}};
}
const asset=(id='a')=>({id,name:`${id}.png`,mime_type:'image/png',size:1000,source:'upload'});
const folders=[{project_id:'p',name:'菌菇奇旅',folder_id:'fp',count:60},{project_id:'',name:'未归属资产',folder_id:'root',count:0}];

test('media markup uses thumbnails and never attaches video src before user intent',()=>{
 const url=mediaURL('a');assert.equal(L.thumbnailURL(url),'/api/creation/assets/a/thumbnail?account_session=test');
 const img=L.media('a','<img>',false,mediaURL);assert.match(img,/src="\/api\/creation\/assets\/a\/thumbnail/);assert.match(img,/loading="lazy"/);assert.doesNotMatch(img,/src="[^\"]*\/content/);assert.match(img,/&lt;img&gt;/);
 const video=L.media('v','video',true,mediaURL);assert.doesNotMatch(video,/<video|src=/);assert.match(video,/预览视频/);
});
test('media loads original on hover or keyboard focus and video on explicit click only',()=>{
 const h=element();L.bindMedia(h.el);const img={dataset:{creationFull:'original'},src:'thumb'};
 h.emit('mouseover',{closest:s=>s==='[data-creation-full]'?img:null});assert.equal(img.src,'original');
 const video={focus(){this.focused=true;}},parent={replaceChildren(node){this.child=node;}},button={dataset:{creationVideo:'video-url'},parentElement:parent,ownerDocument:{createElement:()=>video}};
 assert.equal(parent.child,undefined);h.emit('click',{closest:s=>s==='[data-creation-video]'?button:null});assert.equal(parent.child,video);assert.equal(video.src,'video-url');assert.equal(video.controls,true);assert.equal(video.focused,true);
});
test('folder-first browsing fetches no assets until opened and uses server pagination/search',async()=>{
 const calls=[],h=element();const c=L.createController({user:()=> 'alice',mediaURL,api:async(method,path)=>{calls.push(path);return path.includes('asset-folders')?{folders}:{assets:[asset()],total:60,folder_id:'fp'};}});c.mount(h.el);await c.show();
 assert.deepEqual(calls,['/api/creation/asset-folders']);assert.doesNotMatch(h.el.innerHTML,/<img|<video/);assert.match(h.el.innerHTML,/菌菇奇旅/);
 h.click('folder','p');await tick();assert.match(calls[1],/project_id=p/);assert.match(calls[1],/limit=48/);assert.match(h.el.innerHTML,/加载更多/);
 h.click('more');await tick();assert.match(calls[2],/offset=1/);
 h.click('folders');await tick();assert.doesNotMatch(h.el.innerHTML,/<img|<video/);c.reset();
});
test('multi-select delete requires confirmation, sends exact IDs and retains assets after failure',async()=>{
 const calls=[],h=element();let approved=false,fail=false;
 const c=L.createController({user:()=> 'alice',mediaURL,confirm:async()=>approved,api:async(method,path,body)=>{calls.push({method,path,body});if(path.includes('asset-folders'))return {folders};if(path.endsWith('/delete')){if(fail)throw new Error('资产仍被项目引用');return {deleted:body.ids};}return {assets:[asset('a'),asset('b')],total:2};}});c.mount(h.el);await c.show('p');
 h.select('a');h.select('b');h.click('delete');await tick();assert.equal(calls.filter(x=>x.method==='POST').length,0);
 approved=true;fail=true;h.click('delete');await tick();assert.deepEqual(calls.find(x=>x.method==='POST').body,{ids:['a','b']});assert.match(h.el.innerHTML,/资产仍被项目引用/);assert.match(h.el.innerHTML,/a.png/);assert.match(h.el.innerHTML,/已选 2 项/);c.reset();
});
test('late folder or asset responses cannot repopulate a reset account',async()=>{
 const h=element();let resolve;
 const c=L.createController({user:()=> 'alice',mediaURL,api:()=>new Promise(r=>resolve=r)});c.mount(h.el);const pending=c.show();c.reset();resolve({folders});await pending;assert.equal(h.el.innerHTML,'');c.reset();
});
test('asset picker uses project folders and attaches all selected metadata',async()=>{
 const h=element();let chosen;
 const c=L.createController({user:()=> 'alice',mediaURL,onAttach:async a=>chosen=a,api:async(_,url)=>url.includes('asset-folders')?{folders}:{assets:[asset('a'),asset('b')],total:2}});c.mount(h.el);await c.show('p');h.select('a');h.select('b');h.click('attach');await tick();assert.deepEqual(chosen.map(a=>a.id),['a','b']);assert.doesNotMatch(h.el.innerHTML,/删除选中资产/);c.reset();
});
test('project library first render requests only lightweight project list and replaces dropdown',async()=>{
 const h=element(),calls=[];
 const c=P.createController({user:()=> 'alice',mediaURL,api:async(_,url)=>{calls.push(url);return {projects:[{id:'p',name:'菌菇奇旅',revision:1}]};}});c.mount(h.el);c.setVisible(true);await tick();c.setVisible(false);
 assert.deepEqual(calls,['/api/creation/projects']);assert.match(h.el.innerHTML,/菌菇奇旅/);assert.match(h.el.innerHTML,/data-cp-search/);assert.doesNotMatch(h.el.innerHTML,/data-cp-project|<img|<video/);assert.match(h.el.innerHTML,/重命名/);assert.match(h.el.innerHTML,/删除/);c.reset();
});
test('project rename sends revision, and delete cancellation sends no mutation',async()=>{
 const h=element(),calls=[];const p={id:'p',name:'old',revision:3,document:JSON.stringify({asset_ids:[],states:{},messages:[],plan:{nodes:[],questions:[]}})};
 const c=P.createController({user:()=> 'alice',mediaURL,confirm:async()=>false,api:async(method,url,body)=>{calls.push({method,url,body});if(method==='PATCH')return {project:{...p,name:body.name,revision:4}};return {projects:[p],project:p,runs:[]};}});c.mount(h.el);await c.refresh();
 h.click('rename-project','p');await tick();h.input('data-cp-rename','新名字');h.click('save-rename','p');await tick();assert.deepEqual(calls.find(c=>c.method==='PATCH').body,{name:'新名字',revision:3});assert.match(h.el.innerHTML,/新名字/);
 h.click('delete-project','p');await tick();assert.equal(calls.some(c=>c.method==='DELETE'),false);c.reset();
});
test('opening a project scopes run requests and never fetches the global asset collection',async()=>{
 const h=element(),calls=[];const p={id:'p',name:'project',revision:3,document:JSON.stringify({asset_ids:['a'],states:{},messages:[],plan:{nodes:[],questions:[]}})};
 const c=P.createController({user:()=> 'alice',mediaURL,api:async(_,url)=>{calls.push(url);return {projects:[p],project:p,runs:[],assets:[asset()]};}});c.mount(h.el);await c.refresh();h.click('open-project','p');await tick();await tick();
 assert.ok(calls.includes('/api/creation/runs?project_id=p'));assert.ok(calls.includes('/api/creation/assets?ids=a'));assert.ok(!calls.includes('/api/creation/assets'));assert.match(h.el.innerHTML,/项目列表/);c.reset();
});
test('new module loads before controllers and participates in syntax checks',()=>{
 const html=fs.readFileSync('web/index.html','utf8');assert.ok(html.indexOf('/static/js/creation-library.js')<html.indexOf('/static/js/creation-projects.js'));assert.match(fs.readFileSync('scripts/test.sh','utf8'),/node --check web\/static\/js\/creation-library.js/);
});
