"""Maintainer integration exercise over synthetic fixtures; no SQL execution."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/industry'


def run_case(name, output, *, fixture_root=FIXTURES):
    fixture = Path(fixture_root) / name
    brief = json.loads((fixture / 'brief.json').read_text(encoding='utf-8'))
    contract = brief['handoff']
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='industry-handoff-') as tmp:
        work = Path(tmp); project = work / 'project'; calls = []
        def cli(script, *args):
            proc = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'scripts' / script), *map(str, args)], capture_output=True, encoding='utf-8', cwd=work)
            data = json.loads(proc.stdout)
            calls.append({'script': script, 'command': [str(a) for a in args if str(work) not in str(a)], 'ok': data.get('ok')})
            if proc.returncode or data.get('ok') is False: raise AssertionError(str(data)[:3000])
            return data['result'] if script == 'knowledge.py' else data
        def knowledge(*args): return cli('knowledge.py', '--project', project, *args)
        knowledge('import', '--file', fixture/'schema.sql')
        imported = knowledge('import', '--file', fixture/'policy-v1.txt')
        state = knowledge('state')
        source = next(s for s in state['sources'] if s['name']=='policy-v1.txt')
        rev = source['revisions'][-1]
        evidence = [{'source_id':source['id'], 'revision':1, 'fragment_id':f['id'], 'quote':f['text']} for f in rev['parsed']['fragments']]
        ddl_source = next(s for s in state['sources'] if s['name']=='schema.sql')
        ddl_evidence = [{'source_id':ddl_source['id'], 'revision':1, 'fragment_id':f['id'], 'quote':f['text']} for f in ddl_source['revisions'][-1]['parsed']['fragments']]
        assets=[]
        def asset(aid, kind, label, definition, refs=(), **extra):
            a={'id':aid,'kind':kind,'name':label,'definition':definition,'domain':name,'scope':contract['scope'],'refs':list(refs),'evidence': evidence, **extra};assets.append(a);return a
        tables = sorted({f.split('.')[0] for f in contract['required_fields']})
        for table in tables:
            a=asset('table.'+table,'dataset',table,'DDL physical table; business ownership unknown',properties={'unknown':'business ownership unknown'});a['evidence']=ddl_evidence
        for field in contract['required_fields']:
            table,column=field.split('.')
            a=asset('field.'+field,'field',field,'DDL physical column '+field,['table.'+table],properties={'column':column,'value_type':'physical'});a['evidence']=ddl_evidence
            asset('meaning.'+field,'attribute','业务字段 '+field,'用于'+contract['name']+'；按政策规则解释；物理身份不证明产权',['rule.measurement'],properties={'value_type':'declared_reference'})
            asset('mapping.'+field,'mapping','映射 '+field,'当前合成案例字段对应',['field.'+field,'meaning.'+field],**{'from':'meaning.'+field,'to':'field.'+field,'predicate':'对应物理字段','relation_type':'maps_to'})
        asset('rule.measurement','rule',contract['name']+'计量规则',contract['inclusions']+'；'+contract['exclusions'],properties={'condition':contract['inclusions'],'requirement':contract['exclusions']})
        for i,relation in enumerate(contract['required_relations']):
            left,right=relation.split('=');lt,lc=left.split('.');rt,rc=right.split('.')
            asset('relation.'+str(i),'relation',relation,contract['relationship'],['field.'+left,'field.'+right],**{'from':'table.'+lt,'to':'table.'+rt,'predicate':contract['relationship'],'relation_type':'business'},properties={'cardinality':'many_to_one','ownership':'unknown'})
        roots=[a['id'] for a in assets]
        asset('metric.main','metric',contract['name'],brief['cases'][0]['request'],roots,properties={k:contract[k] for k in ['unit','grain','time_scope','inclusions','exclusions']})
        payload=work/'assets.json';payload.write_text(json.dumps(assets,ensure_ascii=False),encoding='utf-8')
        knowledge('edit','--file',payload,'--confirm')
        inspected=knowledge('inspect','--id','metric.main')
        assert inspected['blockers']==0, inspected
        package=output/(name+'.zip'); package.unlink(missing_ok=True)
        exported=knowledge('export','--id','metric.main','--out',package)
        before=hashlib.sha256(package.read_bytes()).hexdigest()
        with zipfile.ZipFile(package) as z: model=json.loads(z.read('model.json'))
        byid={a['id']:a for a in model['assets']}
        assert set(roots+['metric.main'])==set(byid)
        assert all('field.'+f in byid and 'mapping.'+f in byid for f in contract['required_fields'])
        assert all('relation.'+str(i) in byid for i in range(len(contract['required_relations'])))
        assert byid['metric.main']['scope']==contract['scope']
        assert all(a['status']=='confirmed' for a in byid.values())
        context=cli('semantic_read.py','--package',package,'context','--id','metric.main')
        sources=cli('semantic_read.py','--package',package,'sources','--id','metric.main')
        assert context['status']=='ok' and context['request_complete'] and not context['missing_dependencies']
        assert set(context['required_asset_ids']) == set(byid)
        assert sources['is_latest']=='unknown_offline' and sources['request_complete']
        assert sources['evidence'] and all(e['status']=='available' for e in sources['evidence'])
        assert all(e['assertion']['revision']==1 for e in sources['evidence'])
        assert byid['rule.measurement']['properties']['requirement']==contract['exclusions']
        assert all(a.get('properties',{}).get('ownership')=='unknown' for a in byid.values() if a['kind']=='relation')
        knowledge('import','--file',fixture/'policy-v2.txt','--source-id',source['id'])
        updated=knowledge('state');new_source=next(s for s in updated['sources'] if s['id']==source['id'])
        assert new_source['current_revision']==2
        assert next(a for a in updated['assets'] if a['id']=='metric.main')['status']=='needs_review'
        changed=knowledge('inspect','--id','metric.main')
        assert any(i['code']=='NEWER_SOURCE_REVIEW' for i in changed['issues'])
        assert hashlib.sha256(package.read_bytes()).hexdigest()==before
        old_context=cli('semantic_read.py','--package',package,'context','--id','metric.main')
        assert old_context['is_latest']=='unknown_offline' and old_context['status']=='ok'
        result={'industry':name,'passed':True,'validation_scope':'configuration_delivery_only','independent_business_review':'not_performed_by_runner','asset_count':len(byid),'required_fields':contract['required_fields'],'required_relations':contract['required_relations'],'scope':contract['scope'],'old_package_sha256':before,'source_revision':2,'unknown_status':contract['unknown_status'],'inspection':inspected,'updated_inspection':changed,'context':context,'sources':sources,'calls':calls,'not_exercised':'rows calculation, production execution, business approval'}
        (output/(name+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--case',action='append');p.add_argument('--out',type=Path,default=ROOT/'tmp-freeze034/industry-handoff');args=p.parse_args()
    results=[run_case(n,args.out) for n in (args.case or sorted(d.name for d in FIXTURES.iterdir() if d.is_dir()))]
    print(json.dumps({'passed':len(results),'industries':[r['industry'] for r in results]},ensure_ascii=False))

if __name__=='__main__':main()
