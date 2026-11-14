#!/usr/bin/env python3
"""Live import verification for a disposable local Neo4j instance; never a production loader."""
import argparse
import csv
import io
import json
from pathlib import Path
import sys
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from workbench.semantic_package import read_package
from workbench.neo4j_export import export_neo4j


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fixtures',type=Path,required=True)
    p.add_argument('--import-dir',type=Path,required=True);p.add_argument('--port',type=int,default=57474);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();url=f'http://127.0.0.1:{args.port}/db/neo4j/tx/commit'
    def query(statement,parameters=None):
        data=json.dumps({'statements':[{'statement':statement,'parameters':parameters or {}}]}).encode()
        req=urllib.request.Request(url,data,{'Content-Type':'application/json'})
        result=json.load(urllib.request.urlopen(req,timeout=45));assert not result['errors'],result['errors']
        return [d['row'] for d in result['results'][0]['data']]
    version=query('CALL dbms.components() YIELD name,versions RETURN name,versions')
    results=[]
    for source in sorted(args.fixtures.glob('*/semantic.zip')):
        package=read_package(source);content,manifest=export_neo4j(package)
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            for name in z.namelist():
                if name.endswith('.csv'):(args.import_dir/name).write_bytes(z.read(name))
            script='\n'.join(line for line in z.read('import.cypher').decode().splitlines() if not line.startswith('//'))
            statements=[s.strip() for s in script.split(';') if s.strip()]
        ns=manifest['namespace']
        for iteration in range(2):
            for statement in statements:query(statement)
            assets=query('MATCH (a:SemanticAsset {namespace:$ns}) RETURN a.id,a.asset_json',{'ns':ns})
            assert {aid:json.loads(value) for aid,value in assets}==package.index
            edges=query('MATCH (a:SemanticAsset {namespace:$ns})-[r:SEMANTIC_RELATION]->(b:SemanticAsset {namespace:$ns}) RETURN r.id,a.id,b.id,r.predicate,r.relation_type',{'ns':ns})
            expected={a['id']:(package.redirects.get(a['from'],a['from']),package.redirects.get(a['to'],a['to']),a.get('predicate',''),a.get('relation_type','business')) for a in package.index.values() if a['kind']=='relation'}
            assert {r[0]:tuple(r[1:]) for r in edges}==expected
            saved=query('MATCH (s:SemanticSnapshot {namespace:$ns}) RETURN s.model_json,s.sources_json,s.manifest_json',{'ns':ns})
            assert len(saved)==1 and [json.loads(x) for x in saved[0]]==[package.model,package.source_records,package.manifest]
            counts=query('MATCH (e:SemanticEvidence {namespace:$ns}) RETURN count(e)',{'ns':ns})
            assert counts[0][0]==manifest['counts']['evidence']
        results.append({'fixture':source.parent.name,'namespace':ns,'status':'passed','reimports':2,'counts':manifest['counts']})
        print(source.parent.name,'import and reimport passed',flush=True)
    assert query('MATCH (a:SemanticAsset)-[]->(b:SemanticAsset) WHERE a.namespace<>b.namespace RETURN count(*)')[0][0]==0
    report={'version':version,'passed':len(results),'results':results,'scope':'isolated loopback Neo4j; CSV/Cypher import, byte-equivalent JSON, directed relationships, evidence and sequential idempotency'}
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
