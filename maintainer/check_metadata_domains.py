#!/usr/bin/env python3
"""Real, disposable database fixtures for the four-domain catalog-to-publication chain.

Admin credentials are used only by this maintainer harness to seed/alter synthetic tables.
The shipped connector receives a separate SELECT-only account and never business SQL.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from maintainer.check_cross_domain import load_fixture,make_project
from workbench.metadata_service import asset_id
from workbench.semantic_package import read_package
from workbench.neo4j_export import export_neo4j


def run_domain(engine,domain,out,options):
    out.mkdir(parents=True,exist_ok=False)
    tag='m_'+domain+'_'+uuid.uuid4().hex[:8]
    child=tag+'_event'
    if engine=='sqlite':
        connection=sqlite3.connect(out/'source.db')
        profile=dict(name=domain+' catalog',engine=engine,path=str(out/'source.db'),tables=[tag,child],auto_indexes=True)
        version=sqlite3.sqlite_version
    else:
        admin=os.environ[options.admin_env]
        profile=dict(name=domain+' catalog',engine=engine,host='127.0.0.1',port=options.postgres_port if engine=='postgresql' else options.mysql_port,
            database=options.database,schema='public' if engine=='postgresql' else options.database,
            user='metadata_reader',password_env=options.reader_env,tables=[tag,child],auto_indexes=True)
        if engine=='postgresql':
            import psycopg
            connection=psycopg.connect(host='127.0.0.1',port=options.postgres_port,dbname=options.database,user='testadmin',password=admin,autocommit=True)
            version=connection.execute('SHOW server_version').fetchone()[0]
        else:
            import pymysql
            connection=pymysql.connect(host='127.0.0.1',port=options.mysql_port,database=options.database,user='root',password=admin,autocommit=True)
            with connection.cursor() as c:c.execute('SELECT VERSION()');version=c.fetchone()[0]
    def sql(statement):
        if engine=='mysql':
            with connection.cursor() as c:c.execute(statement)
        else:connection.execute(statement)
        if engine=='sqlite':connection.commit()
    try:
        sql(f'CREATE TABLE {tag}(id INTEGER PRIMARY KEY, value DECIMAL(10,2), note VARCHAR(100))')
        sql(f'CREATE TABLE {child}(id INTEGER PRIMARY KEY, subject_id INTEGER, FOREIGN KEY(subject_id) REFERENCES {tag}(id))')
        sql(f"INSERT INTO {tag} VALUES(1,30,'BUSINESS_ROW_CANARY_DO_NOT_EXPORT')")
        if engine=='postgresql':
            sql(f'GRANT SELECT ON {tag},{child} TO metadata_reader')
        if engine=='mysql':
            for table in [tag,child]:sql(f"GRANT SELECT ON {options.database}.{table} TO 'metadata_reader'@'127.0.0.1'")
        fixture=load_fixture(domain);s,call=make_project(fixture,out/'project')
        cid=call('metadata_connect',connection=profile)['connection']['id']
        def scan():return call('metadata_scan',connection_id=cid)
        def accept(r):
            for gid in r['scan']['group_ids']:call('review',group_id=gid,action='accept',reason='Synthetic test operator reviewed catalog changes')
        first=scan();accept(first)
        old_field=asset_id(cid,tag,'value')
        case=fixture['cases'][0];root_id=case['asset_ids'][0]
        a=copy.deepcopy(next(a for a in s.state()['assets'] if a['id']==root_id))
        original_definition=a['definition'];a['refs']=list(dict.fromkeys(a.get('refs',[])+[old_field]))
        call('edit',asset=a,confirm=True)
        q=call('scenario',scenario={'title':domain+' metadata-dependent question','question':case['question'],'intent':case['intent'],
            'asset_ids':case['asset_ids'],'acceptance':{'required_asset_ids':case['expected_required_ids']+[old_field],
            'required_gap_codes':case.get('expected_gap_codes',[]),'cases':[{'id':'binding','expectation':'The explicitly linked physical column is present in this context; no business rows are supplied'}]}})['scenario']
        def regress():return call('metadata_regress',connection_id=cid)['regression']
        def assess(field):
            checked=s.scenario_check({'scenario_id':q['id'],'limit':500})
            assert field in checked['reader']['context']['required_asset_ids']
            assert checked['acceptance']['context_contract']['status']=='passed'
            call('scenario_assess',scenario_id=q['id'],case_id='binding',basis_fingerprint=checked['acceptance']['basis_fingerprint'],
                outcome='passed',observed='Context includes the explicit current physical field: '+field,
                evidence='Synthetic fixture DDL and actual context required_asset_ids, not a business-value calculation',actor='maintainer-test-operator')
        reports=[regress()];assert reports[-1]['status']=='blocked'
        assess(old_field);reports.append(regress());assert reports[-1]['status']=='passed'
        base=call('publish',scenario_id=q['id']);base_bytes=s.download(base['snapshot_id'])
        sql(f'CREATE INDEX {tag}_value_idx ON {tag}(value)')
        automatic=scan();assert automatic['status']=='automatically_adjusted',automatic['scan']['changes']
        assert automatic['scan']['affected_questions'][0]['id']==q['id']
        reports.append(regress());assert reports[-1]['status']=='blocked' # prior observations become stale
        assess(old_field);reports.append(regress());assert reports[-1]['status']=='passed'
        call('publish',scenario_id=q['id'])
        sql(f'ALTER TABLE {tag} ADD COLUMN confidence DECIMAL(5,2)')
        addition=scan();assert addition['status']=='review_required'
        try:call('publish',scenario_id=q['id']);raise AssertionError('Unreviewed changes published')
        except ValueError:pass
        accept(addition);assess(old_field);reports.append(regress());assert reports[-1]['status']=='passed'
        call('publish',scenario_id=q['id'])
        sql(f'ALTER TABLE {tag} RENAME COLUMN value TO measured_value')
        renamed=scan();assert renamed['status']=='review_required';accept(renamed)
        reports.append(regress());assert reports[-1]['status']=='blocked'
        new_field=asset_id(cid,tag,'measured_value')
        a=copy.deepcopy(next(a for a in s.state()['assets'] if a['id']==root_id));assert a['definition']==original_definition
        a['refs']=[new_field if x==old_field else x for x in a['refs']];call('edit',asset=a,confirm=True)
        q['acceptance']['required_asset_ids']=[new_field if x==old_field else x for x in q['acceptance']['required_asset_ids']]
        q=call('scenario',scenario=q)['scenario'];assess(new_field);reports.append(regress());assert reports[-1]['status']=='passed'
        final=call('publish',scenario_id=q['id']);package=out/'semantic.zip';package.write_bytes(s.download(final['snapshot_id']))
        assert s.download(base['snapshot_id'])==base_bytes
        read=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/semantic_read.py'),'--package',str(package),'task','--limit','500'],capture_output=True,text=True,encoding='utf-8',cwd=out,timeout=30)
        assert read.returncode==0,read.stdout+read.stderr
        consumer=json.loads(read.stdout);assert new_field in consumer['context']['required_asset_ids'];assert old_field not in consumer['context']['required_asset_ids']
        assert 'BUSINESS_ROW_CANARY_DO_NOT_EXPORT' not in str(read_package(package).source_records)
        neo,manifest=export_neo4j(read_package(package));(out/'neo4j.zip').write_bytes(neo)
        report={'engine':engine,'version':version,'domain':domain,'synthetic_only':True,'status':'passed','connection_id':cid,
            'question_id':q['id'],'regressions':reports,'initial_scan':first,'automatic_index_scan':automatic,'column_addition':addition,'rename':renamed,
            'business_rows_read':0,'answer_verified':False,'independent_consumer':consumer,'neo4j_export':manifest,
            'package_sha256':hashlib.sha256(package.read_bytes()).hexdigest()}
        (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(engine,domain,'passed',flush=True)
        return {k:report[k] for k in ('engine','version','domain','status','business_rows_read','answer_verified','package_sha256')}
    finally:connection.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--engine',choices=['sqlite','postgresql','mysql'],action='append')
    p.add_argument('--postgres-port',type=int,default=55432);p.add_argument('--mysql-port',type=int,default=53306)
    p.add_argument('--database',default='metadata_test');p.add_argument('--admin-env',default='METADATA_TEST_ADMIN');p.add_argument('--reader-env',default='METADATA_TEST_PASSWORD')
    args=p.parse_args()
    if args.out.exists() and any(args.out.iterdir()):p.error('Choose a new empty output directory')
    args.out.mkdir(parents=True,exist_ok=True)
    results=[run_domain(e,d,args.out/(e+'-'+d),args) for e in args.engine or ['sqlite','postgresql','mysql'] for d in ['agriculture','traffic','university','finance']]
    summary={'passed':len(results),'results':results,'limits':['Synthetic databases, not production acceptance','Checks context and recorded observations, not business answers','Neo4j file generation; database import has its own test']}
    (args.out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
