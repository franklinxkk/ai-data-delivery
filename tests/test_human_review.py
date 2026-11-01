import base64
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from start import prepare
from visualize_model import render_html


class HumanReview(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.service,_=prepare(Path(self.tmp.name)/'project',demo='traffic')

    def test_export_uses_current_model_and_stale_report_without_changing_project(self):
        self.service.bundle({'metric':'rows','columns':['company_id'],'expected':{'metric_value':3,'matched_row_count':3,'detail_rows':[['A'],['A'],[None]]}})
        s=self.service.store.read()
        self.service.store.change(s['revision'],'tester','changed scope',lambda d:d['model']['metrics'][0]['filters'].append({'field':'company_id','values':['A']}))
        before=self.service.store.read()
        with zipfile.ZipFile(io.BytesIO(self.service.export())) as z:
            html=z.read('00-human-review.html').decode()
            payload=json.loads(re.search(r'<script id="payload" type="application/json">(.*?)</script>',html,re.S).group(1))
            self.assertEqual(payload['model'],before['document']['model'])
            self.assertTrue(payload['reports'][0]['stale']);self.assertTrue(payload['reports'][0]['binding_errors'])
            self.assertEqual(payload['reports'][0]['report']['status'],'pass')
            manifest=json.loads(z.read('manifest.json'))
            self.assertEqual(manifest['files']['00-human-review.html'],hashlib.sha256(z.read('00-human-review.html')).hexdigest())
            self.assertNotIn('project.sqlite',z.namelist())
        self.assertEqual(self.service.store.read(),before)

    def test_embedded_content_cannot_break_out_of_payload(self):
        data=self.service.review_data();label='</script><script>window.pwned=true</script>'
        data['model']['metrics'][0]['name']=label
        html=render_html(data)
        self.assertNotIn(label,html)
        payload=json.loads(re.search(r'<script id="payload" type="application/json">(.*?)</script>',html,re.S).group(1))
        self.assertEqual(payload['model']['metrics'][0]['name'],label)

    def test_no_report_is_not_invented_as_accepted(self):
        data=self.service.review_data()
        self.assertEqual(data['reports'],[])
        self.assertEqual(data['decisions'],[])
        self.assertEqual(data['ontology']['entities'][0]['evidence']['source'],'model_inferred')


if __name__=='__main__':unittest.main()
