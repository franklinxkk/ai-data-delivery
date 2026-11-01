const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const out=process.env.EVIDENCE_DIR||'tmp-v012-onboarding/browser';fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.BROWSER_PATH,headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],steps=[];
 page.on('pageerror',e=>errors.push(String(e)));
 const call=async(action)=>{const pending=page.waitForResponse(r=>r.url().endsWith('/api/'+action)&&r.request().method()==='POST');await page.locator(`[data-action="${action}"]`).click();const result=await(await pending).json();if(result.id)await page.locator(`[data-action="report"][data-id="${result.id}"]`).waitFor();else await page.locator('#current-report').getByRole('heading',{name:'上下文选择结果'}).waitFor();return result};
 await page.goto(process.env.WORKBENCH_URL,{waitUntil:'networkidle'});
 await page.getByRole('button',{name:'开始数值与明细练习'}).waitFor();
 assert.match(await page.locator('.sidebar-foot').innerText(),/0\.1\.2/);
 await page.screenshot({path:path.join(out,'home.png'),fullPage:true});
 await page.getByRole('button',{name:'开始数值与明细练习'}).click();
 assert.equal(await page.locator('#bundle-metric').inputValue(),'rows');
 assert.deepEqual(await page.locator('#bundle-columns').evaluate(s=>Array.from(s.selectedOptions,x=>x.value)),['company_id']);
 assert.equal(await page.locator('#bundle-expected').inputValue(),'');
 for(const [metric,value] of [['rows',3],['present',2],['distinct',1]]){
   await page.locator('#bundle-metric').selectOption(metric);
   const r=await call('bundle');assert.equal(r.status,'computed_only');assert.equal(r.metric_value,value);assert.deepEqual(r.detail_rows,[['A'],['A'],[null]]);
   const unit=metric==='distinct'?'个':'条';assert.equal(r.metric_unit,unit);assert((await page.locator('#current-report').innerText()).includes(`${value} ${unit}`));
   steps.push(`切换${metric}保留有效返回字段，计算${value}及三行明细`);
 }
 await page.locator('#bundle-expected').fill(JSON.stringify({metric_value:2,matched_row_count:3,detail_rows:[['A'],['A'],[null]]}));
 let r=await call('bundle');assert.equal(r.status,'fail');steps.push('错误预期2对实际去重值1，界面显示不匹配');
 await page.locator('#bundle-expected').fill(JSON.stringify({metric_value:1,matched_row_count:3,detail_rows:[['A'],['A'],[null]]}));
 r=await call('bundle');assert.equal(r.status,'pass');steps.push('完整独立预期全部核对后才显示匹配');
 await page.screenshot({path:path.join(out,'bundle.png'),fullPage:true});
 r=await call('context');assert.equal(r.status,'selected');steps.push('相关上下文只记选择完成');
 await page.locator('summary').filter({hasText:'进阶检查'}).click();r=await call('check');steps.push('进阶模型检查仍可实际执行');
 await page.reload({waitUntil:'networkidle'});await page.locator('[data-action=report]').first().click();assert.notEqual(await page.locator('#current-report').innerText(),'');steps.push('刷新后历史报告可以重开');
 await page.locator('nav [data-page=delivery]').click();const dl=page.waitForEvent('download');await page.locator('[data-action=download][data-type=export]').click();await(await dl).saveAs(path.join(out,'semantic-delivery.zip'));steps.push('交付ZIP实际下载');
 assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'evidence.json'),JSON.stringify({scope:'真实本机Edge、工作台HTTP与SQLite；合成数据，未调用生产系统',browser:await browser.version(),steps,errors},null,2));
 await browser.close();console.log(JSON.stringify({steps,errors}));
})().catch(e=>{console.error(e);process.exit(1)});
