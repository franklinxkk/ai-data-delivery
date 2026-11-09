const {chromium}=require('playwright'),fs=require('fs'),path=require('path'),assert=require('assert/strict');
const origin=process.argv[2],lang=process.argv[3]||'en',out=path.resolve(process.env.EVIDENCE_DIR||path.join(__dirname,'../tmp-bilingual-browser'));
fs.mkdirSync(out,{recursive:true});
const zh=lang==='zh',pick=(en,cn)=>zh?cn:en;
(async()=>{const browser=await chromium.launch({executablePath:process.env.BROWSER_PATH||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
try{const page=await browser.newPage({viewport:{width:1600,height:1080},locale:zh?'zh-CN':'en-US',acceptDownloads:true}),errors=[],checks=[];
page.on('pageerror',e=>errors.push(e.message));
const apiState=()=>page.evaluate(async()=>{const r=await fetch('/api/knowledge/state',{headers:{'X-Workbench-Token':document.querySelector('meta[name=session-token]').content}});return r.json()});
const nav=async(id)=>{await page.locator(`nav [data-page="${id}"]`).click();};
async function review(){
 const rows=page.locator('details.kw-candidate');for(let i=0;i<await rows.count();i++)await rows.nth(i).locator('summary').click();
 await page.locator('[data-group-reason]').fill(pick('Synthetic exercise only: checked each definition against the supplied original text.','仅合成练习：逐项核对定义与原文，不代表真实业务签署。'));
 const response=page.waitForResponse(r=>r.url().endsWith('/api/knowledge/review')&&r.request().method()==='POST');
 await page.getByRole('button',{name:pick('Accept whole group','接纳整组'),exact:true}).click();const res=await response;assert.equal(res.status(),200,JSON.stringify(await res.json()));
 await page.getByText(pick('No changes to review here','当前没有待核对变化'),{exact:true}).waitFor();
}
await page.goto(origin+'/?lang='+lang);await page.locator('#kw-import-text').waitFor();
if(!process.argv.includes('--resume')){
assert.equal((await apiState()).assets.length,0);checks.push('Inputs and candidates do not auto-confirm knowledge');
// Language switching must not discard user input or translate domain material.
await page.locator('#kw-import-text').fill('Original material 原文 0 false');await page.locator('#ui-language').selectOption(zh?'en':'zh');
assert.equal(await page.locator('#ui-language').inputValue(),lang);assert.equal(await page.locator('#kw-import-text').inputValue(),'Original material 原文 0 false');
await page.locator('#kw-import-text').fill('');checks.push('Language switch retains unsaved input and explains recovery');
await nav('review');await review();assert.equal((await apiState()).assets.length,5);
await nav('knowledge');await page.getByRole('button',{name:pick('Prepare example business proposals','准备练习业务候选'),exact:true}).click();
await page.getByRole('button',{name:pick('Accept whole group','接纳整组'),exact:true}).waitFor();await review();
}
let state=await apiState();assert.equal(state.assets.length,12);checks.push('Reviewed DDL and source-linked business proposals through UI');
await nav('graph');await page.locator('#kw-canvas-view').selectOption('all');await page.locator('[data-kw-node="demo.available"]').waitFor();
await page.locator('[data-kw-node="demo.available"]').dblclick();await page.locator('#kw-asset-fields').waitFor();
const nameInput=page.locator('#kw-asset-fields [data-field=name]'),originalName=await nameInput.inputValue();
await nameInput.fill('');await page.getByRole('button',{name:pick('Save and confirm','保存并确认'),exact:true}).click();
await page.getByText(pick('Enter an asset name.','请填写资产名称'),{exact:true}).waitFor();assert.equal(await nameInput.inputValue(),'');await nameInput.fill(originalName);
checks.push('Invalid edit is rejected in the selected language and input remains editable');
const aliases=page.locator('#kw-asset-fields [data-field=aliases]');await aliases.fill((await aliases.inputValue())+', '+pick('Ready to lend','可供外借'));
await page.getByRole('button',{name:pick('Save and confirm','保存并确认'),exact:true}).click();await page.locator('dialog[open]').waitFor({state:'hidden'});
await page.reload();await page.locator('[data-kw-node="demo.available"]').waitFor();state=await apiState();assert(state.assets.find(a=>a.id==='demo.available').aliases.includes(pick('Ready to lend','可供外借')));
checks.push('Edit aliases, save and reload preserve knowledge');
await page.getByRole('button',{name:pick('Expand canvas','展开画布'),exact:true}).click();
const layoutResponse=page.waitForResponse(r=>r.url().endsWith('/api/layout')&&r.request().method()==='POST');
await page.getByRole('button',{name:pick('Auto layout','自动布局'),exact:true}).click();await layoutResponse;
await page.getByRole('button',{name:pick('Fit canvas','适应画布'),exact:true}).click();
await page.locator('#kw-canvas').click({position:{x:20,y:20}});
await page.locator('#toast').waitFor({state:'attached'});await page.waitForFunction(()=>!document.querySelector('#toast').classList.contains('show'));
await page.screenshot({path:path.join(out,'graph-'+lang+'.png')});
checks.push('Auto layout saved and real graph screenshot captured');
await page.getByRole('button',{name:pick('Exit focus','退出专注'),exact:true}).click();
await nav('publish');const response=page.waitForResponse(r=>r.url().endsWith('/api/knowledge/publish')&&r.request().method()==='POST');
await page.getByRole('button',{name:pick('Publish confirmed snapshot','发布确认快照'),exact:true}).click();const pub=await response;assert.equal(pub.status(),200,JSON.stringify(await pub.json()));
const downloaded=page.waitForEvent('download');await page.getByRole('button',{name:pick('Download semantic package','下载语义包'),exact:true}).click();await(await downloaded).saveAs(path.join(out,'equipment-'+lang+'.zip'));
checks.push('Published and downloaded a confirmed package through UI');
await nav('history');await page.screenshot({path:path.join(out,'history-'+lang+'.png')});
await nav('knowledge');await page.locator('#ui-language').selectOption(zh?'en':'zh');await page.waitForURL('**lang='+(zh?'en':'zh')+'*');
assert.equal(await page.locator('html').getAttribute('lang'),zh?'en':'zh-CN');assert.deepEqual((await apiState()).assets,state.assets);
checks.push('Language switch changes presentation and preserves all source/asset values');assert.deepEqual(errors,[]);
fs.writeFileSync(path.join(out,'browser-'+lang+'.json'),JSON.stringify({checks,errors,asset_count:state.assets.length},null,2));console.log(JSON.stringify({language:lang,checks,errors}));
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
