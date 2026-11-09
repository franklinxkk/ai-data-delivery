// Targeted VM test of the actual browser script. This is not a real network/browser test.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../workbench/static/knowledge.js'),'utf8');
const storage=new Map(),requests=[],notices=[];let committed=null;
function boot(){
  const listeners={},error={textContent:'',insertAdjacentHTML(){}};
  const context={window:{},document:{querySelector:s=>s==='#main'?null:error,querySelectorAll:()=>[],addEventListener:(type,fn)=>(listeners[type]??=[]).push(fn)},sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},localStorage:{getItem:()=>null,setItem(){}},crypto:require('node:crypto').webcrypto,TextEncoder,console};
  vm.createContext(context);vm.runInContext(source,context);
  context.window.KnowledgeWorkbench.configure({api:async(path,request)=>{requests.push({path,request});if(path==='knowledge/publish'){committed={revision:1,result:{snapshot_id:'stable_snapshot',manifest:{}}};throw Error('Simulated lost HTTP response');}if(path.startsWith('knowledge/operation/'))return {found:true,receipt:committed};throw Error(path);},reload:async()=>{},notify:x=>notices.push(x)});
  context.window.KnowledgeWorkbench.update({project_id:'test-project',revision:0});
  return {context,error,click:async()=>{const b={dataset:{kw:'publish'},closest:()=>null,disabled:false};await listeners.click[0]({target:{closest:()=>b}});}};
}
(async()=>{
 const first=boot();await first.click();assert.equal(requests.filter(x=>x.path==='knowledge/publish').length,1);assert.match(first.error.textContent,/提交结果尚未确认/);const stored=JSON.parse(storage.get('kw-pending:test-project'));assert.equal(stored.length,1);const id=stored[0][1].request.operation_id;
 const reopened=boot();assert.match(reopened.context.window.KnowledgeWorkbench.render('history'),/查询结果/);await reopened.click();assert.equal(requests.filter(x=>x.path==='knowledge/publish').length,1);assert.equal(requests.at(-1).path,'knowledge/operation/'+id);assert.equal(JSON.parse(storage.get('kw-pending:test-project')).length,0);console.log('PASS: lost response -> reopened script -> same operation receipt -> one publish write');
})().catch(e=>{console.error(e);process.exitCode=1;});
