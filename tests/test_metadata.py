"""Catalog lifecycle counterexamples: real SQLite, transactional API and independent snapshots."""
import copy
import io
import json
from pathlib import Path
import sqlite3
import os
import socket
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import uuid
import zipfile

from workbench.db_metadata import capture, classify, profile
from workbench.knowledge import KnowledgeService
from workbench.metadata_service import asset_id
from workbench.semantic_package import SemanticPackage
from workbench.store import Store, Conflict


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dbpath = self.root / '业务 sample.db'
        self.sql('CREATE TABLE plant(id INTEGER PRIMARY KEY, moisture REAL, note TEXT); CREATE TABLE care(id INTEGER PRIMARY KEY, plant_id INTEGER REFERENCES plant(id))')
        self.s = KnowledgeService(Store(self.root / 'project'))
        self.config = dict(name='Plants / 植物', engine='sqlite', path=str(self.dbpath), tables=['plant','care'], auto_indexes=True)
        self.conn = self.call('metadata_connect', connection=self.config)['connection']['id']

    def tearDown(self):
        self.tmp.cleanup()

    def sql(self, sql):
        db = sqlite3.connect(self.dbpath)
        try:
            db.executescript(sql)
        finally:
            db.close()

    def call(self, method, **payload):
        return getattr(self.s, method)({'revision':self.s.store.read()['revision'], 'operation_id':uuid.uuid4().hex, **payload})['result']

    def scan(self):
        return self.call('metadata_scan', connection_id=self.conn)

    def accept(self, result):
        for gid in result['scan']['group_ids']:
            self.call('review', group_id=gid, action='accept')

    def question(self, cases=None):
        field = asset_id(self.conn,'plant','moisture')
        self.call('edit', confirm=True, asset={'id':'water_rule','kind':'rule','name':'Watering / 浇水',
            'definition':'Synthetic moisture threshold, not horticultural advice', 'domain':'Gardening', 'scope':{'site':'demo'},
            'refs':[field], 'properties':{'condition':'moisture < 30','requirement':'Review watering'},
            'evidence':[{'type':'manual','quote':'Synthetic test operator declares the field binding','actor':'test-operator'}]})
        return self.call('scenario', scenario={'title':'When to water?', 'question':'Explain the watering threshold',
            'intent':'explain','asset_ids':['water_rule'],'acceptance':{'required_asset_ids':['water_rule',field], 'cases':cases or []}})['scenario']['id']

    def test_complete_roundtrip_automatic_index_and_independent_consumer(self):
        self.accept(self.scan()); qid=self.question()
        with self.assertRaisesRegex(ValueError,'回归'): self.call('publish',scenario_id=qid)
        r=self.call('metadata_regress',connection_id=self.conn)['regression']
        self.assertEqual(r['status'],'passed'); self.assertFalse(r['answer_verified'])
        original=self.call('publish',scenario_id=qid); original_bytes=self.s.download(original['snapshot_id'])
        self.sql('CREATE INDEX idx_moisture ON plant(moisture)')
        changed=self.scan();self.assertEqual(changed['status'],'automatically_adjusted')
        self.assertEqual(changed['scan']['affected_questions'][0]['id'],qid)
        with self.assertRaisesRegex(ValueError,'回归'):self.call('publish',scenario_id=qid)
        self.assertEqual(self.call('metadata_regress',connection_id=self.conn)['regression']['status'],'passed')
        published=self.call('publish',scenario_id=qid)
        self.assertEqual(original_bytes,self.s.download(original['snapshot_id']))
        with zipfile.ZipFile(io.BytesIO(self.s.download(published['snapshot_id']))) as z:
            p=SemanticPackage({n:z.read(n) for n in z.namelist()})
            self.assertIn(asset_id(self.conn,'plant','moisture'),p.index)
            self.assertNotIn(str(self.dbpath),z.read('sources.json').decode())
        self.s=KnowledgeService(Store(self.root/'project'))
        self.assertEqual(self.scan()['status'],'unchanged')

    def test_manual_column_change_and_stale_external_capture_block_review(self):
        self.accept(self.scan());self.question()
        self.sql('ALTER TABLE plant ADD COLUMN humidity REAL')
        r=self.scan();self.assertEqual(r['status'],'review_required')
        self.sql('ALTER TABLE plant ADD COLUMN temperature REAL')
        baseline=self.s.store.read()['revision']
        with self.assertRaises(Conflict):self.accept(r)
        self.assertEqual(baseline,self.s.store.read()['revision'])
        latest=self.scan();self.accept(latest)
        self.assertIn(asset_id(self.conn,'plant','temperature'),{a['id'] for a in self.s.state()['assets']})
        with self.assertRaises(ValueError):self.accept(r)

    def test_unreviewed_tables_not_lost_when_another_table_changes(self):
        first=self.scan()
        self.sql('ALTER TABLE plant ADD COLUMN humidity REAL')
        second=self.scan();self.accept(second)
        self.assertIn(asset_id(self.conn,'care'),{a['id'] for a in self.s.state()['assets']})
        self.assertEqual(len([a for a in self.s.state()['assets'] if a['kind']=='relation']),1)
        with self.assertRaises(ValueError):self.accept(first)

    def test_failed_capture_and_idempotent_retry_never_advance_or_reread(self):
        req=dict(operation_id=uuid.uuid4().hex,revision=self.s.store.read()['revision'],connection_id=self.conn)
        original=self.s.metadata_scan(req)
        with patch('workbench.metadata_service.capture',side_effect=AssertionError('must not reread')):
            self.assertEqual(original,self.s.metadata_scan(req))
        before=self.s.store.read()
        with patch('workbench.metadata_service.capture',side_effect=ValueError('unavailable')):
            with self.assertRaises(ValueError):self.scan()
        self.assertEqual(before,self.s.store.read())

    def test_operator_edits_prevent_automatic_overwrite(self):
        self.accept(self.scan())
        asset=copy.deepcopy(next(a for a in self.s.state()['assets'] if a['id']==asset_id(self.conn,'plant','moisture')))
        asset['definition']='Operator clarified measurement; keep this until reviewed'
        self.call('edit',asset=asset,confirm=True)
        self.sql('CREATE INDEX idx_moisture ON plant(moisture)')
        r=self.scan();self.assertEqual(r['status'],'review_required')
        found=next(a for a in self.s.state()['assets'] if a['id']==asset['id'])
        self.assertEqual(found['definition'],asset['definition'])

    def test_missing_field_requires_mapping_repair(self):
        self.accept(self.scan());qid=self.question()
        self.sql('ALTER TABLE plant RENAME COLUMN moisture TO moisture_pct')
        self.accept(self.scan())
        r=self.call('metadata_regress',connection_id=self.conn)['regression']
        self.assertEqual(r['status'],'blocked')
        with self.assertRaises(ValueError):self.call('publish',scenario_id=qid)

    def test_manual_observation_becomes_stale_after_metadata_change(self):
        self.accept(self.scan());qid=self.question([{'id':'boundary','expectation':'At 30, do not require watering'}])
        def assess():
            checked=self.s.scenario_check({'scenario_id':qid})
            self.call('scenario_assess',scenario_id=qid,case_id='boundary',basis_fingerprint=checked['acceptance']['basis_fingerprint'],outcome='passed',observed='Synthetic threshold 30 is excluded',evidence='Independent fixture arithmetic: 30 < 30 is false',actor='test-operator')
        assess();self.assertEqual(self.call('metadata_regress',connection_id=self.conn)['regression']['status'],'passed')
        self.sql('CREATE INDEX idx_moisture ON plant(moisture)');self.scan()
        self.assertEqual(self.call('metadata_regress',connection_id=self.conn)['regression']['status'],'blocked')
        assess();self.assertEqual(self.call('metadata_regress',connection_id=self.conn)['regression']['status'],'passed')

    def test_unrelated_question_can_publish_and_does_not_clear_pending_scope(self):
        self.accept(self.scan());self.question()
        self.call('edit',confirm=True,asset={'id':'unrelated','kind':'term','name':'Other','definition':'Other scope','domain':'Other','scope':'Other','evidence':[{'type':'manual','quote':'Explicit synthetic term','actor':'test'}]})
        self.sql('ALTER TABLE plant ADD COLUMN humidity REAL');self.scan()
        self.call('publish',asset_ids=['unrelated'])
        self.assertTrue(self.s.state()['connections'][0]['dirty_asset_ids'])

    def test_removing_editable_metadata_properties_does_not_bypass_guard(self):
        self.accept(self.scan());qid=self.question()
        for a in self.s.state()['assets']:
            if a.get('properties',{}).get('metadata_connection'):
                a['properties'].pop('metadata_connection');self.call('edit',asset=a,confirm=True)
        self.sql('ALTER TABLE plant ADD COLUMN humidity REAL')
        with self.assertRaises(Conflict):self.call('publish',scenario_id=qid)

    def test_only_catalog_reads_no_user_sql_no_creation_and_no_secret_leak(self):
        self.sql("INSERT INTO plant VALUES(1,5,'NEVER_EXPORT_BUSINESS_ROW')")
        before=self.dbpath.read_bytes(); r=capture(self.config)
        self.assertNotIn('NEVER_EXPORT_BUSINESS_ROW',json.dumps(r));self.assertEqual(before,self.dbpath.read_bytes())
        for key in ['password','sql','options']:
            with self.assertRaises(ValueError):profile({**self.config,key:'do not execute'})
        missing=self.root/'missing.db'
        with self.assertRaises(ValueError):capture({**self.config,'path':str(missing)})
        self.assertFalse(missing.exists())
        with patch('workbench.db_metadata._sqlite',side_effect=RuntimeError('SECRET VALUE')):
            with self.assertRaisesRegex(ValueError,'^Metadata read failed') as error:capture(self.config)
            self.assertNotIn('SECRET VALUE',str(error.exception))

    def test_unique_index_is_manual_and_unselected_fk_target_is_gap(self):
        self.accept(self.scan());self.sql('CREATE UNIQUE INDEX u_note ON plant(note)')
        self.assertEqual(self.scan()['status'],'review_required')
        other=self.call('metadata_connect',connection={**self.config,'name':'Limited','tables':['care']})['connection']['id']
        self.accept(self.call('metadata_scan',connection_id=other))
        dataset=next(a for a in self.s.state()['assets'] if a['id']==asset_id(other,'care'))
        self.assertTrue(dataset['properties']['knowledge_gaps'])

    def test_rejected_changes_only_reproposed_on_explicit_refresh(self):
        r=self.scan();gid=r['scan']['group_ids'][0]
        self.call('review',group_id=gid,action='reject',reason='Need to inspect catalog again')
        self.assertEqual(self.scan()['status'],'unchanged')
        with self.assertRaises(ValueError):self.accept(r)
        revised=self.call('metadata_scan',connection_id=self.conn,refresh_review=True)
        self.assertNotEqual(revised['scan']['group_ids'],r['scan']['group_ids']);self.accept(revised)

    def test_physical_identity_cannot_be_merged_away_from_connection(self):
        self.accept(self.scan())
        with self.assertRaisesRegex(ValueError,'物理身份'):
            self.call('merge',survivor_id=asset_id(self.conn,'plant'),merged_id=asset_id(self.conn,'care'))

    def test_remote_tls_and_named_credentials_are_enforced(self):
        p=dict(name='TLS test',engine='postgresql',host='db.example.test',port=5432,database='test',schema='public',
               user='reader',password_env='SPECIFIC_TEST_SECRET',tables=['plant'])
        addresses=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('192.0.2.1',5432))]
        with patch.dict(os.environ,{'SPECIFIC_TEST_SECRET':'do-not-store'}), patch('socket.getaddrinfo',return_value=addresses):
            db=MagicMock();db.__enter__.return_value=db;db.execute.return_value.fetchone.return_value=None
            with patch('psycopg.connect',return_value=db) as connect:
                capture(p)
                self.assertEqual(connect.call_args.kwargs['sslmode'],'verify-full')
                self.assertEqual(connect.call_args.kwargs['password'],'do-not-store')
                self.assertIn('READ ONLY',db.execute.call_args_list[0].args[0])
            with patch('pymysql.connect',return_value=db) as connect, patch('workbench.db_metadata._mysql_capture',return_value={'plant':None}):
                capture({**p,'engine':'mysql','schema':'test'})
                self.assertTrue(connect.call_args.kwargs['ssl_verify_cert']);self.assertTrue(connect.call_args.kwargs['ssl_verify_identity'])
                self.assertFalse(connect.call_args.kwargs['local_infile'])

    def test_metadata_and_mapped_ipv6_endpoints_are_denied(self):
        for address in ['169.254.169.254','::ffff:169.254.169.254','fd00:ec2::254']:
            answers=[(socket.AF_INET6,socket.SOCK_STREAM,6,'',(address,5432))]
            with patch('socket.getaddrinfo',return_value=answers),self.assertRaisesRegex(ValueError,'not allowed'):
                capture(dict(name='blocked',engine='postgresql',host='blocked.example',port=5432,database='test',schema='public',
                    user='reader',password_env='UNUSED',tables=['plant']))

    def test_regression_history_displays_stale_basis_without_rewriting_record(self):
        self.accept(self.scan());qid=self.question()
        self.assertEqual(self.call('metadata_regress',connection_id=self.conn)['regression']['status'],'passed')
        a=copy.deepcopy(next(a for a in self.s.state()['assets'] if a['id']=='water_rule'))
        a['definition']='Explicitly revised synthetic definition';self.call('edit',asset=a,confirm=True)
        self.assertEqual(self.s.state()['metadata_regressions'][-1]['current_status'],'stale')
        self.assertEqual(self.s.store.read()['document']['knowledge']['metadata_regressions'][-1]['status'],'passed')


if __name__=='__main__':unittest.main()
