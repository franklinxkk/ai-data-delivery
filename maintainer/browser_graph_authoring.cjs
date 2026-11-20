const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {spawn}=require('node:child_process');
const [out]=process.argv.slice(2);
if(!out)throw Error('Usage: node maintainer/browser_graph_authoring.cjs <evidence directory>');
function start(){
  const directory=fs.mkdtempSync(path.join(require('node:os').tmpdir(),'ontology-graph-'));
  const server=spawn(process.env.PYTHON||'python',['-u','scripts/start.py','--project',path.join(directory,'project'),'--language','zh','--ddl','examples/semantic-workbench/transport.sql'],{windowsHide:true});
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{server.kill();reject(Error('Workbench startup timed out'));},30000);
    let output='';
    server.stdout.on('data',chunk=>{output+=chunk;const match=output.match(/http:\/\/127\.0\.0\.1:\d+/);if(match){clearTimeout(timer);resolve({server,origin:match[0]});}});
    server.stderr.on('data',chunk=>{output+=chunk;});
    server.on('error',err=>{clearTimeout(timer);reject(err);});
    server.on('exit',()=>{clearTimeout(timer);reject(Error(output));});
  });
}
async function api(page,route,payload){
  return page.evaluate(async({route,payload})=>{
    const headers={'X-Workbench-Token':document.querySelector('meta[name="session-token"]').content};
    if(payload)headers['Content-Type']='application/json';
    const response=await fetch('/api/knowledge/'+route,{method:payload?'POST':'GET',headers,body:payload?JSON.stringify(payload):undefined});
    const body=await response.json();if(!response.ok)throw Error(JSON.stringify(body));return body;
  },{route,payload});
}
async function write(page,route,payload){
  const {revision}=await api(page,'revision');
  return api(page,route,{revision,operation_id:require('node:crypto').randomUUID(),...payload});
}
(async()=>{
  fs.mkdirSync(out,{recursive:true});
  const {server,origin}=await start();
  let browser;
  try{
    browser=await chromium.launch({executablePath:process.env.BROWSER_PATH||undefined,headless:true});
    const context=await browser.newContext({viewport:{width:1440,height:960}}),page=await context.newPage();
    const errors=[];context.on('weberror',event=>errors.push(event.error().message));
    await page.goto(origin+'/?lang=zh#graph');await page.waitForLoadState('networkidle');
    const initial=await api(page,'state');
    const foreign=initial.assets.filter(a=>a.relation_type==='physical_fk');
    assert.ok(foreign.length&&foreign.every(a=>a.status==='draft'));
    assert.equal(initial.assets.filter(a=>a.kind==='relation'&&a.relation_type==='business').length,0,'Use a fresh project');
    const stamp=Date.now(),start='order'+stamp,other='inspected'+stamp,relation='edge'+stamp;
    const entity=(id,name,definition)=>({id,kind:'entity',name,definition,domain:'整改',scope:'试点'});
    const memo='整改工单上登记的责任单位负责整改。';
    const imported=await write(page,'import',{filename:'整改职责说明.txt',text:memo,domain:'整改',scope:'试点'});
    const source=imported.result.source_id,fragment=imported.result.parsed.fragments.find(f=>f.text.includes(memo));
    const evidence=[{source_id:source,revision:1,fragment_id:fragment.id,quote:memo}];
    await write(page,'edit',{asset:[{...entity(start,'工单','整改工单'),evidence},
      {...entity(other,'企业','被检查单位'),evidence},{...entity('owner'+stamp,'企业','整改责任单位'),evidence}]});
    await page.reload();await page.waitForLoadState('networkidle');
    await page.locator('[data-kw=create][data-kind=relation]').click();
    const form=page.locator('#kw-form');
    await form.locator('[data-field=name]').fill('流转至复核人');
    await form.locator('[data-field=predicate]').fill('提交复核');
    await form.locator('[data-field=from]').selectOption(start);
    const candidates=await form.locator('[data-field=to] option').allTextContents();
    assert.ok(candidates.some(s=>s.includes('被检查单位')&&s.includes('整改职责说明.txt')&&s.includes(other)));
    assert.ok(candidates.some(s=>s.includes('整改责任单位')&&s.includes('整改职责说明.txt')&&s.includes('owner'+stamp)));
    const creator=form.locator('[data-end-create=to]');await creator.locator('summary').click();
    await creator.locator('input').fill('复核人');await creator.locator('button').click();
    await page.waitForFunction(()=>document.querySelector('[data-field=to]').selectedOptions[0]?.text.includes('复核人'));
    const created=await form.locator('[data-field=to]').inputValue();
    assert.equal(await form.locator('[data-field=name]').inputValue(),'流转至复核人');
    await form.locator('button[value=draft]').click();await page.locator('#kw-dialog').waitFor({state:'hidden'});
    const saved=await api(page,'state'),localEdge=saved.assets.find(a=>a.name==='流转至复核人');
    assert.equal(localEdge.to,created);assert.equal(localEdge.from,start);assert.equal(saved.assets.find(a=>a.id===created).status,'draft');
    assert.equal(new URL(page.url()).searchParams.get('focus'),localEdge.id);
    await page.locator('[data-kw=expand-canvas]').click();
    await page.locator('[data-kw=toggle-inspector]').click();
    await page.locator('#kw-inspector [data-kw=edit]').click();
    await form.locator('[data-field=definition]').fill('未提交的描述');
    await form.locator('details').filter({has:page.locator('#kw-cite-source')}).locator('summary').click();
    await form.locator('#kw-cite-source').selectOption(source);
    await form.locator('#kw-cite-fragment').selectOption(fragment.id);
    const change=await write(page,'edit',{asset:{id:relation,kind:'relation',name:'工单整改责任',from:start,to:'owner'+stamp,
      relation_type:'business',predicate:'由该单位整改',definition:memo,domain:'整改',scope:'试点',evidence},confirm:true});
    const link=form.locator('#kw-external-change a').filter({hasText:'查看刚改的关系'});
    await link.waitFor({timeout:15000});await page.screenshot({path:path.join(out,'unsaved-external-change.png')});
    const opened=context.waitForEvent('page');await link.click();const focused=await opened;
    await focused.waitForLoadState('networkidle');
    assert.equal(new URL(focused.url()).searchParams.get('revision'),String(change.revision));
    for(const id of [start,'owner'+stamp])assert.ok(await focused.locator('[data-kw-node="'+id+'"]').isVisible());
    await focused.locator('[data-kw-edge="'+relation+'"] .kw-edge-label').waitFor({state:'visible'});
    assert.ok((await focused.locator('#kw-inspector').innerText()).includes(memo));
    await focused.locator('#kw-inspector [data-kw=source]').click();
    assert.ok((await focused.locator('.kw-fragment.target').innerText()).includes(memo));
    await focused.getByRole('button',{name:'关闭原文'}).click();
    await focused.reload();await focused.waitForLoadState('networkidle');
    await focused.screenshot({path:path.join(out,'focused-relation.png')});
    assert.equal(await form.locator('[data-field=definition]').inputValue(),'未提交的描述');
    assert.equal(await form.locator('#kw-cite-quote').inputValue(),memo);
    await page.bringToFront();await form.locator('button[value=draft]').click();
    await page.locator('#kw-conflict').getByRole('button').waitFor();
    assert.equal(await form.locator('[data-field=definition]').inputValue(),'未提交的描述');
    await form.locator('[data-kw=close-dialog]').first().click();
    await focused.bringToFront();
    const dense=Array.from({length:96},(_,i)=>entity('n'+i,'密集节点 '+i,'合成夹具'));
    const edges=dense.flatMap((n,i)=>[1,7,13].map(k=>({id:'e'+i+'_'+k,kind:'relation',name:'连接 '+i+' '+k,
      from:n.id,to:'n'+((i+k)%dense.length),relation_type:'business',predicate:'关联'})));
    await write(focused,'edit',{asset:[...dense,...edges]});
    await focused.goto(origin+'/?lang=zh&focus=n0#graph');await focused.waitForLoadState('networkidle');
    assert.equal(await focused.locator('[data-kw-node]').count(),7);
    const firstExpansion=Date.now();await focused.locator('[data-kw=clear-focus]').click();
    const cancel=focused.locator('[data-kw=arrange]').filter({hasText:'取消布局'});
    await cancel.click();const firstCancelMs=Date.now()-firstExpansion;
    await focused.locator('#kw-canvas-search').fill('密集节点 80');
    await focused.waitForFunction(()=>document.querySelectorAll('[data-kw-node]').length===1);
    await focused.locator('#kw-canvas-search').fill('');
    await focused.locator('[data-kw=more]').click();await cancel.waitFor({timeout:10000});
    await cancel.click();
    const arrange=focused.locator('[data-kw=arrange][data-layout-action=arrange]').filter({hasText:'自动布局'});
    await arrange.waitFor();await focused.screenshot({path:path.join(out,'dense-cancelled.png')});
    await arrange.click();
    await focused.waitForFunction(()=>document.querySelector('[data-kw=arrange]').textContent==='自动布局'&&!document.querySelector('[data-kw=arrange]').disabled,null,{timeout:90000});
    const layout=(await api(focused,'state')).layout;
    assert.ok(Object.keys(layout).filter(key=>key.startsWith('semantic:all:')).length>=24,
      'Completed worker result saved node positions: '+JSON.stringify({count:Object.keys(layout).length,toast:await focused.locator('#toast').innerText(),errors}));
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({localEdge:localEdge.id,externalEdge:relation,revision:change.revision,denseNodes:dense.length,denseLinks:edges.length,firstCancelMs,errors}));
  }finally{try{await browser?.close();}finally{server.kill();}}
})().catch(e=>{console.error(e);process.exitCode=1;});
