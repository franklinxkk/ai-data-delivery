// Tests of the actual UI event handlers with a controlled layout helper.
// These prove state/write behavior, not browser rendering or layout geometry.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../workbench/static/knowledge.js'),'utf8');
const clone=value=>JSON.parse(JSON.stringify(value));
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const node=id=>({id,name:id,kind:'entity',status:'confirmed',definition:'Definition of '+id});
const edge=(id,from,to)=>({id,name:id,kind:'relation',status:'confirmed',from,to,predicate:id,relation_type:'business'});
const assets=[node('left'),node('right'),node('bottom'),node('spare'),edge('reverse','right','left'),edge('vertical','bottom','left'),edge('other','spare','bottom')];
const savedLayout={
  'semantic:business:left':{x:1000,y:300},'semantic:business:right':{x:1260,y:300},
  'semantic:business:bottom':{x:1000,y:450},'semantic:business:spare':{x:1260,y:450},
  'semantic:all:left':{x:80,y:90},'semantic:all:right':{x:450,y:90},
  'semantic:all:bottom':{x:80,y:320},'semantic:all:spare':{x:450,y:320}
};
function makePlan(input,positions){
  const nodeById=new Map(input.nodes.map(n=>[n.id,n]));
  const routes={};
  for(const e of input.edges){
    const a=positions[e.from],b=positions[e.to],na=nodeById.get(e.from),nb=nodeById.get(e.to);
    const start={x:a.x+na.width,y:a.y+na.height/2},end={x:b.x,y:b.y+nb.height/2};
    routes[e.id]={points:[start,end],label:e.label?{x:(start.x+end.x)/2-45,y:(start.y+end.y)/2-28,width:90,height:24,text:e.label,lines:[e.label]}:null};
  }
  const boxes=input.nodes.map(n=>({...positions[n.id],width:n.width,height:n.height}));
  const bounds=boxes.length?{
    left:Math.min(...boxes.map(p=>p.x))-30,top:Math.min(...boxes.map(p=>p.y))-30,
    right:Math.max(...boxes.map(p=>p.x+p.width))+30,bottom:Math.max(...boxes.map(p=>p.y+p.height))+30
  }:{left:0,top:0,right:1,bottom:1};
  return {positions:clone(positions),routes,bounds};
}
function createHelper(){
  const calls={layout:[],route:[]};
  const controls={wait:null,error:null};
  const helper={
    async layout(input){
      calls.layout.push(clone(input));
      if(controls.wait)await controls.wait.promise;
      if(controls.error)throw controls.error;
      const points=[{x:75,y:230},{x:420,y:80},{x:730,y:250},{x:390,y:420}];
      const positions=Object.fromEntries(input.nodes.map((n,i)=>[n.id,(input.fixed||[]).includes(n.id)?input.positions[n.id]:points[i%points.length]]));
      return makePlan(input,positions);
    },
    route(input){calls.route.push(clone(input));return makePlan(input,input.positions);}
  };
  return {helper,calls,controls};
}
function boot({state={},helper=createHelper(),api,session=new Map(),local=new Map()}={}){
  const listeners={},requests=[],notices=[];
  const main={innerHTML:''},canvas={clientWidth:820,clientHeight:500,scrollLeft:0,scrollTop:0};
  const svg={style:{},dataset:{},innerHTML:'',setAttribute(name,value){this[name]=value;},querySelectorAll:()=>[],createSVGPoint(){return {x:0,y:0,matrixTransform(){return {x:this.x,y:this.y};}};},getScreenCTM(){return {inverse(){return {};}};}};
  const inspector={innerHTML:''},count={textContent:''},error={textContent:'',insertAdjacentHTML(){}};
  const controls={arrange:{disabled:false,textContent:'自动布局'},expand:{focus(){}}};
  const selectors={'#main':main,'#kw-graph':svg,'#kw-canvas':canvas,'#kw-inspector':inspector,'#kw-graph-count':count,'#kw-publish-error':error,
    '[data-kw="arrange"]':controls.arrange,'[data-kw="expand-canvas"]':controls.expand,'[data-kw="more"]':{disabled:false}};
  const context={window:{SemanticGraphLayout:helper.helper},document:{querySelector:s=>selectors[s]??null,querySelectorAll:()=>[],addEventListener:(type,fn)=>(listeners[type]??=[]).push(fn)},
    sessionStorage:{getItem:k=>session.get(k)||null,setItem:(k,v)=>session.set(k,v)},localStorage:{getItem:k=>local.get(k)||null,setItem:(k,v)=>local.set(k,v)},
    crypto:require('node:crypto').webcrypto,TextEncoder,console};
  vm.createContext(context);vm.runInContext(source,context);
  const wb=context.window.KnowledgeWorkbench;
  wb.configure({api:async(path,request)=>{requests.push({path,request:request===undefined?undefined:clone(request)});if(api)return api(path,request);if(path==='layout')return {};throw Error('Unexpected API '+path);},reload:async()=>{},notify:message=>notices.push(message),go:page=>{main.innerHTML=wb.render(page);wb.mount();}});
  wb.update({project_id:'vm-project',revision:7,...clone(state)});
  return {wb,main,canvas,svg,inspector,count,error,controls,requests,notices,helper,session,local,
    mount(page='graph'){main.innerHTML=wb.render(page);wb.mount();},
    async click(kw='publish',data={}){const button={dataset:{kw,...data},closest:()=>null,disabled:false};await listeners.click[0]({target:{closest:selector=>selector==='[data-kw]'?button:null}});},
    async dragNode(id,dx,dy){const selected={dataset:{kwNode:id},classList:{add(){}}};const target={classList:{contains:()=>false},closest:selector=>selector==='#kw-canvas'?canvas:selector==='[data-kw-node]'?selected:null};const start={target,clientX:100,clientY:100,preventDefault(){}};for(const fn of listeners.pointerdown||[])fn(start);for(const fn of listeners.pointermove||[])fn({target,clientX:100+dx,clientY:100+dy});for(const fn of listeners.pointerup||[])await fn({target,clientX:100+dx,clientY:100+dy});},
    change(id,value){const element={id,value,dataset:{},matches:()=>false,closest:()=>null};for(const fn of listeners.change||[])fn({target:element});},
    input(id,value){const element={id,value,dataset:{},matches:()=>false,closest:()=>null,hasAttribute:()=>false};for(const fn of listeners.input||[])fn({target:element});},
    view(){return JSON.parse(local.get('kw-view:'+(state.project_id||'vm-project'))||'{}');}
  };
}
function positionsOnScreen(svg){
  return Object.fromEntries([...svg.innerHTML.matchAll(/data-kw-node="([^"]+)"[^>]*transform="translate\(([-\d.]+),([-\d.]+)\)"/g)].map(m=>[m[1],{x:Number(m[2]),y:Number(m[3])}]));
}
async function checkReadOnlyCanvasActions(){
  const initial=clone(savedLayout),initialAssets=clone(assets);
  const app=boot({state:{project_id:'canvas-actions',assets,layout:initial}});app.mount();
  const before=positionsOnScreen(app.svg);
  assert.match(app.main.innerHTML,/aria-expanded="false"[^>]*>展开画布/);
  await app.click('expand-canvas');
  assert.match(app.main.innerHTML,/kw-canvas-expanded/);
  assert.match(app.main.innerHTML,/aria-expanded="true"[^>]*>退出专注/);
  assert.equal(app.view().inspector,false);
  await app.click('toggle-inspector');assert.match(app.main.innerHTML,/kw-inspector-visible/);
  await app.click('toggle-inspector');assert.equal(app.view().inspector,false);
  await app.click('fit-canvas');
  const plan=app.helper.calls.route.at(-1),bounds=makePlan(plan,plan.positions).bounds,zoom=app.view().zoom;
  assert.ok(zoom>0&&(bounds.right-bounds.left)*zoom<=app.canvas.clientWidth-32+.01);
  assert.ok((bounds.bottom-bounds.top)*zoom<=app.canvas.clientHeight-32+.01);
  assert.equal(app.canvas.scrollLeft,0);assert.equal(app.canvas.scrollTop,0);
  assert.ok(Number.isFinite(Number(app.svg.dataset.offsetX))&&Number.isFinite(Number(app.svg.dataset.offsetY)));
  await app.click('zoom',{delta:'0.15'});assert.ok(app.view().zoom>zoom);
  await app.click('select',{id:'left'});
  assert.match(app.svg.innerHTML,/kw-edge-group\s+related [^"]*" data-kw-edge="reverse"/);
  assert.match(app.svg.innerHTML,/kw-edge-group\s+dimmed [^"]*" data-kw-edge="other"/);
  assert.match(app.inspector.innerHTML,/>left</);
  assert.equal(app.view().inspector,true);
  await app.click('expand-canvas');assert.match(app.main.innerHTML,/aria-expanded="false"[^>]*>展开画布/);
  assert.deepEqual(positionsOnScreen(app.svg),before);
  assert.deepEqual(initial,savedLayout);assert.deepEqual(assets,initialAssets);
  assert.equal(app.requests.length,0);assert.equal(app.helper.calls.layout.length,0);
  console.log('PASS: focus/exit, details, fit, zoom and selection preserve saved layout and semantic assets');
}
async function checkSavedArrangementAndUndo(){
  const app=boot({state:{project_id:'arrangement',assets,layout:savedLayout}});app.mount();
  const before=positionsOnScreen(app.svg);
  await app.click('fix',{id:'left'});
  assert.equal(app.requests.length,1);assert.deepEqual(app.requests[0].request.positions,savedLayout);
  await app.click('arrange');
  assert.equal(app.helper.calls.layout.length,1);
  const input=app.helper.calls.layout[0];assert.deepEqual(input.fixed,['left']);
  assert.equal(input.width,app.canvas.clientWidth);assert.equal(input.height,app.canvas.clientHeight);
  assert.deepEqual(input.nodes.map(n=>n.id),['left','right','bottom','spare']);
  assert.deepEqual(input.edges.map(e=>e.id),['reverse','vertical','other']);
  assert.equal(app.requests.length,2);assert.equal(app.requests[1].path,'layout');
  const written=app.requests[1].request.positions;
  assert.deepEqual(written['semantic:business:left'],savedLayout['semantic:business:left']);
  assert.deepEqual(written['semantic:business:right'],{x:420,y:80});
  assert.deepEqual(written['semantic:all:right'],savedLayout['semantic:all:right']);
  assert.deepEqual(positionsOnScreen(app.svg).right,{x:420,y:80});
  assert.ok(app.notices.some(x=>x.includes('自动布局已保存')));
  await app.click('undo-layout');
  assert.equal(app.requests.length,3);assert.deepEqual(app.requests[2].request.positions,savedLayout);
  assert.deepEqual(positionsOnScreen(app.svg),before);
  console.log('PASS: automatic arrangement delegates topology and fixed nodes, saves positions, and undo restores the prior layout');
}
async function checkFailedWriteAndRetry(){
  let rejectWrite=true;
  const app=boot({state:{project_id:'failed-write',assets,layout:savedLayout},api:async(path)=>{assert.equal(path,'layout');if(rejectWrite)throw Error('Storage unavailable');return {};}});app.mount();
  const before=positionsOnScreen(app.svg);
  await app.click('arrange');
  assert.ok(app.notices.some(x=>x.includes('Storage unavailable')));
  assert.ok(!app.notices.some(x=>x.includes('自动布局已保存')));
  assert.deepEqual(positionsOnScreen(app.svg),before);
  assert.equal(app.controls.arrange.disabled,false);
  rejectWrite=false;await app.click('arrange');
  assert.equal(app.helper.calls.layout.length,2);assert.equal(app.requests.length,2);
  assert.deepEqual(app.requests[0].request.positions,app.requests[1].request.positions);
  assert.deepEqual(positionsOnScreen(app.svg).right,{x:420,y:80});
  await app.click('undo-layout');assert.deepEqual(app.requests[2].request.positions,savedLayout);
  console.log('PASS: failed layout persistence retains the original positions and supports retry with correct undo');
}
async function checkStaleCalculation(){
  const helper=createHelper();helper.controls.wait=deferred();
  const app=boot({state:{project_id:'stale-calculation',assets,layout:savedLayout},helper});app.mount();
  const pending=app.click('arrange');await tick();
  assert.equal(helper.calls.layout.length,1);assert.equal(app.controls.arrange.disabled,true);
  app.change('kw-canvas-view','all');const allBefore=positionsOnScreen(app.svg);
  helper.controls.wait.resolve();await pending;
  assert.equal(app.requests.length,0,'Changing graph scope while layout computes must discard the old result before persistence');
  assert.equal(app.view().view,'all');assert.deepEqual(positionsOnScreen(app.svg),allBefore);
  assert.ok(app.notices.some(x=>x.includes('图谱范围已变化')));
  assert.equal(app.controls.arrange.disabled,false);
  helper.controls.wait=null;await app.click('arrange');
  assert.equal(app.requests.length,1);assert.deepEqual(app.requests[0].request.positions['semantic:business:right'],savedLayout['semantic:business:right']);
  assert.deepEqual(app.requests[0].request.positions['semantic:all:right'],{x:420,y:80});
  console.log('PASS: an asynchronous layout for a previous view cannot write stale positions into the current view');
}
async function checkAutomaticPreview(){
  const app=boot({state:{project_id:'preview',assets}});app.mount();await tick();
  assert.equal(app.helper.calls.layout.length,1);assert.equal(app.requests.length,0);
  assert.deepEqual(positionsOnScreen(app.svg).right,{x:420,y:80});
  await app.click('select',{id:'left'});await app.click('fit-canvas');
  assert.equal(app.helper.calls.layout.length,1,'Ordinary redraws must reuse the layout, not move the nodes again');
  assert.equal(app.requests.length,0);
  console.log('PASS: an unsaved graph gets one automatic preview without silently persisting layout');
}
async function checkNewViewPreviewAfterPendingCalculation(){
  const helper=createHelper();helper.controls.wait=deferred();
  const withMetric=[...assets,{id:'metric',name:'Metric',kind:'metric',status:'confirmed'}];
  const app=boot({state:{project_id:'new-view-preview',assets:withMetric,layout:savedLayout},helper});
  // Keep positions only in business so the destination view needs an initial preview.
  const business=Object.fromEntries(Object.entries(savedLayout).filter(([key])=>key.startsWith('semantic:business:')));
  app.wb.update({project_id:'new-view-preview',revision:7,assets:withMetric,layout:business});app.mount();
  const pending=app.click('arrange');await tick();app.change('kw-canvas-view','all');
  assert.equal(helper.calls.layout.length,1,'The pending calculation should not launch a competing layout');
  helper.controls.wait.resolve();await pending;await tick();
  assert.equal(app.requests.length,0,'The departed view cannot persist its obsolete arrangement');
  assert.equal(helper.calls.layout.length,2,'The new view must still receive its initial automatic preview');
  assert.ok(helper.calls.layout[1].nodes.some(n=>n.id==='metric'));
  assert.ok('metric' in positionsOnScreen(app.svg));
  assert.deepEqual(positionsOnScreen(app.svg).right,{x:420,y:80});
  console.log('PASS: switching to an unsaved view during layout still starts that new view preview after the old result is discarded');
}
async function checkFirstDragAndPinPersistence(){
  const dragApp=boot({state:{project_id:'first-drag',assets}});dragApp.mount();await tick();
  const preview=positionsOnScreen(dragApp.svg);await dragApp.dragNode('right',40,25);
  assert.equal(dragApp.requests.length,1);
  const written=dragApp.requests[0].request.positions;
  for(const [id,pos] of Object.entries(preview))assert.deepEqual(written['semantic:business:'+id],id==='right'?{x:pos.x+40,y:pos.y+25}:pos);
  const reopened=boot({state:{project_id:'first-drag',assets,layout:written},local:dragApp.local});reopened.mount();
  assert.deepEqual(positionsOnScreen(reopened.svg),Object.fromEntries(Object.entries(preview).map(([id,pos])=>[id,id==='right'?{x:pos.x+40,y:pos.y+25}:pos])));
  assert.equal(reopened.helper.calls.layout.length,0,'Reopening should preserve every visible node, not auto-layout the siblings');
  let fail=true;
  const pinApp=boot({state:{project_id:'first-pin',assets},api:async(path)=>{assert.equal(path,'layout');if(fail)throw Error('Pin storage unavailable');return {};}});pinApp.mount();await tick();
  const pinPreview=positionsOnScreen(pinApp.svg);await pinApp.click('fix',{id:'left'});
  assert.ok(!pinApp.view().fixed?.includes('left'));assert.deepEqual(positionsOnScreen(pinApp.svg),pinPreview);
  fail=false;await pinApp.click('fix',{id:'left'});assert.ok(pinApp.view().fixed.includes('left'));
  for(const [id,pos] of Object.entries(pinPreview))assert.deepEqual(pinApp.requests[1].request.positions['semantic:business:'+id],pos);
  console.log('PASS: first drag/pin persists the complete automatic preview; reload preserves siblings and failed pin does not mark fixed');
}
async function checkPublishRecovery(){
  const session=new Map(),requests=[];let committed=null;
  const api=async(path,request)=>{requests.push({path,request});if(path==='knowledge/publish'){committed={revision:1,result:{snapshot_id:'stable_snapshot',manifest:{}}};throw Error('Simulated lost HTTP response');}if(path.startsWith('knowledge/operation/'))return {found:true,receipt:committed};throw Error(path);};
  const first=boot({state:{project_id:'publish-recovery'},api,session});await first.click();
  assert.equal(requests.filter(x=>x.path==='knowledge/publish').length,1);assert.match(first.error.textContent,/提交结果尚未确认/);
  const stored=JSON.parse(session.get('kw-pending:publish-recovery'));assert.equal(stored.length,1);const id=stored[0][1].request.operation_id;
  const reopened=boot({state:{project_id:'publish-recovery'},api,session});assert.match(reopened.wb.render('history'),/查询结果/);await reopened.click();
  assert.equal(requests.filter(x=>x.path==='knowledge/publish').length,1);assert.equal(requests.at(-1).path,'knowledge/operation/'+id);
  assert.equal(JSON.parse(session.get('kw-pending:publish-recovery')).length,0);
  console.log('PASS: lost publish response -> reopened script -> same operation receipt -> one publish write');
}
async function checkRuleFieldSearch(){
  const rules=[{...node('dispatch'),kind:'rule',name:'工单派发',properties:{condition:'需要派单',requirement:'唯一匹配',execution:{sql:'SECRET_EXECUTION'}}},
    {...node('outcome'),kind:'rule',name:'成果判断',scope:'单一账簿',properties:{condition:'排除缺考',requirement:'达到70%',knowledge_gaps:['完成时点未知']}}];
  const app=boot({state:{project_id:'semantic-search',assets:rules}});app.mount();
  app.change('kw-canvas-view','all');await tick();
  for(const [query,id] of [['派单','dispatch'],['70%','outcome'],['缺考','outcome'],['单一账簿','outcome'],['完成时点','outcome']]){
    app.input('kw-graph-search',query);await tick();
    assert.deepEqual(Object.keys(positionsOnScreen(app.svg)),[id]);
  }
  app.input('kw-graph-search','SECRET_EXECUTION');await tick();assert.deepEqual(positionsOnScreen(app.svg),{});
  assert.equal(app.requests.length,0);
  console.log('PASS: graph search discovers rule fields, scope and declared gaps, without indexing execution code');
}
(async()=>{
  await checkPublishRecovery();await checkReadOnlyCanvasActions();await checkSavedArrangementAndUndo();
  await checkFailedWriteAndRetry();await checkStaleCalculation();await checkAutomaticPreview();
  await checkNewViewPreviewAfterPendingCalculation();await checkFirstDragAndPinPersistence();
  await checkRuleFieldSearch();
})().catch(error=>{console.error(error);process.exitCode=1;});
