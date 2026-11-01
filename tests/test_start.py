"""First-use paths: independent numbers, safe reopen and import failure isolation."""
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from start import prepare


class FirstUse(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.project=self.root/'project with spaces'

    def test_traffic_counts_and_record_scope_are_different(self):
        service,_=prepare(self.project,demo='traffic')
        for metric,value in [('rows',3),('present',2),('distinct',1)]:
            r=service.bundle({'metric':metric,'columns':['company_id'],'limit':50,'offset':0})
            self.assertEqual(r['metric_value'],value);self.assertEqual(r['matched_row_count'],3)
            self.assertEqual(r['detail_rows'],[['A'],['A'],[None]])
            self.assertEqual(r['status'],'computed_only')
        self.assertEqual(service.store.read()['document']['sample']['provenance'],'demo')

    def test_retail_rejects_other_tenant_and_refunds(self):
        service,_=prepare(self.project,demo='retail')
        r=service.bundle({'metric':'revenue','columns':['amount']})
        self.assertEqual((r['metric_value'],r['matched_row_count'],r['detail_rows']),(130,2,[[100],[30]]))
        self.assertEqual(r['metric_unit'],'元')
        service.store.change(service.store.read()['revision'],'tester','change displayed unit',lambda doc:doc['model']['metrics'][0].update(unit='另一单位'))
        self.assertEqual(service.store.runs()[0]['report']['metric_unit'],'元')

    def test_cannot_reset_existing_project_and_reopen_keeps_history(self):
        service,_=prepare(self.project,demo='traffic')
        service.bundle({'metric':'rows','columns':['company_id']})
        before=hashlib.sha256(service.store.path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,'不会覆盖'):prepare(self.project,demo='retail')
        self.assertEqual(hashlib.sha256(service.store.path.read_bytes()).hexdigest(),before)
        reopened,r=prepare(self.project)
        self.assertEqual(r['status'],'reopened');self.assertEqual(len(reopened.store.runs()),1)
        self.assertEqual(reopened.store.read()['revision'],service.store.read()['revision'])

    def test_invalid_input_does_not_leave_a_project(self):
        bad=self.root/'invalid.json';bad.write_text('{invalid',encoding='utf-8')
        with self.assertRaises(ValueError):prepare(self.project,model=bad)
        self.assertFalse((self.project/'project.sqlite').exists())

    def test_only_ddl_import_keeps_business_draft_without_sample(self):
        ddl=self.root/'orders.sql';original=b'CREATE TABLE orders (id INTEGER PRIMARY KEY, amount INTEGER);'
        ddl.write_bytes(original);service,_=prepare(self.project,ddl=ddl)
        doc=service.store.read()['document']
        self.assertEqual(doc['model']['datasets'][0]['name'],'orders')
        self.assertNotIn('tutorial',doc);self.assertFalse(doc.get('sample'));self.assertEqual(ddl.read_bytes(),original)

    def test_demo_is_not_mixed_with_customer_files(self):
        with self.assertRaisesRegex(ValueError,'不能混合'):prepare(self.project,demo='traffic',sample='customer.sqlite')
        self.assertFalse(self.project.exists())

    def test_model_replacement_removes_demo_tutorial_not_sample_origin(self):
        service,_=prepare(self.project,demo='traffic');state=service.store.read()
        raw=json.dumps(state['document']['model']).encode()
        service.import_file({'revision':state['revision'],'kind':'model','filename':'replacement.json',
            'content':base64.b64encode(raw).decode(),'replace':True})
        doc=service.store.read()['document']
        self.assertNotIn('tutorial',doc);self.assertEqual(doc['sample']['provenance'],'demo')

    def test_mock_children_do_not_inherit_secret_sentinel(self):
        from mocks import run_mock
        with mock.patch.dict(os.environ,{'DELIVERY_SECRET_SENTINEL':'not-a-real-secret'}),mock.patch.object(run_mock.subprocess,'run') as child:
            child.return_value.returncode=0
            run_mock.run_step('environment probe',['example.py'],ROOT)
        self.assertNotIn('DELIVERY_SECRET_SENTINEL',child.call_args.kwargs['env'])


if __name__=='__main__':unittest.main()
