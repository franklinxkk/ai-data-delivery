// Exercise the real final onboarding, binding review and narrow-screen navigation.
const {chromium}=require('playwright'),fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const origin=process.argv[2],out=process.env.EVIDENCE_DIR;
if(!out)throw Error('Set EVIDENCE_DIR to an isolated output directory');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.BROWSER_PATH||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1100},acceptDownloads:true}),errors=[],checks=[];
  page.on('pageerror',e=>errors.push(e.message));
  const action=a=>page.locator(`[data-sq="${a}"]`).first().click();
  const state=()=>page.evaluate(async()=>{const r=await fetch('/api/knowledge/state',{headers:{'X-Workbench-Token':document.querySelector('meta[name=session-token]').content}});return r.json()});
  const check=async()=>{const response=page.waitForResponse(r=>r.url().endsWith('/scenario-check'));await action('check');assert.equal((await response).status(),200);await page.locator('[data-testid=query-control]').waitFor();};
  await page.goto(origin+'/?lang=zh#questions');await page.waitForLoadState('networkidle');
  await page.locator('[data-sq-field=question]').fill('实验室 L 有多少台可借设备？');
  await page.locator('[data-sq-field=title]').fill('设备借用 · 口径核对');
  await page.locator('[data-sq-field=intent]').selectOption('query');
  await page.locator('[data-sq-asset="demo.available"]').check();await check();
  const control=page.locator('[data-testid=query-control]');await control.locator('summary').click();
  await action('bindings');await page.locator('[data-testid=binding-review]').waitFor();
  const dialog=page.locator('#kw-dialog'),rows=dialog.locator('.qb-filter');
  const numeric=rows.filter({has:page.locator('[data-qb="filter-type"] option[value="number"][selected]')}).first();
  const value=numeric.locator('[data-qb=filter-value]');assert.equal(await value.inputValue(),'0');
  await value.fill('invalid number');await dialog.locator('[data-qb=reason]').fill('合成练习：已对照来源核对实验室范围、在库、未停用与按编号去重。');
  await dialog.getByRole('button',{name:'确认口径并保存',exact:true}).click();
  await dialog.locator('#kw-dialog-error').getByText('数字条件需要有效数值',{exact:true}).waitFor();
  assert.equal(await value.inputValue(),'invalid number');
  await value.fill('0');
  await dialog.screenshot({path:path.join(out,'binding-error-recovery-zh.png')});
  for(const width of [960,390]){await page.setViewportSize({width,height:1100});assert.equal(await dialog.evaluate(el=>el.scrollWidth>el.clientWidth+1),false,'Dialog overflow '+width);}
  await page.setViewportSize({width:1600,height:1100});
  const before=await state(),request=page.waitForResponse(r=>r.url().endsWith('/knowledge/edit')&&r.request().method()==='POST');
  await dialog.getByRole('button',{name:'确认口径并保存',exact:true}).click();const response=await request;assert.equal(response.status(),200,JSON.stringify(await response.json()));await dialog.waitFor({state:'hidden'});
  const after=await state(),metric=after.assets.find(a=>a.id==='demo.available');
  assert.equal(after.assets.length,before.assets.length);assert.equal(metric.properties.query_plan.filters.find(f=>f.value===0).value,0);
  assert.equal(metric.evidence.at(-1).type,'manual');assert(metric.evidence.at(-1).quote.includes('合成练习'));
  checks.push('Actual binding dialog retains invalid input, preserves numeric zero and writes reviewed evidence to the same metric');
  await check();await control.locator('summary').click();
  assert(!(await control.innerText()).includes('指标口径已变化'));
  await action('bindings');await dialog.screenshot({path:path.join(out,'binding-review-zh.png')});await dialog.locator('[data-kw=close-dialog]').last().click();
  await page.evaluate(()=>window.scrollTo(0,0));await page.waitForFunction(()=>!document.querySelector('#toast').classList.contains('show'));
  await page.screenshot({path:path.join(out,'question-v034-zh.png'),fullPage:false});
  const published=page.waitForResponse(r=>r.url().endsWith('/knowledge/publish'));await action('handoff');assert.equal((await published).status(),200);await page.locator('#sq-handoff').waitFor();
  assert((await page.locator('#sq-handoff').innerText()).includes('PACKAGE brief'));
  const download=page.waitForEvent('download');await page.locator('#sq-handoff [data-kw=download]').click();await(await download).saveAs(path.join(out,'final-question.zip'));
  checks.push('Review, recheck, publish and download stay connected; receiving instruction uses brief');
  for(const width of [1600,960,390]){await page.setViewportSize({width,height:1100});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'Page overflow '+width);assert(await page.locator('.sq-list').isVisible());}
  await page.locator('.sq-list [data-sq=open]').filter({hasText:'设备借用'}).first().click();assert.equal(await page.locator('[data-sq-field=question]').inputValue(),'实验室 L 有多少台可借设备？');
  await page.screenshot({path:path.join(out,'question-narrow-zh.png'),fullPage:true});
  checks.push('Saved questions remain reachable at 390px; no horizontal overflow at 1600/960/390px');
  await page.setViewportSize({width:1600,height:1100});await page.locator('#ui-language').selectOption('en');await page.waitForURL('**lang=en*');
  await page.locator('.sq-list [data-sq=open]').filter({hasText:'设备借用'}).first().click();await check();await control.locator('summary').click();
  assert((await control.innerText()).includes('Count distinct'));await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:path.join(out,'question-v034-en.png'),fullPage:false});
  await action('bindings');await page.locator('[data-testid=binding-review]').waitFor();assert((await dialog.innerText()).includes('Aggregation'));await dialog.screenshot({path:path.join(out,'binding-review-en.png')});
  await dialog.locator('[data-kw=close-dialog]').last().click();
  checks.push('English presentation retains original business text and offers readable binding review');
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'release034-browser.json'),JSON.stringify({checks,errors},null,2));console.log(JSON.stringify({checks,errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
