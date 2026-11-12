'use strict';
/* Questions reference canonical assets; this view never stores another ontology. */
window.ScenarioWorkbench=(()=>{
  const $=s=>document.querySelector(s), esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const t=(zh,en)=>window.UIText?.language==='zh'?zh:en, copy=v=>JSON.parse(JSON.stringify(v));
  const btn=(zh,en,action,extra='',cls='')=>`<button type="button" data-sq="${action}" ${extra} class="${cls}">${t(zh,en)}</button>`;
  let C,S={scenarios:[],assets:[],batches:[],groups:[]},draft=null,baseRevision=null,dirty=false,report=null,task=null,filter='',notice='',busy=false;
  const blank=()=>({title:'',question:'',intent:'explain',domain:'',scope:'',as_of:'',acceptance_notes:'',asset_ids:[]});
  function configure(context){C=context;}
  function update(state){S={scenarios:[],assets:[],batches:[],groups:[],...state};if(!draft){draft=blank();baseRevision=S.revision;}else if(!dirty){const saved=S.scenarios.find(x=>x.id===draft.id);if(saved)draft=copy(saved);baseRevision=S.revision;}}
  function rerender(){if(location.hash==='#questions'||!location.hash){$('#main').innerHTML=render();}}
  function open(id){draft=copy(S.scenarios.find(x=>x.id===id)||blank());baseRevision=S.revision;dirty=false;report=null;task=null;notice='';filter='';rerender();}
  function capture(strict=true){
    const form=$('#sq-form');if(!form)return;
    for(const el of form.querySelectorAll('[data-sq-field]'))draft[el.dataset.sqField]=el.value;
    const scope=form.querySelector('[data-field="scope"]');
    draft.scope=scope?scope.value:window.KnowledgeWorkbench.readScope(form,draft.scope,strict);
  }
  const scopeText=v=>window.KnowledgeWorkbench.scopeText(v);
  const kindName=v=>({entity:t('业务对象','Object'),term:t('业务术语','Term'),attribute:t('属性','Attribute'),relation:t('业务关系','Relationship'),metric:t('指标','Metric'),rule:t('业务规则','Rule'),dataset:t('数据集','Dataset'),field:t('数据字段','Data field'),mapping:t('数据映射','Mapping')}[v]||v);
  const statusName=v=>({confirmed:t('已确认','Confirmed'),draft:t('草稿','Draft'),needs_review:t('待复核','Needs review'),retired:t('已停用','Retired')}[v]||v);
  const gapName=v=>({DECLARED_KNOWLEDGE_GAP:t('资料尚未提供','Missing business facts'),CONTEXT_TRUNCATED:t('还有定义需要读取','More context to read'),NO_DATA_CONNECTOR:t('尚未连接数据','Data connection needed'),NO_ACTION_EXECUTOR:t('尚未连接办理接口','Action interface needed'),APPLICABILITY_UNKNOWN:t('适用时间待明确','Time applicability unclear'),OUTSIDE_KNOWN_INTERVAL:t('超出已知适用时间','Outside known time interval')}[v]||t('需核对项','Review item'));
  function selection(){
    const selected=new Set(draft.asset_ids),q=filter.toLocaleLowerCase();
    const items=S.assets.filter(a=>selected.has(a.id)||(!q? !['field','dataset','mapping'].includes(a.kind):[a.name,a.domain,a.definition,...(a.aliases||[])].join(' ').toLocaleLowerCase().includes(q)));
    const ordered=items.sort((a,b)=>Number(selected.has(b.id))-Number(selected.has(a.id)));
    const visible=ordered.slice(0,80),missing=draft.asset_ids.filter(id=>!S.assets.some(a=>a.id===id));
    return `<p class="privacy">${t('已选','Selected')}: ${selected.size} · ${t('按名称、领域或别名检索；不会自动选择同名概念。','Search names, domains or aliases; matching names are never selected automatically.')}</p><div class="sq-options">${visible.map(a=>`<label class="sq-option"><input type="checkbox" data-sq-asset="${esc(a.id)}" ${selected.has(a.id)?'checked':''}><span><b>${esc(a.name)}</b> <small>${esc(a.domain)} · ${esc(statusName(a.status))}</small><span>${esc(a.definition)}</span><small>${esc(scopeText(a.scope))}</small></span></label>`).join('')}${missing.map(id=>`<label class="sq-option error"><input type="checkbox" data-sq-asset="${esc(id)}" checked>${esc(id)} · ${t('引用不存在，请重新核对','Missing reference; review this selection')}</label>`).join('')}</div>${items.length>80?`<p class="privacy">${t('当前显示前 80 项，请缩小搜索范围；其他已选项保留。','Showing the first 80 matches. Narrow the search; other selections are retained.')}</p>`:''}`;
  }
  function resultHtml(){
    if(!report)return `<div class="sq-empty"><b>${t('先写一个真实的业务问题','Start with a real business question')}</b><p>${t('例如：什么条件下车辆可以出车？再选择相关定义，检查缺口和调用边界。','For example: when may a vehicle be dispatched? Select related definitions to inspect gaps and consumption boundaries.')}</p></div>`;
    const r=report.reader||report.result||report.readiness||report,context=r.context;
    const labels={needs_selection:t('找到候选，请确认含义','Candidates found: confirm meaning'),no_match:t('还没有找到对应定义','No matching definitions yet'),context_available:t('所选定义的上下文可读取','Selected definitions are readable'),needs_review:t('仍有含义或证据需要核对','Meaning or evidence needs review'),requires_execution:t('已有语义上下文，执行能力待接入','Semantic context available; execution is separate'),blocked:t('当前范围需要修正','This scope needs correction')};
    const stale=report.revision!==S.revision||dirty;
    const issues=[...(context?.gaps||[]),...(report.issues||[])];
    return `<section class="sq-result" data-testid="scenario-result"><span class="eyebrow">${t('检查结果','READINESS CHECK')}</span><h2>${esc(labels[r.decision||r.status||report.status]||t('请核对检查信息','Review the check details'))}</h2>${stale?`<div class="notice warning">${t('问题或项目已有变化，请重新检查。此处保留上次结果供对照。','The question or project changed. Check again; the previous result is retained for comparison.')}</div>`:''}<p>${t('这是语义准备检查，尚未回答业务问题，也未查询数据或执行操作。','This checks semantic preparation. It has not answered the business question, queried data or performed an action.')}</p>
    ${(r.candidates||[]).length?`<div class="sq-candidates">${r.candidates.map(a=>`<div class="sq-candidate"><b>${esc(a.name)}</b><p>${esc(a.definition)}</p><small>${esc(a.domain)} · ${esc(scopeText(a.scope))}</small>${btn('选择此含义','Select this meaning','choose',`data-id="${esc(a.id)}" ${draft.asset_ids.includes(a.id)?'disabled':''}`,'small')}</div>`).join('')}</div>`:''}
    ${r.offset>0?btn('上一页候选','Previous candidates','more',`data-offset="${Math.max(0,r.offset-r.limit)}"`,'small'):''}${r.next_offset!=null?btn('更多候选','More candidates','more',`data-offset="${r.next_offset}"`,'small'):''}
    ${context?`<p><b>${t('包含定义','Definitions included')}: ${context.total}</b> · ${t('所需依赖随上下文带出','Required dependencies travel with context')}</p>${(context.assets||[]).map(a=>`<details class="sq-definition"><summary>${esc(a.name)} · ${esc(kindName(a.kind))}</summary><p>${esc(a.definition)}</p><p>${esc(scopeText(a.scope))}</p>${btn('在图谱中核对','Review in graph','locate',`data-id="${esc(a.id)}"`,'small')}</details>`).join('')}`:''}
    ${issues.length?`<h3>${t('需要补齐或确认','Gaps to resolve')}</h3><ul>${issues.map(x=>`<li><b>${esc(gapName(x.code))}</b> ${esc(x.message||x.detail||'')}</li>`).join('')}</ul>`:''}
    ${context?`<div class="row">${context.offset>0?btn('上一页定义','Previous definitions','more',`data-offset="${Math.max(0,context.offset-context.limit)}"`,'small'):''}${context.next_offset!=null?btn('下一页定义','Next definitions','more',`data-offset="${context.next_offset}"`,'small'):''}</div>`:''}
    ${(r.next_steps||[]).map(x=>`<p class="privacy">${esc(t(x.message||x,x.message_en||x.code||x.message||x))}</p>`).join('')}
    ${report.error||r.error?`<p class="error">${esc((report.error||r.error).message||report.error||r.error)}</p>`:''}
    <details><summary>${t('查看 Agent 上下文与证据','Inspect Agent context and evidence')}</summary><pre class="code sq-json">${esc(JSON.stringify(report,null,2))}</pre></details></section>`;
  }
  function render(){
    if(!draft){draft=blank();baseRevision=S.revision;}
    const intents=[['explain',t('解释业务规则','Explain business meaning')],['calculate',t('计算指标','Calculate a metric')],['query',t('查询业务数据','Query business records')],['act',t('办理业务动作','Perform a business action')]];
    const selectedId=draft.id||'',changed=dirty&&baseRevision!==S.revision;
    return window.KnowledgeWorkbench.pendingHtml()+`<div class="page-head"><div><span class="eyebrow">QUESTION → MEANING → CONTEXT</span><h1>${t('从一个业务问题开始','Start with a business question')}</h1><div class="sub">${t('复用已有定义，只补齐影响当前问题的含义。图谱、材料和 Agent 共用同一套知识。','Reuse existing definitions and clarify what changes this question. Materials, graph and Agents share the same knowledge.')}</div></div>${btn('新建问题','New question','new','','primary')}</div>
    <div class="sq-steps"><span>1 ${t('写下问题','Define the question')}</span><span>2 ${t('核对关键含义','Confirm key meanings')}</span><span>3 ${t('检查与交付','Check and deliver')}</span></div>
    <div class="sq-workspace"><aside class="card sq-list"><h2>${t('业务问题','Business questions')}</h2>${S.scenarios.length?S.scenarios.map(s=>`<button type="button" data-sq="open" data-id="${esc(s.id)}" class="sq-question ${selectedId===s.id?'selected':''}"><b>${esc(s.title||s.question)}</b><span>${esc(s.question)}</span></button>`).join(''):`<p class="sub">${t('保存后可随时继续。旧项目的知识保持原样。','Save a question to return to it later. Existing knowledge stays intact.')}</p>`}<hr>${btn('加入已有材料','Add source material','materials','','quiet')}${btn('打开语义图谱','Open semantic graph','graph','','quiet')}${btn('核对候选变化','Review proposed changes','review','','quiet')}</aside>
    <div><section class="card" id="sq-form"><div class="row between"><h2>${t('希望解决什么问题？','What should this model help answer?')}</h2><span class="privacy">${dirty?t('有未保存修改','Unsaved changes'):selectedId?t('已保存','Saved'):t('新问题','New question')}</span></div>
    ${changed?`<div class="notice warning">${t('项目已有其他修改。当前输入保留；先读取最新问题，再对照修改。','The project changed elsewhere. Your input is retained; reload the saved question and compare before editing.')}${btn('读取最新问题','Reload saved question','reload','','small')}</div>`:''}
    <label>${t('业务问题','Business question')}<textarea rows="3" data-sq-field="question" placeholder="${t('例如：哪些车辆符合本周出车条件？','For example: which vehicles are eligible for dispatch this week?')}">${esc(draft.question)}</textarea></label>
    <div class="grid cols2"><label>${t('便于查找的名称（可选）','Short title (optional)')}<input data-sq-field="title" value="${esc(draft.title)}"></label><label>${t('期望完成的任务','Intended task')}<select data-sq-field="intent">${intents.map(([id,label])=>`<option value="${id}" ${draft.intent===id?'selected':''}>${label}</option>`).join('')}</select></label></div>
    <label>${t('已知样例、预期与例外（可选）','Known examples, expected results and exceptions (optional)')}<textarea rows="2" data-sq-field="acceptance_notes" placeholder="${t('例如：年检过期的车辆不能出车。未知条件请留空，不代填。','For example: a vehicle with an expired inspection is ineligible. Leave unknown conditions unresolved.')}">${esc(draft.acceptance_notes)}</textarea></label><p class="privacy">${t('这些是问题的核对线索；保存不会把它们自动变成已确认规则。','These notes guide review. Saving them does not turn them into confirmed rules.')}</p>
    <details class="sq-advanced"><summary>${t('领域、适用范围与业务日期','Domain, scope and business date')}</summary><label>${t('业务领域（可选）','Business domain (optional)')}<input data-sq-field="domain" value="${esc(draft.domain)}"></label>${window.KnowledgeWorkbench.scopeFields(draft.scope)}<label>${t('按哪个业务日期理解（可选）','Business date to interpret (optional)')}<input type="date" data-sq-field="as_of" value="${esc(draft.as_of)}"></label><p class="privacy">${t('留空表示日期未指定。范围用于查找含义，不能替代租户或数据权限。','A blank date stays unspecified. Scope helps find meaning; it does not grant tenant or data access.')}</p></details>
    <div class="row sq-actions">${btn('保存问题','Save question','save')}${btn('保存并检查','Save and check','check','','primary')}${btn('读取最新问题','Reload saved question','reload','','quiet small')}</div><p class="error" id="sq-error" role="alert">${esc(notice)}</p>
    <h3>${t('问题涉及哪些已有定义？','Which existing definitions are involved?')}</h3><input id="sq-filter" value="${esc(filter)}" placeholder="${t('搜索名称、领域、别名；无需填写 ID','Search names, domains or aliases; no IDs required')}" aria-label="${t('搜索已有定义','Search existing definitions')}"><div id="sq-selection">${selection()}</div></section>
    <section class="card sq-next"><h2>${t('需要补充含义时','When meaning needs clarification')}</h2><p>${t('选一份材料，让当前宿主 Agent 围绕这个问题整理候选；接纳仍在原有核对页完成。','Choose material for your host Agent to prepare question-focused proposals. Review and accept them in the existing review page.')}</p><select id="sq-batch" aria-label="${t('材料任务','Material task')}"><option value="">${t('选择已有材料任务','Choose a material task')}</option>${S.batches.filter(b=>b.status!=='cancelled').map(b=>`<option value="${esc(b.id)}">${esc((b.sources||[]).map(ref=>S.sources?.find(s=>s.id===ref.source_id)?.name||ref.source_id).join(' · '))} · ${esc(b.status)}</option>`).join('')}</select><div class="row">${btn('准备当前问题的 Agent 任务','Prepare host task for this question','task')}${btn('核对候选变化','Review proposed changes','review')}</div>${task?`<div class="notice"><b>${t('任务已准备，等待当前宿主处理','Task prepared; waiting for the host Agent')}</b><p>${t('这里不会自动运行模型。宿主可直接读取任务；手动协作时可复制下方指令。','No model runs here. The host can read this task directly; copy the command below for a manual handoff.')}</p><textarea readonly id="sq-task-command">${esc(task.host_instruction||'')}</textarea></div>`:''}</section></div>
    <aside class="card sq-output">${resultHtml()}<hr><h3>${t('交给应用或另一个 Agent','Hand off to an application or Agent')}</h3><p>${t('按本问题所选定义进入交付页，复用原有依赖补齐、发布和离线读取能力。','Open delivery with this question’s selected definitions, retaining dependency closure, publication and offline reading.')}</p>${btn('交付所选语义','Deliver selected semantics','deliver',!draft.asset_ids.length?'disabled':'','primary')}<p class="privacy">${t('业务问题不随语义包自动发布；包中只带所选知识及必要依据。','Question notes are not automatically published; packages contain selected knowledge and required evidence.')}</p></aside></div>`;
  }
  async function save(){
    capture();if(!dirty&&draft.id)return;
    const submitted=copy(draft),result=await window.KnowledgeWorkbench.transact('scenario:'+(draft.id||'new'),'scenario',{scenario:submitted},baseRevision);
    if(JSON.stringify(draft)!==JSON.stringify(submitted)){draft.id=result.scenario.id;baseRevision=S.revision;dirty=true;throw Error(t('上次内容已保存；提交期间新增的修改已保留，请再次保存。','The submitted content was saved. Edits made during submission are retained; save again.'));}
    draft=copy(result.scenario);dirty=false;baseRevision=S.revision;notice='';rerender();
  }
  async function check(offset=0){if(dirty||report?.revision!==S.revision)offset=0;await save();report=await C.api('knowledge/scenario-check',{scenario_id:draft.id,revision:S.revision,offset});rerender();}
  document.addEventListener('input',e=>{
    if(e.target.id==='sq-filter'){filter=e.target.value;$('#sq-selection').innerHTML=selection();return;}
    if(e.target.closest('#sq-form')){dirty=true;notice='';capture(false);}
  });
  document.addEventListener('change',e=>{
    const el=e.target;
    if(el.dataset.sqAsset){const ids=new Set(draft.asset_ids);el.checked?ids.add(el.dataset.sqAsset):ids.delete(el.dataset.sqAsset);draft.asset_ids=[...ids];dirty=true;return;}
    if(el.closest('#sq-form')){dirty=true;capture(false);}
  });
  document.addEventListener('click',async e=>{
    const b=e.target.closest('[data-sq]');if(!b||busy)return;b.disabled=true;busy=true;
    try{
      const a=b.dataset.sq;
      if(a==='new'||a==='open'||a==='reload'){if(dirty&&a!=='reload'){notice=t('请先保存当前问题，或点击“读取最新问题”放弃当前修改。','Save this question first, or use “Reload saved question” to discard edits.');$('#sq-error').textContent=notice;return;}if(a==='reload')await C.reload();open(a==='new'?'':a==='reload'?draft.id:b.dataset.id);}
      else if(a==='save')await save();
      else if(a==='check')await check();
      else if(a==='more')await check(Number(b.dataset.offset));
      else if(a==='choose'){capture();draft.asset_ids=[...new Set([...draft.asset_ids,b.dataset.id])];dirty=true;rerender();}
      else if(a==='task'){const batch=$('#sq-batch').value;if(!batch)throw Error(t('请先选择材料任务','Choose a material task first'));await save();task=await window.KnowledgeWorkbench.transact('scenario-task:'+draft.id+':'+batch,'task',{batch_id:batch,scenario_id:draft.id,action:'prepare'});rerender();}
      else if(a==='deliver'){await save();window.KnowledgeWorkbench.deliver(draft.asset_ids);}
      else if(a==='locate')window.KnowledgeWorkbench.locate(b.dataset.id);
      else if(['materials','graph','review'].includes(a))C.go(a==='materials'?'knowledge':a);
    }catch(err){notice=err.message;const target=$('#sq-error');if(target)target.textContent=notice;else C.notify(notice);}
    finally{b.disabled=false;busy=false;}
  });
  return {configure,update,render,isDirty:()=>dirty};
})();
