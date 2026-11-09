// Targeted VM test of the actual browser script. This is not a real network/browser test.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../workbench/static/knowledge.js'),'utf8');
const storage=new Map(),requests=[],notices=[];let committed=null;
function boot(selectors={},state={}){
  const listeners={},error={textContent:'',insertAdjacentHTML(){}};
  const context={window:{},document:{querySelector:s=>selectors[s]??(s==='#main'?null:error),querySelectorAll:()=>[],addEventListener:(type,fn)=>(listeners[type]??=[]).push(fn)},sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},localStorage:{getItem:()=>null,setItem(){}},crypto:require('node:crypto').webcrypto,TextEncoder,console};
  vm.createContext(context);vm.runInContext(source,context);
  context.window.KnowledgeWorkbench.configure({api:async(path,request)=>{requests.push({path,request});if(path==='knowledge/publish'){committed={revision:1,result:{snapshot_id:'stable_snapshot',manifest:{}}};throw Error('Simulated lost HTTP response');}if(path.startsWith('knowledge/operation/'))return {found:true,receipt:committed};if(path==='layout')return {};throw Error(path);},reload:async()=>{},notify:x=>notices.push(x)});
  context.window.KnowledgeWorkbench.update({project_id:'test-project',revision:0,...state});
  return {context,error,click:async(kw='publish',data={})=>{const b={dataset:{kw,...data},closest:()=>null,disabled:false};await listeners.click[0]({target:{closest:()=>b}});}};
}

async function checkCanvas(){
  const main={},canvas={clientWidth:340,clientHeight:320},count={},inspector={};
  const svg={style:{},setAttribute(name,value){this[name]=value;}};
  const node=id=>({id,name:id,kind:'entity',status:'confirmed'});
  const edge=(id,from,to)=>({id,name:id,kind:'relation',status:'confirmed',from,to,predicate:id,relation_type:'business'});
  const layout={'semantic:business:left':{x:1000,y:300},'semantic:business:right':{x:1260,y:300},
    'semantic:business:bottom':{x:1000,y:450},'semantic:business:spare':{x:1260,y:450}};
  const original=JSON.stringify(layout),requestCount=requests.length;
  const app=boot({'#main':main,'#kw-graph':svg,'#kw-canvas':canvas,'#kw-inspector':inspector,'#kw-graph-count':count,
    '[data-kw="expand-canvas"]':{focus(){}}},{project_id:'test-graph',layout,
    assets:[node('left'),node('right'),node('bottom'),node('spare'),edge('reverse','right','left'),
      edge('vertical','bottom','left'),edge('other','spare','bottom')]});
  const wb=app.context.window.KnowledgeWorkbench;
  main.innerHTML=wb.render('graph');
  wb.mount();
  assert.match(main.innerHTML,/aria-expanded="false"/);
  await app.click('expand-canvas');
  assert.match(main.innerHTML,/kw-graph-layout kw-canvas-expanded/);
  assert.match(main.innerHTML,/aria-expanded="true"[^>]*>收起画布/);
  await app.click('fit-canvas');
  const zoom=parseFloat(svg.style.width)/1494;
  assert.ok(zoom>0&&494*zoom<=canvas.clientWidth+.01);
  assert.ok(Math.abs(canvas.scrollLeft-976*zoom)<.01);
  assert.ok(Math.abs(canvas.scrollTop-276*zoom)<.01);
  await app.click('zoom',{delta:'0.15'});
  assert.ok(parseFloat(svg.style.width)/1494>zoom);
  await app.click('select',{id:'left'});
  assert.match(svg.innerHTML,/class="kw-edge-group related [^"]*" data-kw-edge="reverse"/);
  assert.match(svg.innerHTML,/class="kw-edge-group dimmed [^"]*" data-kw-edge="other"/);
  assert.match(svg.innerHTML,/M1260,345 C[^"]* 1214,345" marker-end="url\(#kw-arrow-focus\)"/);
  assert.match(svg.innerHTML,/M1105,450 C[^"]* 1105,394" marker-end="url\(#kw-arrow-focus\)"/);
  assert.match(inspector.innerHTML,/>left</);
  await app.click('expand-canvas');
  assert.match(main.innerHTML,/aria-expanded="false"[^>]*>展开画布/);
  assert.equal(JSON.stringify(layout),original);
  assert.equal(requests.length,requestCount);
  console.log('PASS: expand/collapse, fit and pan to distant nodes, manual zoom, focused directional edges, no layout writes');

  const grid=boot({'#main':main,'#kw-graph':svg,'#kw-canvas':canvas,'#kw-inspector':inspector,'#kw-graph-count':count},
    {project_id:'test-grid',assets:[node('a'),node('b'),node('c'),node('d')]});
  const gridWorkbench=grid.context.window.KnowledgeWorkbench;
  main.innerHTML=gridWorkbench.render('graph');
  gridWorkbench.mount();
  const expected=[['a',40,40],['b',360,40],['c',680,40],['d',40,225]];
  for(const [id,x,y] of expected){
    assert.match(svg.innerHTML,new RegExp(`data-kw-node="${id}"[^>]*transform="translate\\(${x},${y}\\)"`));
  }
  await grid.click('arrange');
  assert.equal(requests.at(-1).path,'layout');
  for(const [id,x,y] of expected){
    const position=requests.at(-1).request.positions['semantic:business:'+id];
    assert.equal(position.x,x);
    assert.equal(position.y,y);
  }
  console.log('PASS: default and explicit arrangement share the wider grid');
}
(async()=>{
 const first=boot();await first.click();assert.equal(requests.filter(x=>x.path==='knowledge/publish').length,1);assert.match(first.error.textContent,/提交结果尚未确认/);const stored=JSON.parse(storage.get('kw-pending:test-project'));assert.equal(stored.length,1);const id=stored[0][1].request.operation_id;
 const reopened=boot();assert.match(reopened.context.window.KnowledgeWorkbench.render('history'),/查询结果/);await reopened.click();assert.equal(requests.filter(x=>x.path==='knowledge/publish').length,1);assert.equal(requests.at(-1).path,'knowledge/operation/'+id);assert.equal(JSON.parse(storage.get('kw-pending:test-project')).length,0);console.log('PASS: lost response -> reopened script -> same operation receipt -> one publish write');
 await checkCanvas();
})().catch(e=>{console.error(e);process.exitCode=1;});
