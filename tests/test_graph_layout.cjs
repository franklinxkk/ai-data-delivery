// Independent geometry checks. These do not replace real browser/label-font inspection.
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const EPS=0.1;
const elapsed=()=>performance.now();
const fixtures=['plants','traffic','education','finance'].map(name=>JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/graph-layout',name+'.json'),'utf8')));
const overlaps=(a,b)=>a.x+EPS<b.x+b.width&&a.x+a.width>b.x+EPS&&a.y+EPS<b.y+b.height&&a.y+a.height>b.y+EPS;
const rects=(graph,result)=>graph.nodes.map(n=>({id:n.id,...result.positions[n.id],width:n.width,height:n.height}));
function boundaryDistance(p,r){
  const dx=Math.max(r.x-p.x,0,p.x-r.x-r.width),dy=Math.max(r.y-p.y,0,p.y-r.y-r.height);
  if(dx||dy)return Math.hypot(dx,dy);
  return Math.min(p.x-r.x,r.x+r.width-p.x,p.y-r.y,r.y+r.height-p.y);
}
function crossesRect(a,b,r){
  // Clip against the strict interior, so touching an attachment boundary is legal.
  const lo={x:r.x+1,y:r.y+1},hi={x:r.x+r.width-1,y:r.y+r.height-1};
  let enter=0,leave=1;
  for(const key of ['x','y']){
    const delta=b[key]-a[key];
    if(Math.abs(delta)<1e-9){if(a[key]<=lo[key]||a[key]>=hi[key])return false;continue;}
    let t0=(lo[key]-a[key])/delta,t1=(hi[key]-a[key])/delta;
    if(t0>t1)[t0,t1]=[t1,t0];
    enter=Math.max(enter,t0);leave=Math.min(leave,t1);
    if(enter>=leave)return false;
  }
  return enter<leave;
}
function intersection(a,b,c,d){
  const rx=b.x-a.x,ry=b.y-a.y,sx=d.x-c.x,sy=d.y-c.y,den=rx*sy-ry*sx;
  if(Math.abs(den)<1e-7)return null;
  const t=((c.x-a.x)*sy-(c.y-a.y)*sx)/den,u=((c.x-a.x)*ry-(c.y-a.y)*rx)/den;
  if(t< -1e-5||t>1+1e-5||u< -1e-5||u>1+1e-5)return null;
  return {x:a.x+t*rx,y:a.y+t*ry};
}
function crossingCount(edges,routes){
  let count=0;
  for(let i=0;i<edges.length;i++)for(let j=i+1;j<edges.length;j++){
    const a=edges[i],b=edges[j];
    if([a.from,a.to].some(id=>id===b.from||id===b.to))continue;
    const pa=routes[a.id]?.points||[],pb=routes[b.id]?.points||[],unique=[];
    for(let x=1;x<pa.length;x++)for(let y=1;y<pb.length;y++){
      const hit=intersection(pa[x-1],pa[x],pb[y-1],pb[y]);
      if(hit&&![pa[0],pa.at(-1),pb[0],pb.at(-1)].some(p=>Math.hypot(p.x-hit.x,p.y-hit.y)<2)
        &&!unique.some(p=>Math.hypot(p.x-hit.x,p.y-hit.y)<2))unique.push(hit);
    }
    count+=unique.length;
  }
  return count;
}
function sharedSegmentLength(a,b,c,d){
  if(Math.abs(a.x-b.x)<EPS&&Math.abs(c.x-d.x)<EPS&&Math.abs(a.x-c.x)<EPS)
    return Math.max(0,Math.min(Math.max(a.y,b.y),Math.max(c.y,d.y))-Math.max(Math.min(a.y,b.y),Math.min(c.y,d.y)));
  if(Math.abs(a.y-b.y)<EPS&&Math.abs(c.y-d.y)<EPS&&Math.abs(a.y-c.y)<EPS)
    return Math.max(0,Math.min(Math.max(a.x,b.x),Math.max(c.x,d.x))-Math.max(Math.min(a.x,b.x),Math.min(c.x,d.x)));
  return 0;
}
function measure(graph,result){
  const nodes=rects(graph,result),labels=[],nodeOverlaps=[],labelNodeOverlaps=[],labelOverlaps=[],edgeNodeCrossings=[],labelOtherEdgeCrossings=[];
  for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++)if(overlaps(nodes[i],nodes[j]))nodeOverlaps.push([nodes[i].id,nodes[j].id]);
  for(const e of graph.edges){
    const route=result.routes[e.id];
    if(!route)continue;
    if(e.label&&route.label)labels.push({id:e.id,...route.label});
    for(const n of nodes){
      if(n.id===e.from||n.id===e.to)continue;
      if(route.points.some((p,i)=>i&&crossesRect(route.points[i-1],p,n)))edgeNodeCrossings.push([e.id,n.id]);
    }
  }
  for(const label of labels)for(const n of nodes)if(overlaps(label,n))labelNodeOverlaps.push([label.id,n.id]);
  for(let i=0;i<labels.length;i++)for(let j=i+1;j<labels.length;j++)if(overlaps(labels[i],labels[j]))labelOverlaps.push([labels[i].id,labels[j].id]);
  for(const label of labels)for(const edge of graph.edges){
    if(edge.id===label.id)continue;
    const points=result.routes[edge.id]?.points||[];
    if(points.some((p,i)=>i&&crossesRect(points[i-1],p,label)))labelOtherEdgeCrossings.push([label.id,edge.id]);
  }
  let sharedRouteLength=0;
  const routes=Object.values(result.routes);
  for(let i=0;i<routes.length;i++)for(let j=i+1;j<routes.length;j++)
    for(let a=1;a<routes[i].points.length;a++)for(let b=1;b<routes[j].points.length;b++)
      sharedRouteLength+=sharedSegmentLength(routes[i].points[a-1],routes[i].points[a],routes[j].points[b-1],routes[j].points[b]);
  return {nodes:nodes.length,edges:graph.edges.length,labels:labels.length,nodeOverlaps,labelNodeOverlaps,labelOverlaps,edgeNodeCrossings,
    labelOtherEdgeCrossings,sharedRouteLength:Math.round(sharedRouteLength),crossings:crossingCount(graph.edges,result.routes),bounds:result.bounds};
}
function validate(graph,result,context){
  assert.deepEqual(Object.keys(result.positions).sort(),graph.nodes.map(n=>n.id).sort(),context+' preserves nodes');
  assert.deepEqual(Object.keys(result.routes).sort(),graph.edges.map(e=>e.id).sort(),context+' preserves edges');
  const nodes=new Map(rects(graph,result).map(n=>[n.id,n]));
  const bounds=result.bounds;
  assert.ok(bounds&&['left','top','right','bottom'].every(k=>Number.isFinite(bounds[k])),context+' finite bounds');
  const inside=p=>p.x>=bounds.left-EPS&&p.x<=bounds.right+EPS&&p.y>=bounds.top-EPS&&p.y<=bounds.bottom+EPS;
  for(const n of nodes.values())for(const field of ['x','y','width','height'])assert.ok(Number.isFinite(n[field]),context+' finite node '+n.id);
  for(const n of nodes.values())assert.ok(inside(n)&&inside({x:n.x+n.width,y:n.y+n.height}),context+' bounds include node '+n.id);
  for(const edge of graph.edges){
    const r=result.routes[edge.id];
    assert.ok(Array.isArray(r.points)&&r.points.length>=2,context+' route '+edge.id);
    for(const p of r.points){assert.ok(Number.isFinite(p.x)&&Number.isFinite(p.y),context+' finite route '+edge.id);assert.ok(inside(p),context+' bounds include route '+edge.id);}
    assert.ok(boundaryDistance(r.points[0],nodes.get(edge.from))<=12,context+' source attachment '+edge.id);
    assert.ok(boundaryDistance(r.points.at(-1),nodes.get(edge.to))<=12,context+' target attachment '+edge.id);
    if(edge.label){
      assert.ok(r.label,context+' missing label '+edge.id);
      assert.equal(r.label.text,edge.label,context+' preserves complete relationship name '+edge.id);
      assert.ok(r.label.width>0&&r.label.height>0,context+' label geometry '+edge.id);
      assert.ok(inside(r.label)&&inside({x:r.label.x+r.label.width,y:r.label.y+r.label.height}),context+' bounds include label '+edge.id);
    }
  }
  const metrics=measure(graph,result);
  for(const field of ['nodeOverlaps','labelNodeOverlaps','labelOverlaps','edgeNodeCrossings'])assert.deepEqual(metrics[field],[],context+' '+field);
  return metrics;
}
function oldGrid(graph){
  const nodes=graph.nodes.map(n=>({...n,width:210,height:90}));
  const positions=Object.fromEntries(nodes.map((n,i)=>[n.id,{x:40+(i%3)*320,y:40+Math.floor(i/3)*185}])),routes={};
  for(const e of graph.edges){
    const a=positions[e.from],b=positions[e.to],ax=a.x+105,ay=a.y+45,bx=b.x+105,by=b.y+45;
    let p0,p1,p2,p3,label;
    if(e.reference){p0={x:a.x+105,y:a.y+88};p3={x:b.x+105,y:b.y};p1=p0;p2=p3;}
    else if(e.from===e.to){p0={x:a.x+210,y:ay-22};p1={x:a.x+296,y:ay-38};p2={x:a.x+296,y:ay+38};p3={x:a.x+214,y:ay+22};label={x:a.x+268,y:ay-5};}
    else{
      const dx=bx-ax,dy=by-ay,h=Math.abs(dx)>=210&&(Math.abs(dy)<90||Math.abs(dx)/210>=Math.abs(dy)/90),side=Math.sign(h?dx:dy)||1;
      p0={x:h?ax+side*105:ax,y:h?ay:ay+side*45};p3={x:h?bx-side*109:bx,y:h?by:by-side*49};
      const bend=Math.min(54,Math.max(8,Math.abs(h?p3.x-p0.x:p3.y-p0.y)*.45))*side;
      p1={x:p0.x+(h?bend:0),y:p0.y+(h?0:bend)};p2={x:p3.x-(h?bend:0),y:p3.y-(h?0:bend)};
      label={x:(p0.x+p3.x)/2+(h?0:14),y:(p0.y+p3.y)/2+(h?-9:4)};
    }
    const points=Array.from({length:65},(_,i)=>{const t=i/64,s=1-t;return {x:s*s*s*p0.x+3*s*s*t*p1.x+3*s*t*t*p2.x+t*t*t*p3.x,y:s*s*s*p0.y+3*s*s*t*p1.y+3*s*t*t*p2.y+t*t*t*p3.y};});
    const width=[...e.label].reduce((v,c)=>v+(/[\u0000-\u007f]/.test(c)?6:11),0);
    routes[e.id]={points,label:label&&{text:e.label,x:label.x-width/2,y:label.y-12,width,height:15}};
  }
  return {graph:{...graph,nodes},result:{positions,routes,bounds:{}}};
}
async function run(){
  const engine=require('../workbench/static/graph-layout.js');
  const results={created:new Date().toISOString(),type:'Node geometry verification, not browser screenshot acceptance',
    sourceHashes:Object.fromEntries(['graph-layout.js','vendor/elk.bundled.js','knowledge.js','knowledge.css'].map(file=>[file,crypto.createHash('sha256').update(fs.readFileSync(path.join(__dirname,'../workbench/static',file))).digest('hex')])),
    viewport:{width:1252,height:547,fitPadding:16,source:'Root browser observation of focused canvas; no viewport override'},
    fontCssPx:{nodeName:14,relationship:12,nodeMetadata:11},
    crossingMethod:'Count distinct intersections between non-adjacent edge polylines, ignoring global attachment endpoints and collinear shared segments; old cubic routes sampled at 64 intervals. Same explicit relations and deduplicated references in both graphs.',cases:[]};
  for(const fixture of fixtures){
    const graph={nodes:fixture.nodes.map(n=>({...n,width:172,height:68})),edges:fixture.edges,width:1252,height:547};
    const before=JSON.stringify(graph),start=elapsed(),result=await engine.layout(graph),durationMs=elapsed()-start;
    assert.equal(JSON.stringify(graph),before,'layout does not mutate caller input');
    const metrics=validate(graph,result,fixture.domain),old=oldGrid(graph),baseline=measure(old.graph,old.result);
    const repeated=await engine.layout(graph);
    assert.deepEqual(repeated.positions,result.positions,fixture.domain+' deterministic layout');
    assert.deepEqual(repeated.routes,result.routes,fixture.domain+' deterministic routes');
    const bw=result.bounds.right-result.bounds.left,bh=result.bounds.bottom-result.bounds.top;
    const scale=Math.min(1.3,(graph.width-32)/bw,(graph.height-32)/bh);
    const displayEstimate={scale,nodeNameCssPx:14*scale,relationshipCssPx:12*scale,nodeMetadataCssPx:11*scale,
      occupiedWidth:bw*scale,occupiedHeight:bh*scale,horizontalUtilization:bw*scale/graph.width,verticalUtilization:bh*scale/graph.height};
    results.cases.push({name:fixture.domain,sourceRevision:fixture.source_revision,durationMs,direction:result.direction,displayEstimate,metrics,baseline,positions:result.positions,routes:result.routes});
    console.log(`PASS ${fixture.domain}: ${metrics.nodes} nodes, ${metrics.edges} edges; crossings ${baseline.crossings} -> ${metrics.crossings}; ${Math.round(durationMs)}ms`);
  }
  const finance=results.cases.find(c=>c.name==='finance');
  assert.ok(finance.metrics.crossings<finance.baseline.crossings,'financial topology reduces actual non-adjacent line crossings versus old grid');
  const narrowFixture=fixtures.find(f=>f.domain==='finance');
  const narrow={nodes:narrowFixture.nodes.map(n=>({...n,width:172,height:68})),edges:narrowFixture.edges,width:640,height:565};
  results.cases.push({name:'finance-narrow-canvas',metrics:validate(narrow,await engine.layout(narrow),'finance narrow canvas')});
  const corner={nodes:['a','b','c','d'].map(id=>({id,width:172,height:68})),edges:[
    {id:'ab1',from:'a',to:'b',label:'资产所属机构'},
    {id:'ab2',from:'a',to:'b',label:'机构负责资产的定期巡检与维护任务'},
    {id:'ba',from:'b',to:'a',label:'反向依赖'},
    {id:'bc',from:'b',to:'c',label:'流转给下一对象'},
    {id:'ca',from:'c',to:'a',label:'完成后回到起点'},
    {id:'self',from:'c',to:'c',label:'继承自身定义'},
    {id:'reference',from:'d',to:'b',label:'',reference:true}
  ],width:1252,height:547};
  results.cases.push({name:'cycles-parallel-self-long-label',metrics:validate(corner,await engine.layout(corner),'corner cases')});
  const manual={...corner,positions:{a:{x:40,y:100},b:{x:620,y:100},c:{x:320,y:100},d:{x:320,y:350}}};
  const manualResult=engine.route(manual);
  validate(manual,manualResult,'manual obstacle routing');
  assert.deepEqual({...manualResult.positions},manual.positions,'manual routing does not move nodes');
  results.cases.push({name:'manual-obstacle-routing',metrics:measure(manual,manualResult)});
  const fixed={...corner,positions:{a:{x:900,y:420}},fixed:['a']};
  const fixedResult=await engine.layout(fixed);
  validate(fixed,fixedResult,'fixed node layout');
  assert.deepEqual(fixedResult.positions.a,fixed.positions.a,'fixed node does not move');
  results.cases.push({name:'fixed-node',metrics:measure(fixed,fixedResult)});
  const empty={nodes:[],edges:[],width:1252,height:547};
  results.cases.push({name:'empty',metrics:validate(empty,await engine.layout(empty),'empty graph')});
  const disconnected={nodes:['orphan-a','orphan-b','orphan-c'].map(id=>({id,width:172,height:68})),edges:[],width:1252,height:547};
  results.cases.push({name:'disconnected',metrics:validate(disconnected,await engine.layout(disconnected),'unconnected knowledge')});
  for(const [name,ids,edgeId] of [['special-node-ids',['__proto__','constructor'],'ordinary-edge'],['special-edge-id',['ordinary-a','ordinary-b'],'__proto__']]){
    const special={nodes:ids.map(id=>({id,width:172,height:68})),edges:[{id:edgeId,from:ids[0],to:ids[1],label:'合法稳定身份'}],width:1252,height:547};
    const result=await engine.layout(special);
    results.cases.push({name,metrics:validate(special,result,name)});
    validate(special,engine.route({...special,positions:result.positions}),name+' manual reroute');
  }
  const large={nodes:Array.from({length:80},(_,i)=>({id:'n'+i,width:172,height:68})),edges:Array.from({length:79},(_,i)=>({id:'e'+i,from:'n'+Math.floor(i/3),to:'n'+(i+1),label:'关联对象'+i})),width:1252,height:547};
  const start=elapsed(),largeResult=await engine.layout(large),durationMs=elapsed()-start;
  validate(large,largeResult,'80 node graph');
  assert.ok(durationMs<30000,'80 node layout completes within 30 seconds');
  results.cases.push({name:'80-node',durationMs,metrics:measure(large,largeResult)});
  if(process.env.GRAPH_LAYOUT_REPORT){fs.mkdirSync(path.dirname(process.env.GRAPH_LAYOUT_REPORT),{recursive:true});fs.writeFileSync(process.env.GRAPH_LAYOUT_REPORT,JSON.stringify(results,null,2));}
  console.log('PASS: real domain identity preservation, node/label/route geometry, deterministic layout, cycles, self edges, parallel edges, long labels, fixed/manual positions, bounded 80-node layout');
}
if(require.main===module)run().catch(error=>{console.error(error);process.exitCode=1;});
module.exports={measure,validate,crossingCount,oldGrid};
