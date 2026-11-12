// Run against an isolated equipment example after browser_bilingual.cjs.
const {chromium}=require('playwright'),fs=require('fs'),path=require('path'),assert=require('assert/strict');
const origin=process.argv[2],out=process.env.EVIDENCE_DIR||path.join(__dirname,'../tmp-question-browser');
fs.mkdirSync(out,{recursive:true});
(async()=>{const browser=await chromium.launch({executablePath:process.env.BROWSER_PATH||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1600,height:1080},acceptDownloads:true}),errors=[],checks=[];
 page.on('pageerror',e=>errors.push(e.message));
 const api=(route,data)=>page.evaluate(async({route,data})=>{const r=await fetch('/api/knowledge/'+route,{method:data?'POST':'GET',headers:{'X-Workbench-Token':document.querySelector('meta[name=session-token]').content,'Content-Type':'application/json'},body:data?JSON.stringify(data):undefined});return {status:r.status,body:await r.json()};},{route,data});
 const state=async()=>(await api('state')).body;
 const action=async(name)=>page.locator(`[data-sq="${name}"]`).first().click();
 const q=()=>page.locator('[data-sq-field=question]');
 await page.goto(origin+'/?lang=zh#questions');await q().waitFor();
 assert.equal(await page.locator('nav [data-page=questions]').innerText(),'01\n业务问题');
 const original=await state(),testTitle='浏览器问题回归 '+Date.now();
 await q().fill('实验室 L 当前可借设备数有多少？');await page.locator('[data-sq-field=title]').fill(testTitle);
 await page.locator('[data-sq-field=intent]').selectOption('calculate');
 await page.locator('[data-sq-field=acceptance_notes]').fill('没有实际库存记录时不能给出台数。');
 await action('check');await page.locator('[data-testid=scenario-result]').waitFor();
 assert(await page.locator('[data-testid=scenario-result]').innerText().then(x=>x.includes('找到候选')));
 await page.locator('[data-sq=choose][data-id="demo.available"]').click();
 await action('check');await page.getByRole('heading',{name:'仍有含义或证据需要核对',exact:true}).waitFor();
 let s=await state(),scenario=s.scenarios.find(x=>x.title===testTitle);assert.deepEqual(scenario.asset_ids,['demo.available']);
 assert.deepEqual(s.assets,original.assets);assert.equal(s.snapshots.length,original.snapshots.length);
 checks.push('Question save and lexical discovery require explicit selection; calculation remains unexecuted');
 await page.reload();await page.locator(`[data-sq=open][data-id="${scenario.id}"]`).click();assert.equal(await q().inputValue(),scenario.question);
 await action('check');await page.getByRole('heading',{name:'仍有含义或证据需要核对',exact:true}).waitFor();
 assert(await page.locator('[data-testid=scenario-result]').innerText().then(x=>x.includes('练习适用范围')));
 checks.push('Reopen retains question and IDs; readback includes required scope and gaps');
 await page.locator('#sq-batch').selectOption((await state()).batches[0].id);
 await action('task');await page.locator('#sq-task-command').waitFor();assert((await page.locator('#sq-task-command').inputValue()).includes('--scenario'));
 assert.deepEqual((await state()).assets,original.assets);checks.push('Question-scoped host task carries scenario identity without confirming knowledge');
 await action('check');await page.getByRole('heading',{name:'仍有含义或证据需要核对',exact:true}).waitFor();

 await page.screenshot({path:path.join(out,'questions-zh.png'),fullPage:true});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false);
 // Independent writer changes the same saved question while local edits remain.
 await q().fill('未保存的本地问题');s=await state();
 const concurrent={...scenario,title:'另一窗口已修改'};
 assert.equal((await api('scenario',{revision:s.revision,operation_id:'browser-concurrent-'+Date.now(),scenario:concurrent})).status,200);
 const conflict=page.waitForResponse(r=>r.url().endsWith('/api/knowledge/scenario')&&r.request().method()==='POST');await action('save');assert.equal((await conflict).status(),409);
 assert.equal(await q().inputValue(),'未保存的本地问题');
 await action('reload');await page.waitForFunction(()=>document.querySelector('[data-sq-field=title]')?.value==='另一窗口已修改');
 assert.equal(await q().inputValue(),scenario.question);checks.push('Stale save refuses without losing input; explicit reload reads latest server state');
 // New check cannot be attached to a different question while awaiting its response.
 await page.route('**/api/knowledge/scenario-check',async route=>{await new Promise(r=>setTimeout(r,500));await route.continue();});
 await action('check');await action('new');await page.getByRole('heading',{name:'仍有含义或证据需要核对',exact:true}).waitFor();assert.equal(await q().inputValue(),scenario.question);await page.unroute('**/api/knowledge/scenario-check');
 checks.push('Pending readiness request cannot switch to a different question');
 // Scoped delivery survives a reload; empty does not mean all in a question handoff.
 await action('deliver');await page.locator('[data-kw=publish]').first().waitFor();await page.reload();
 assert.equal(await page.locator('[data-publish-id="demo.available"]').isChecked(),true);
 await page.locator('[data-publish-id="demo.available"]').uncheck();s=await state();await page.locator('[data-kw=publish]').first().click();
 await page.getByText('当前问题没有选择定义，请先选择，或明确切换为全部业务语义。',{exact:true}).waitFor();assert.equal((await state()).snapshots.length,s.snapshots.length);
 await page.locator('[data-publish-id="demo.available"]').check();
 await page.locator('[data-kw=publish]').first().click();await page.locator('[data-kw=download]').first().waitFor();
 const download=page.waitForEvent('download');await page.locator('[data-kw=download]').first().click();await (await download).saveAs(path.join(out,'question-semantic.zip'));
 checks.push('Scoped publication survives reload; empty selection blocks; fixed ZIP downloaded');
 // English interface still preserves the Chinese source and saved question.
 await page.goto(origin+'/?lang=en#questions');await q().waitFor();await page.locator(`[data-sq=open][data-id="${scenario.id}"]`).click();
 assert.equal(await q().inputValue(),scenario.question);await action('check');await page.getByRole('heading',{name:'Meaning or evidence needs review',exact:true}).waitFor();
 await page.screenshot({path:path.join(out,'questions-en.png'),fullPage:true});
 await page.setViewportSize({width:1280,height:900});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false);
 checks.push('English question page preserves original source text; 1600/1280 layouts do not overflow');
 assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'questions-browser.json'),JSON.stringify({checks,errors},null,2));console.log(JSON.stringify({checks,errors}));
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
