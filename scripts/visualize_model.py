#!/usr/bin/env python3
"""Generate a self-contained, read-only semantic/mapping/evidence HTML explorer."""
import argparse
import json
from pathlib import Path
import sys
from _contract import (binding_errors, digest, load, object_digest,
                       ont_entities, ont_relations, ont_relation_id)


def ontology_view(model):
    """本体声明层 + 投影状态（静态对账结果，不做推理）。"""
    entities, relations = ont_entities(model), ont_relations(model)
    if not entities and not relations:
        return None
    projected_by = {}
    for ds in model.get("datasets", []) or []:
        if ds.get("ontology_ref"):
            projected_by.setdefault(ds["ontology_ref"], []).append(ds.get("name"))
    projected_rels = {r.get("ontology_ref") for r in model.get("relationships", []) or []
                      if r.get("ontology_ref")}
    return {
        "entities": [{**e, "projected_by": projected_by.get(e.get("name"), [])}
                     for e in entities],
        "relations": [{**r, "id": ont_relation_id(r),
                       "projected": ont_relation_id(r) in projected_rels}
                      for r in relations],
    }


def build_data(model_path, report_paths=(), session_path=None):
    model = load(model_path)
    reports = []
    for path in report_paths:
        report = load(path)
        reports.append({"name": Path(path).name, "binding_errors": binding_errors(report, model_path), "report": report})
    session = load(session_path) if session_path else None
    if session and object_digest(session["model"]) != object_digest(model):
        raise ValueError("session does not match this model")
    return {"model": model, "sha256": digest(model_path), "reports": reports,
            "ontology": ontology_view(model),
            "gaps": session.get("gaps", []) if session else [],
            "decisions": session.get("decisions", []) if session else []}


PAGE = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'">
<title>语义交付 · 模型与证据</title><style>
:root{color-scheme:light;--ink:#172d3b;--soft:#536777;--line:#dce4e8;--accent:#006b68}
*{box-sizing:border-box}body{margin:0;background:#f3f6f7;color:var(--ink);font:15px/1.6 system-ui,"Microsoft YaHei",sans-serif}
header{background:#103b48;color:white;padding:28px max(24px,calc((100vw - 1360px)/2))}h1{font-size:28px;margin:0}header p{color:#c8e6e5;margin:8px 0 0}
main{max-width:1408px;margin:auto;padding:24px}.bar{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-bottom:20px}input,select,button{font:inherit;border:1px solid #adbfc9;border-radius:8px;padding:9px;background:white;color:var(--ink)}input{flex:1;min-width:230px}button{cursor:pointer}.layout{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(280px,1fr);gap:22px}.panel{background:white;border:1px solid var(--line);border-radius:12px;padding:20px;margin-bottom:18px}h2{font-size:19px;margin:0 0 12px}h3{font-size:16px;margin:0}.muted{color:var(--soft);font-size:13px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.card{text-align:left;display:block;padding:16px;border:1px solid var(--line);border-radius:10px;overflow-wrap:anywhere}.card:hover,.card:focus{border-color:var(--accent);background:#f1faf8}.badge{display:inline-block;padding:2px 8px;border-radius:5px;font-size:12px;background:#e7efef;margin:4px 5px 4px 0}.bad{background:#ffe9dc;color:#853600}.good{background:#dcf2e9;color:#126043}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.6 ui-monospace,monospace;background:#f4f7f8;padding:12px;border-radius:6px}.edge,.item{padding:12px 0;border-bottom:1px solid var(--line)}.edge button,.item button{border:0;background:none;padding:0;color:var(--accent);text-align:left}#counts{margin-left:auto}footer{color:var(--soft);font-size:12px;overflow-wrap:anywhere}@media(max-width:850px){.layout{grid-template-columns:1fr}header{padding:24px}.panel{padding:16px}main{padding:16px}}
</style></head><body><header><h1>语义交付 · 模型与证据</h1><p>查看语义关系、物理映射和补齐进度；每个验证结论保留适用范围。</p></header>
<main><div class="bar"><label for="search">搜索</label><input id="search" placeholder="数据集、字段、指标或缺口"><label for="filter">显示</label><select id="filter"><option value="all">全部内容</option><option value="gaps">待补齐内容</option><option value="evidence">验证证据</option></select><span id="counts" class="muted"></span></div>
<div class="layout"><section><div class="panel" id="semantic"><h2>数据集与物理映射</h2><p class="muted">模型声明的 source 与 fields。未观测实际运行链路。</p><div id="datasets" class="cards"></div><h2 style="margin-top:22px">语义关系</h2><div id="relations"></div><h2 style="margin-top:22px">指标</h2><div id="metrics"></div></div><div class="panel" id="gapPanel"><h2>补齐与决策</h2><div id="gaps"></div></div><div class="panel" id="evidencePanel"><h2>验证证据</h2><div id="reports"></div></div></section><aside><div class="panel"><h2 id="detailTitle">选择对象查看详情</h2><p class="muted">来源、计算口径、确认依据和完整属性在此显示。</p><div id="detail"></div></div></aside></div>
<footer id="footer"></footer></main><script id="payload" type="application/json">__PAYLOAD__</script><script>
'use strict';
const data=JSON.parse(document.getElementById('payload').textContent), m=data.model;
const $=id=>document.getElementById(id);
function element(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=String(text);if(cls)e.className=cls;return e}
document.head.append(element('style','aside .panel{position:sticky;top:16px;max-height:calc(100vh - 32px);overflow:auto}@media(max-width:850px){aside .panel{position:static;max-height:none}}'));
function inspect(title,obj){$('detailTitle').textContent=title;$('detail').replaceChildren(element('pre',JSON.stringify(obj,null,2)));if(window.innerWidth<=850)$('detailTitle').scrollIntoView({block:'start'})}
function matches(obj,q){return JSON.stringify(obj).toLowerCase().includes(q)}
function badge(text,ok){return element('span',text,'badge '+(ok?'good':'bad'))}
const graphPanel=element('div',undefined,'panel'),graphTitle=element('h2','语义图 · 本体层与合同投影'),graphNote=element('p','上为本体层（业务对象与谓词），下为投影层（物理数据集）。实线=等值键，虚线=弱匹配，点线=纯语义，灰虚线=投影。点击节点聚焦邻接，双击空白复位，滚轮缩放、拖拽平移。','muted');
const svgNS='http://www.w3.org/2000/svg',graph=document.createElementNS(svgNS,'svg');
graph.setAttribute('role','img');graph.setAttribute('aria-label','本体与数据集关系图');graph.style.width='100%';graph.style.height='auto';graph.style.touchAction='none';
const gtools=element('div');gtools.style.marginBottom='8px';
const zin=element('button','放大'),zout=element('button','缩小'),zreset=element('button','复位');
[zin,zout,zreset].forEach(b=>{b.style.marginRight='8px';gtools.append(b)});
graphPanel.append(graphTitle,graphNote,gtools,graph);$('semantic').before(graphPanel);
function svg(tag,attrs,text){const e=document.createElementNS(svgNS,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;return e}
const DASH={equi_key:'',weak:'7 5',derived:'12 5 3 5',semantic_only:'2 5'};
let vb={x:0,y:0,w:1160,h:400},focusId=null,edgePairs=[];
function setVB(){graph.setAttribute('viewBox',vb.x+' '+vb.y+' '+vb.w+' '+vb.h)}
zin.addEventListener('click',()=>{vb.w*=0.8;vb.h*=0.8;setVB()});
zout.addEventListener('click',()=>{vb.w*=1.25;vb.h*=1.25;setVB()});
zreset.addEventListener('click',()=>{focusId=null;drawGraph($('search').value.toLowerCase())});
graph.addEventListener('wheel',e=>{e.preventDefault();const f=e.deltaY<0?0.9:1.1;vb.w*=f;vb.h*=f;setVB()},{passive:false});
let pan=null;
graph.addEventListener('pointerdown',e=>{pan={x:e.clientX,y:e.clientY,vx:vb.x,vy:vb.y};try{graph.setPointerCapture(e.pointerId)}catch(_){}});
graph.addEventListener('pointermove',e=>{if(!pan)return;const k=vb.w/(graph.clientWidth||1160);vb.x=pan.vx-(e.clientX-pan.x)*k;vb.y=pan.vy-(e.clientY-pan.y)*k;setVB()});
graph.addEventListener('pointerup',()=>pan=null);
graph.addEventListener('dblclick',()=>{focusId=null;applyFocus()});
function applyFocus(){
 const keep=new Set();
 if(focusId){keep.add(focusId);for(const p of edgePairs)if(p.a===focusId||p.b===focusId){keep.add(p.a);keep.add(p.b)}}
 for(const n of graph.querySelectorAll('[data-node]'))n.style.opacity=!focusId||keep.has(n.getAttribute('data-node'))?1:0.18;
 for(const e of graph.querySelectorAll('[data-edge]')){const [a,b]=e.getAttribute('data-edge').split('|');e.style.opacity=!focusId||(keep.has(a)&&keep.has(b))?1:0.06}
}
function drawGraph(q){
 graph.replaceChildren();edgePairs=[];
 const ont=data.ontology,ents=ont?(ont.entities||[]).filter(e=>matches(e,q)):[],dss=(m.datasets||[]).filter(d=>matches(d,q));
 const CW=250,RH=130,X0=140,eCols=Math.max(1,Math.min(4,Math.ceil(Math.sqrt(ents.length||1)))),ePos={};
 ents.forEach((e,i)=>ePos[e.name]={x:X0+(i%eCols)*CW,y:95+Math.floor(i/eCols)*RH});
 const band2=ents.length?Math.ceil(ents.length/eCols)*RH+150:50;
 const dCols=Math.max(1,Math.min(4,Math.ceil(Math.sqrt(dss.length||1)))),dPos={};
 dss.forEach((d,i)=>dPos[d.name]={x:X0+(i%dCols)*CW,y:band2+95+Math.floor(i/dCols)*RH});
 vb={x:0,y:0,w:1160,h:Math.max(band2+(dss.length?Math.ceil(dss.length/dCols)*RH+70:90),300)};setVB();
 const defs=svg('defs',{}),mk=(id,color)=>{const mkk=svg('marker',{id,viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:7,markerHeight:7,orient:'auto-start-reverse'});mkk.append(svg('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:color}));defs.append(mkk)};
 mk('arrowT','#006b68');mk('arrowB','#4a6fa5');graph.append(defs);
 if(ents.length)graph.append(svg('text',{x:16,y:40,fill:'#006b68','font-size':14,'font-weight':'bold'},'本体层 · 业务世界'));
 if(dss.length)graph.append(svg('text',{x:16,y:band2+40,fill:'#4a6fa5','font-size':14,'font-weight':'bold'},'投影层 · 物理数据'));
 const label=(x,y,text)=>{const t=svg('text',{x,y,fill:'#536777','font-size':12,'text-anchor':'middle'},text);t.style.paintOrder='stroke';t.style.stroke='#f3f6f7';t.style.strokeWidth='4';return t};
 const edge=(el,a,b,obj,title)=>{el.setAttribute('data-edge',a+'|'+b);edgePairs.push({a,b});el.style.cursor='pointer';el.addEventListener('click',ev=>{ev.stopPropagation();inspect(title,obj)});graph.append(el)};
 if(ont)for(const r of ont.relations||[]){const a=ePos[r.from],b=ePos[r.to];if(!a||!b)continue;
  const mx=(a.x+b.x)/2,my=(a.y+b.y)/2-46;
  const p=svg('path',{d:`M ${a.x} ${a.y} Q ${mx} ${my} ${b.x} ${b.y}`,fill:'none',stroke:'#006b68','stroke-width':2,'stroke-dasharray':DASH[r.mapping]??'7 5','marker-end':'url(#arrowT)'});
  edge(p,'e:'+r.from,'e:'+r.to,r,'本体关系 · '+r.id);graph.append(label(mx,my-4,(r.predicate||'')+(r.mapping&&r.mapping!=='equi_key'?' · '+r.mapping:'')))}
 for(const d of dss){const ref=d.ontology_ref;if(!ref||!ePos[ref])continue;const a=ePos[ref],b=dPos[d.name];
  const p=svg('path',{d:`M ${a.x} ${a.y+30} L ${b.x} ${b.y-30}`,fill:'none',stroke:'#9ab0ba','stroke-width':1.5,'stroke-dasharray':'3 3'});
  edge(p,'e:'+ref,'d:'+d.name,{ontology_ref:ref,dataset:d.name},'投影 · '+ref+' → '+d.name)}
 for(const r of m.relationships||[]){const a=dPos[r.from],b=dPos[r.to];if(!a||!b)continue;
  const p=svg('path',{d:`M ${a.x} ${a.y} L ${b.x} ${b.y}`,fill:'none',stroke:'#4a6fa5','stroke-width':2,'marker-end':'url(#arrowB)'});
  edge(p,'d:'+r.from,'d:'+r.to,r,'关系 · '+(r.id||r.from+' → '+r.to));graph.append(label((a.x+b.x)/2+10,(a.y+b.y)/2-8,r.cardinality||''))}
 const node=(id,x,y,title,sub,fill,stroke,dot,obj,kind)=>{
  const g=svg('g',{tabindex:0,role:'button','aria-label':title});g.setAttribute('data-node',id);g.style.cursor='pointer';
  g.append(svg('rect',{x:x-102,y:y-29,width:204,height:58,rx:10,fill,stroke,'stroke-width':1.6}));
  if(dot)g.append(svg('circle',{cx:x+88,cy:y-15,r:6,fill:dot}));
  g.append(svg('text',{x,y:y-3,'text-anchor':'middle',fill:'#172d3b','font-size':15},title));
  if(sub)g.append(svg('text',{x,y:y+17,'text-anchor':'middle',fill:'#536777','font-size':11.5},sub));
  const act=()=>{focusId=focusId===id?null:id;applyFocus();inspect(kind+' · '+title,obj)};
  g.addEventListener('click',ev=>{ev.stopPropagation();act()});
  g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();act()}});
  graph.append(g)};
 for(const e of ents){const p=ePos[e.name];
  node('e:'+e.name,p.x,p.y,e.cn||e.name,(e.is_a?'is_a '+e.is_a+' · ':'')+(e.attributes||[]).length+' 属性','#eef8f6','#006b68',e.projected_by.length?'#2e9e7b':(e.unprojected_reason?'#9aa7ad':'#e0863d'),e,'本体实体')}
 for(const d of dss){const p=dPos[d.name];
  node('d:'+d.name,p.x,p.y,d.cn||d.name,'source: '+(d.source||'待补充'),'#f4f7fb','#4a6fa5',null,d,'数据集')}
 const lg=svg('g',{}),ly=vb.h-18;
 [['—— 等值键','#006b68',''],['┄ 弱匹配','#006b68','7 5'],['┈ 纯语义','#006b68','2 5'],['⎯ 投影','#9ab0ba','3 3'],['—— 合同关系','#4a6fa5','']].forEach((it,i)=>{
  lg.append(svg('line',{x1:560+i*125,y1:ly,x2:585+i*125,y2:ly,stroke:it[1],'stroke-width':2,'stroke-dasharray':it[2]}));
  lg.append(svg('text',{x:590+i*125,y:ly+4,fill:'#536777','font-size':12},it[0].slice(2)))});
 graph.append(lg);applyFocus();
}
const ontoPanel=element('div',undefined,'panel');
ontoPanel.append(element('h2','业务本体 · 声明层'),element('p','对象/属性/谓词/落地方式的声明式事实清单；系统不做推理，投影状态以标记显示。','muted'));
const ontEntities=element('div',undefined,'cards'),ontRelations=element('div'),ontRelTitle=element('h2','本体关系');
ontRelTitle.style.marginTop='22px';ontoPanel.append(ontEntities,ontRelTitle,ontRelations);
graphPanel.after(ontoPanel);
function render(){const q=$('search').value.toLowerCase(), filter=$('filter').value;
 for(const id of ['datasets','relations','metrics','gaps','reports'])$(id).replaceChildren();
 let shown=0;
 const ont=data.ontology;
 ontoPanel.hidden=!ont||filter!=='all';
 ontEntities.replaceChildren();ontRelations.replaceChildren();
 if(ont){
  for(const e of ont.entities||[]){if(!matches(e,q))continue;const b=element('button',undefined,'card');
   b.append(element('h3',e.cn||e.name),element('div',(e.is_a?('is_a '+e.is_a+' · '):'')+(e.attributes||[]).length+' 个属性','muted'));
   b.append(e.projected_by.length?badge('投影 → '+e.projected_by.join('、'),true):(e.unprojected_reason?element('span','未投影（已说明）','badge'):badge('未投影（未说明）',false)));
   b.addEventListener('click',()=>inspect('本体实体 · '+e.name,e));ontEntities.append(b)}
  if(!ontEntities.children.length)ontEntities.append(element('p','无匹配本体实体。','muted'));
  for(const r of ont.relations||[]){if(!matches(r,q))continue;const row=element('div',undefined,'edge'),b=element('button',r.from+' → '+r.to+'  ·  '+(r.predicate||'?'));
   row.append(b,element('span',r.mapping||'?','badge'));
   row.append(r.projected?badge('已投影',true):(r.mapping==='equi_key'?badge('未投影',false):element('span','不投影（无键）','badge')));
   if(r.note)row.append(element('div',r.note,'muted'));
   b.addEventListener('click',()=>inspect('本体关系 · '+r.id,r));ontRelations.append(row)}
 }
 for(const d of m.datasets||[]){if(!matches(d,q))continue;shown++;const b=element('button',undefined,'card');b.append(element('h3',d.cn||d.name),element('div',d.name+' → '+(d.source||'待补充物理来源'),'muted'),element('div',d.grain||'粒度待确认'));if(d.ontology_ref)b.append(element('div','本体对象： '+d.ontology_ref,'muted'));b.addEventListener('click',()=>inspect('数据集 · '+d.name,d));$('datasets').append(b)}
 for(const r of m.relationships||[]){if(!matches(r,q))continue;const row=element('div',undefined,'edge'),b=element('button',r.from+' → '+r.to+'  ·  '+r.cardinality);b.addEventListener('click',()=>inspect('关系 · '+(r.id||r.from+' → '+r.to),r));row.append(b,element('div','键：'+JSON.stringify(r.from_columns||r.join_key||[])+' → '+JSON.stringify(r.to_columns||r.join_key||[]),'muted'));$('relations').append(row)}
 for(const metric of m.metrics||[]){if(!matches(metric,q))continue;const row=element('div',undefined,'item'),b=element('button',(metric.name||metric.id)+' · '+metric.id);b.addEventListener('click',()=>inspect('指标 · '+metric.id,metric));row.append(b);$('metrics').append(row)}
 for(const g of data.gaps){if(!matches(g,q)||(filter==='gaps'&&g.state==='confirmed'))continue;const row=element('div',undefined,'item'),b=element('button',g.question);row.append(badge(g.state,g.state==='confirmed'),b,element('div',g.object+' · '+g.owner_role,'muted'));b.addEventListener('click',()=>inspect('补齐 · '+g.id,{...g,decisions:data.decisions.filter(d=>d.gap_id===g.id)}));$('gaps').append(row)}
 if(!$('gaps').children.length)$('gaps').append(element('p',data.gaps.length?'当前筛选无缺口。':'未提供补齐会话；不能据此判断语义完整。','muted'));
 for(const r of data.reports){if(!matches(r,q))continue;const row=element('div',undefined,'item'),b=element('button',r.name),valid=!r.binding_errors.length;row.append(badge(valid?(r.report.decision||r.report.status||'查看报告'):'证据失效 / 未绑定',valid&&r.report.status==='pass'),b,element('div',valid?('来源：'+(r.report.evidence?.mode||'未声明')+' · '+(r.report.scope||'')) :r.binding_errors.join('；'),'muted'));b.addEventListener('click',()=>inspect('证据 · '+r.name,r));$('reports').append(row)}
 if(!data.reports.length)$('reports').append(element('p','未提供验证报告；图形展示不代表数据验证通过。','muted'));
 $('semantic').hidden=filter!=='all';$('gapPanel').hidden=filter==='evidence';$('evidencePanel').hidden=filter==='gaps';
 $('counts').textContent=shown+' 个匹配数据集 · '+data.gaps.filter(g=>g.state!=='confirmed').length+' 个待确认项';
 graphPanel.hidden=filter!=='all';drawGraph(q);
}
$('search').addEventListener('input',render);$('filter').addEventListener('change',render);$('footer').textContent='模型版本 '+(m.version||'未声明')+' · SHA256 '+data.sha256+' · 本地只读快照；不代表国标符合性、运行血缘或生产验收。';render();
</script></body></html>'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True)
    ap.add_argument("--session")
    ap.add_argument("--report", action="append", default=[])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    try:
        data = build_data(args.model, args.report, args.session)
        payload = json.dumps(data, ensure_ascii=False, default=str).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        output = Path(args.out)
        inputs = [args.model, args.session, *args.report]
        if output.resolve() in {Path(p).resolve() for p in inputs if p}:
            raise ValueError("output must not overwrite an input")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(PAGE.replace("__PAYLOAD__", payload), encoding="utf-8")
        print(output)
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
