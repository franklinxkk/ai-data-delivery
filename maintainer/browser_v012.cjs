const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const out=process.env.EVIDENCE_DIR||'tmp-v0012/browser';fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.BROWSER_PATH,headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],steps=[];
 page.on('pageerror',e=>errors.push(String(e)));page.on('dialog',d=>d.accept());
 const state=()=>page.evaluate(async()=>await(await fetch('/api/state',{headers:{'X-Workbench-Token':document.querySelector('meta[name=session-token]').content}})).json());
 const response=async(action)=>{const pending=page.waitForResponse(r=>r.url().endsWith('/api/'+action)&&r.request().method()==='POST');await page.locator(`[data-action=${action}]`).click();const r=await pending;assert.equal(r.status(),200);const body=await r.json();await page.waitForFunction(key=>document.querySelector('#current-report')?.textContent.includes(key),body.id||body.payload_sha256);return body;};
 const importFile=async(kind,file)=>{if(kind==='model')await page.locator('#replace-model').check();if(kind==='sample')await page.locator('#provenance').selectOption('demo');await page.locator('#file-'+kind).setInputFiles(file);const p=page.waitForResponse(r=>r.url().endsWith('/api/import'));await page.locator(`[data-action=import][data-kind=${kind}]`).click();assert.equal((await p).status(),200);await page.waitForFunction(()=>document.querySelector('#toast').textContent.includes('已导入'));};
 await page.goto((process.env.WORKBENCH_URL||'http://127.0.0.1:18842')+'/#data');
 await importFile('model','tmp-v0012/demo/traffic.yaml');await importFile('sample','tmp-v0012/demo/traffic.sqlite');steps.push('通过文件控件导入交通模型与模拟SQLite快照');
 await page.locator('nav [data-page=check]').click();
 for(const [metric,value] of [['rows',3],['present',2],['distinct',1]]){
   await page.locator('#bundle-metric').selectOption(metric);await page.locator('#bundle-columns').selectOption(['company_id']);
   await page.locator('#bundle-expected').fill(JSON.stringify({metric_value:value,matched_row_count:3,detail_rows:[['A'],['A'],[null]]}));
   const r=await response('bundle');assert.equal(r.status,'pass');assert.equal(r.metric_value,value);assert.deepEqual(r.detail_rows,[['A'],['A'],[null]]);
   steps.push(`真实选择${metric}并核对数值${value}及三行明细`);
 }
 await page.locator('#bundle-metric').selectOption('distinct');await page.locator('#bundle-columns').selectOption('company_id');
 await page.locator('#bundle-limit').fill('1');await page.locator('#bundle-offset').fill('2');let result=await response('bundle');assert.equal(result.status,'computed_only');assert.equal(result.metric_value,1);assert.deepEqual(result.detail_rows,[[null]]);assert.equal(result.pagination.truncated,true);steps.push('分页最后一行NULL，总指标仍为1，未填预期不记pass');
 await page.locator('#bundle-metric').selectOption('distinct');await page.locator('#bundle-columns').selectOption('company_id');
 result=await response('context');assert.equal(result.status,'selected');assert.equal(result.context.entity_excerpt.evidence.source,'model_inferred');steps.push('上下文预览保留推断等级与来源，未当作Agent调用');
 await page.screenshot({path:path.join(out,'context.png'),fullPage:true});
 await page.reload();await page.locator('[data-action=report]').first().click();assert.match(await page.locator('#current-report').innerText(),/指标值/);steps.push('刷新后从历史证据重开实际结果');
 await page.locator('nav [data-page=model]').click();await page.locator('[data-action=asset-tab][data-kind=metrics]').click();await page.locator('[data-action=edit][data-kind=metrics][data-key=distinct]').click();
 await page.locator('#editor summary').filter({hasText:'现有表达式'}).click();await page.locator('[name=expr]').fill('COUNT(*)');await page.locator('#edit-form button[type=submit]').click();await page.waitForFunction(()=>!document.querySelector('dialog').open);
 await page.locator('nav [data-page=check]').click();assert((await state()).runs.filter(r=>r.kind==='bundle').every(r=>r.stale));await page.locator('[data-action=report]').first().click();assert.match(await page.locator('#current-report .badge').innerText(),/证据已过期/);steps.push('真实编辑口径后，旧执行证据标过期；重开报告也明确过期');
 await page.locator('#bundle-metric').selectOption('distinct');await page.locator('#bundle-columns').selectOption('company_id');result=await response('bundle');assert.equal(result.metric_value,3);steps.push('新口径实际重算为3');
 await page.screenshot({path:path.join(out,'bundle.png'),fullPage:true});
 await page.locator('nav [data-page=delivery]').click();const dl=page.waitForEvent('download');await page.locator('[data-action=download][data-type=export]').click();await(await dl).saveAs(path.join(out,'semantic-delivery.zip'));steps.push('真实点击导出ZIP，后续校验内容');
 assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'evidence.json'),JSON.stringify({browser:await browser.version(),scope:'真实本机工作台与SQLite项目；合成业务数据，无生产服务',steps,errors},null,2));await browser.close();console.log(JSON.stringify({steps,errors}));
})().catch(e=>{console.error(e);process.exit(1)});
