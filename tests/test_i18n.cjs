const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=path.join(__dirname,'../workbench/static'),catalog=JSON.parse(fs.readFileSync(path.join(root,'ui-en.json'),'utf8'));
function load(language){
 const select={value:'',addEventListener(){}},document={documentElement:{},querySelectorAll:()=>[],getElementById:()=>select};
 const ctx={window:{UI_EN:catalog},document,location:{search:'?lang='+language},navigator:{language:'en-US'},URLSearchParams,localStorage:{getItem:()=>null},setTimeout};vm.createContext(ctx);vm.runInContext(fs.readFileSync(path.join(root,'i18n.js'),'utf8'),ctx);return ctx.window.UIText;
}
const en=load('en'),zh=load('zh');
assert.equal(en.t('语义图谱'),'Semantic graph');assert.equal(zh.t('语义图谱'),'语义图谱');
const source='业务对象 <script> & 0 false';
assert.equal(en.t(['<h2>语义图谱</h2><p>','</p>'],source),'<h2>Semantic graph</h2><p>'+source+'</p>','Interpolated domain text is not translated or reinterpreted');
assert.equal(en.t(['',' / ',''],0,false),'0 / false');
assert.equal(en.error({error:'请填写资产名称'}),'Enter an asset name.');
assert(en.error({details:{issues:[{code:'MISSING_PROPERTY',asset_id:'m1',field:'unit'}]}}).includes('m1: Complete this required property before confirming: (unit)'));
assert.equal(zh.error({error:'请填写资产名称'}),'请填写资产名称');
assert(Object.values(catalog).every(x=>typeof x==='string'&&x.length));
console.log('PASS: English/Chinese static labels, original-value preservation, false/zero and actionable diagnostics');
