// Exercise the shared form serializer used by edit, candidate review, merge and source review.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(require('node:path').join(__dirname,'../workbench/static/knowledge.js'),'utf8');
const context={window:{},document:{addEventListener(){}},console};
vm.createContext(context);
vm.runInContext(source.replace('return {configure,update,render,mount,transact,pendingHtml,scopeFields,readScope,scopeText,deliver,locate};','return {configure,update,render,mount,scopeFields,scopeText,readAsset};'),context);
const {scopeFields,scopeText,readAsset}=context.window.KnowledgeWorkbench;
const clone=x=>JSON.parse(JSON.stringify(x));
const scope={currency:'模拟人民币',ledger:{id:'L1',allowed:['只做多','股票']},minimum:0,approved:false,unknown:null,empty:{}};
const html=scopeFields(scope);
assert.ok(html.includes('适用范围（分项）')&&html.includes('只做多'));
assert.ok(!html.includes('[object Object]'));
assert.ok(html.includes('type="number"')&&html.includes('value="0"'));
assert.ok(scopeText(scope).includes('approved：否'));
function form(scopeRows=[],plainRows=[{dataset:{field:'name'},value:'重命名'}]){
 return {querySelector:s=>s==='[data-field]'?plainRows[0]:null,
  querySelectorAll:s=>s==='[data-field]'?plainRows:s==='[data-scope-path]'?scopeRows:[]};
}
const original={name:'已有定义',scope:clone(scope),properties:{},refs:[]};
assert.deepEqual(clone(readAsset(form(),original).scope),scope,'Editing a name preserves structured scope');
const input=(path,type,value)=>({dataset:{scopePath:JSON.stringify(path),scopeType:type,scopeLabel:path.join(' / ')},value});
const changed=clone(readAsset(form([input(['ledger','allowed','0'],'string','仅限已结算多头'),input(['minimum'],'number','17'),input(['approved'],'boolean','true')]),original));
assert.equal(changed.scope.ledger.allowed[0],'仅限已结算多头');
assert.equal(changed.scope.ledger.allowed[1],'股票');
assert.equal(changed.scope.minimum,17);assert.equal(changed.scope.approved,true);
assert.deepEqual(changed.scope.empty,{});assert.equal(changed.scope.unknown,null);assert.deepEqual(original.scope,scope);
assert.throws(()=>readAsset(form([input(['minimum'],'number','')]),original),/有效数值/);
assert.equal(readAsset(form([input(['minimum'],'number','')]),original,false).scope.minimum,0,'Transient invalid input must not overwrite prior value');
assert.deepEqual(clone(readAsset(form(),{...original,scope:{}}).scope),{});
const flat=readAsset(form([],[{dataset:{field:'scope'},value:'新的纯文本范围'}]),{...original,scope:'原范围'});
assert.equal(flat.scope,'新的纯文本范围');
assert.ok(scopeFields({danger:'<script>alert(1)</script>'}).includes('&lt;script&gt;'));
console.log('PASS: structured scope survives unrelated edits; nested values update without losing types or unknown fields; invalid numbers are rejected');
