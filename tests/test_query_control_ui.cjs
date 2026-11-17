// Exercise real question event handlers; browser geometry is verified separately.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const source=fs.readFileSync(require('node:path').join(__dirname,'../workbench/static/scenarios.js'),'utf8');
const clone=x=>JSON.parse(JSON.stringify(x));
const sorted=x=>Array.isArray(x)?x.map(sorted):x&&typeof x==='object'?Object.fromEntries(Object.keys(x).sort().map(k=>[k,sorted(x[k])])):x;
function boot(){
 const scenario={id:'q',question:'Count eligible items',title:'Count',intent:'query',asset_ids:['metric'],domain:'',scope:'',as_of:null,acceptance_notes:'',acceptance:{required_asset_ids:[],required_gap_codes:[],cases:[]}};
 let state={revision:1,scenarios:[scenario],assets:[{id:'metric',name:'Count',kind:'metric',status:'confirmed'}]},wb,wait=null;
 const fields={question:scenario.question,title:scenario.title,intent:'query',domain:'',as_of:'',acceptance_notes:''},listeners={},main={innerHTML:''},error={textContent:'',focus(){}};
 const form={querySelectorAll(selector){return selector==='[data-sq-field]'?Object.entries(fields).map(([k,v])=>({dataset:{sqField:k},value:v})):[];},querySelector(){return {value:''};}};
 const document={querySelector(s){return s==='#main'?main:s==='#sq-form'?form:s==='#sq-error'?error:null;},addEventListener(k,fn){listeners[k]=fn;}};
 const kw={scopeText:v=>v,scopeFields:()=>'',readScope:()=>'',pendingHtml:()=>'',transact:async(key,action,payload)=>{
   if(action==='scenario'){state.scenarios=[{...clone(payload.scenario),as_of:payload.scenario.as_of||null}];state.revision++;wb.update(sorted(clone(state)));return {scenario:clone(state.scenarios[0])};}
   if(action==='publish'){if(wait)await wait;state.revision++;wb.update(sorted(clone(state)));return {download_url:'/old-snapshot',filename:'question.zip'};}
   throw Error(action);
 }};
 const context={window:{UIText:{language:'en'},KnowledgeWorkbench:kw},document,location:{hash:'#questions'},crypto:crypto.webcrypto};
 vm.createContext(context);vm.runInContext(source,context);wb=context.window.ScenarioWorkbench;
 wb.configure({reload:async()=>{},notify:()=>{}});wb.update(state);wb.open('q');
 return {wb,html:()=>wb.render(),edit(){fields.question='Changed while request is pending';listeners.input({target:{dataset:{},id:'',closest:s=>s==='#sq-form'?form:null}});},
  pause(){let resume;wait=new Promise(r=>resume=r);return resume;},otherWrite(){state.revision++;wb.update(sorted(clone(state)));},
  async click(a){const b={dataset:{sq:a},disabled:false};await listeners.click({target:{closest:s=>s==='[data-sq]'?b:null}});}};
}
(async()=>{
 let t=boot();await t.click('handoff');assert(t.html().includes('/old-snapshot'),'Readback key order and null date must not invalidate unchanged content');
 t.edit();assert(!t.html().includes('/old-snapshot'));await t.click('save');assert(!t.html().includes('/old-snapshot'));
 t=boot();let resume=t.pause(),pending=t.click('handoff');await new Promise(r=>setImmediate(r));t.edit();resume();await pending;
 assert(!t.html().includes('/old-snapshot'));assert(t.wb.isDirty());
 t=boot();resume=t.pause();pending=t.click('handoff');await new Promise(r=>setImmediate(r));t.otherWrite();resume();await pending;
 assert(!t.html().includes('/old-snapshot'));
 console.log('PASS: canonical content comparison, null date, immediate invalidation, in-flight edits and project changes cannot expose an outdated handoff');
})().catch(e=>{console.error(e);process.exitCode=1});
