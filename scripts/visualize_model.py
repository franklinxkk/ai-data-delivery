#!/usr/bin/env python3
"""Generate a self-contained, read-only semantic/mapping/evidence HTML explorer."""
import argparse
import json
from pathlib import Path
import sys
from _contract import binding_errors, digest, load, object_digest


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
const graphPanel=element('div',undefined,'panel'),graphTitle=element('h2','关系图 · 设计声明'),graphNote=element('p','虚线为声明的关系，点击节点或关系查看属性；数据验证状态见证据面板。','muted');
const svgNS='http://www.w3.org/2000/svg',graph=document.createElementNS(svgNS,'svg');
graph.setAttribute('role','img');graph.setAttribute('aria-label','数据集关系图');graph.style.width='100%';graph.style.height='auto';
graphPanel.append(graphTitle,graphNote,graph);$('semantic').before(graphPanel);
function svg(tag,attrs,text){const e=document.createElementNS(svgNS,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;return e}
function drawGraph(q){graph.replaceChildren();const visible=(m.datasets||[]).filter(d=>matches(d,q)),positions={};
 const height=Math.max(170,Math.ceil(visible.length/2)*150);graph.setAttribute('viewBox','0 0 760 '+height);
 const defs=svg('defs',{}),marker=svg('marker',{id:'arrow',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:7,markerHeight:7,orient:'auto-start-reverse'});marker.append(svg('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:'#70949c'}));defs.append(marker);graph.append(defs);
 visible.forEach((d,i)=>positions[d.name]={x:190+(i%2)*380,y:75+Math.floor(i/2)*150});
 for(const r of m.relationships||[]){const a=positions[r.from],b=positions[r.to];if(!a||!b)continue;const horizontal=a.y===b.y,sign=b.x>a.x?1:-1;
 const start=horizontal?{x:a.x+115*sign,y:a.y}:{x:a.x,y:a.y+32};const end=horizontal?{x:b.x-115*sign,y:b.y}:{x:b.x,y:b.y-32};
 const line=svg('path',{d:'M '+start.x+' '+start.y+' L '+end.x+' '+end.y,fill:'none',stroke:'#70949c','stroke-width':2,'stroke-dasharray':'6 4','marker-end':'url(#arrow)'});line.append(svg('title',{},r.from+' → '+r.to+' '+r.cardinality));line.style.cursor='pointer';line.addEventListener('click',()=>inspect('关系 · '+(r.id||r.from+' → '+r.to),r));graph.append(line,svg('text',{x:(start.x+end.x)/2+8,y:(start.y+end.y)/2-8,fill:'#536777','font-size':13},r.cardinality));}
 for(const d of visible){const p=positions[d.name],g=svg('g',{tabindex:0,role:'button','aria-label':'查看数据集 '+d.name});g.style.cursor='pointer';g.append(svg('rect',{x:p.x-114,y:p.y-31,width:228,height:62,rx:10,fill:'#eef8f6',stroke:'#42847f'}),svg('text',{x:p.x,y:p.y-4,'text-anchor':'middle',fill:'#172d3b','font-size':15},d.name),svg('text',{x:p.x,y:p.y+17,'text-anchor':'middle',fill:'#536777','font-size':12},'source: '+(d.source||'待补充')));g.addEventListener('click',()=>inspect('数据集 · '+d.name,d));g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' ')inspect('数据集 · '+d.name,d)});graph.append(g)}
}
function render(){const q=$('search').value.toLowerCase(), filter=$('filter').value;
 for(const id of ['datasets','relations','metrics','gaps','reports'])$(id).replaceChildren();
 let shown=0;
 for(const d of m.datasets||[]){if(!matches(d,q))continue;shown++;const b=element('button',undefined,'card');b.append(element('h3',d.cn||d.name),element('div',d.name+' → '+(d.source||'待补充物理来源'),'muted'),element('div',d.grain||'粒度待确认'));b.addEventListener('click',()=>inspect('数据集 · '+d.name,d));$('datasets').append(b)}
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
