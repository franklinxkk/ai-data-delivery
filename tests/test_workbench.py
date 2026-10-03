"""Workbench contracts: private persistence, actual diagnostics and complete answers."""
import base64
import copy
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from workbench.service import Service, compare_rows, lint, consumer_projection, local_json
from workbench.store import Conflict, identity
from workbench.serve import make_server
from _contract import relation_keys


def model():
    return {"version": "test", "custom_root": {"tree": [1, {"value": "keep"}]},
            "datasets": [{"name": "tasks", "source": "tasks", "grain": "每个任务一行", "primary_key": ["id"],
                          "fields": [{"name": "id", "role": "pk"}, {"name": "status", "role": "dim", "enum": ["done", "open"]}],
                          "ai": {"instructions": "统计任务"}, "temporal": {"kind": "current"}, "custom": {"keep": True}}],
            "metrics": [{"id": "total", "name": "任务数", "dataset": "tasks", "type": "count", "expr": "COUNT(*)"}],
            "ontology": {"entities": [{"uid": "task", "name": "任务"}, {"uid": "warning", "name": "预警"}],
                         "relations": [{"from": "任务", "to": "预警", "predicate": "触发", "mapping": "semantic_only", "note": "仅业务声明"}]}}


class WorkbenchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.service = Service(Path(self.tmp.name) / "project")

    def req(self, **extra):
        return {"revision": self.service.store.read()["revision"], **extra}

    def imported(self, content, kind="model", **extra):
        if kind == "model":
            content = yaml.safe_dump(content, allow_unicode=True).encode()
        return self.service.import_file(self.req(kind=kind, filename="source."+kind, content=base64.b64encode(content).decode(), **extra))

    def sample(self):
        p = Path(self.tmp.name) / "input.db"
        c = sqlite3.connect(p)
        c.executescript("CREATE TABLE tasks(id TEXT,status TEXT); INSERT INTO tasks VALUES ('A','done'),('B','open');")
        c.close()
        self.imported(p.read_bytes(), "sample", provenance="demo")

    def test_roundtrip_unknown_fields_history_and_export(self):
        m = model(); self.imported(m)
        self.service.edit(self.req(kind="datasets", key="tasks", patch={"cn": "任务表"}))
        stored = self.service.store.read()["document"]["model"]
        self.assertEqual(stored["custom_root"], m["custom_root"])
        self.assertEqual(stored["datasets"][0]["custom"], {"keep": True})
        with zipfile.ZipFile(io.BytesIO(self.service.export())) as z:
            self.assertEqual(yaml.safe_load(z.read("semantic.yaml")), stored)
            self.assertNotIn("project.sqlite", z.namelist())
            self.assertNotIn("source.model", z.namelist())
        with zipfile.ZipFile(io.BytesIO(self.service.export(True))) as z:
            backup = Path(self.tmp.name) / "restored"; backup.mkdir()
            (backup / "project.sqlite").write_bytes(z.read("project.sqlite"))
        self.assertEqual(Service(backup).store.read(), self.service.store.read())
        self.service.store.restore(1, self.service.store.read()["revision"])
        self.assertEqual(self.service.store.read()["document"]["model"], m)
        self.assertEqual(len(self.service.store.history()), 4)

    def test_revision_conflict_does_not_overwrite(self):
        self.imported(model())
        stale = self.req(kind="datasets", key="tasks", patch={"grain": "错误的旧编辑"})
        self.service.edit(self.req(kind="datasets", key="tasks", patch={"grain": "新版粒度"}))
        with self.assertRaises(Conflict):
            self.service.edit(stale)
        self.assertEqual(self.service.store.read()["document"]["model"]["datasets"][0]["grain"], "新版粒度")

    def test_rename_identity_and_deletion_references(self):
        m=model(); m["datasets"][0]["ontology_ref"]="任务"
        self.imported(m)
        self.service.edit(self.req(kind="entities", key="task", patch={"name": "工作任务"}))
        changed=self.service.store.read()["document"]["model"]
        self.assertEqual(changed["ontology"]["relations"][0]["from"], "工作任务")
        self.assertEqual(changed["datasets"][0]["ontology_ref"], "task")
        with self.assertRaisesRegex(ValueError, "引用"):
            self.service.edit(self.req(kind="datasets", key="tasks", remove=True))
        with self.assertRaisesRegex(ValueError, "引用"):
            self.service.edit(self.req(kind="entities", key="task", remove=True))

    def test_relation_legacy_keys_and_stable_ids(self):
        r={"from":"a","to":"b","join_key_from":"id","join_key_to":"task_id"}
        self.assertEqual(relation_keys(r),(["id"],["task_id"]))
        with self.assertRaises(ValueError):
            relation_keys({**r,"from_columns":["different"]})
        m=model();m["relationships"]=[r];self.imported(m)
        key=identity("relationships",r)
        self.service.edit(self.req(kind="relationships",key=key,patch={"note":"有依据的关联"}))
        self.assertEqual(self.service.store.read()["document"]["model"]["relationships"][0]["id"],key)

    def test_ddl_does_not_execute_and_empty_checks_not_pass(self):
        self.imported(b'CREATE TABLE tasks(id TEXT PRIMARY KEY, amount REAL); DROP TABLE existing;', "ddl")
        s=self.service.state()
        self.assertEqual(s["document"]["model"]["datasets"][0]["primary_key"],["id"])
        self.assertTrue(any(g["property"]=="grain" for g in s["gaps"]))
        r=self.service.check()
        self.assertEqual(r["data"]["status"],"not_ready")
        self.assertEqual(r["links"]["status"],"not_ready")

    def test_answers_need_attribution_and_close_actual_gap(self):
        m=model();del m["datasets"][0]["grain"];self.imported(m)
        gap=next(g for g in self.service.state()["gaps"] if g["property"]=="grain")
        with self.assertRaises(ValueError):
            self.service.answer(self.req(gap=gap["id"],value="每任务一行"))
        self.service.answer(self.req(gap=gap["id"],value="每任务一行",actor="测试业务负责人",role="business_owner",basis="案例定义"))
        self.assertFalse(any(g["id"]==gap["id"] for g in self.service.state()["gaps"]))
        self.assertEqual(len(self.service.state()["document"]["decisions"]),1)

    def test_computed_is_not_verified_and_shapes_are_complete(self):
        self.imported(model());self.sample()
        sample_source=self.service.store.read()["document"]["sources"][-1]
        self.assertIn("checkpoint",sample_source["snapshot_note"])
        self.assertEqual(self.service.query({"metric":"total"})["status"],"computed_only")
        self.assertEqual(self.service.query({"metric":"total","expected":[[2]]})["status"],"pass")
        self.assertEqual(self.service.query({"metric":"total","expected":[[2,25]]})["status"],"fail")
        self.assertFalse(compare_rows([[11]], [[11,25]]))
        self.assertFalse(compare_rows([[None]],[[0]]))
        self.assertFalse(compare_rows([[True]],[[1]]))
        self.assertTrue(compare_rows([[0.6666666]],[[0.6667]]))

    def test_missing_snapshot_is_recorded_as_error_not_http_failure(self):
        self.imported(model());self.sample()
        current=self.service.store.read()
        self.service.store.change(current["revision"],"test","损坏测试快照引用",
                                  lambda doc: doc["sample"].update(id="missing-attachment"))
        result=self.service.check()
        self.assertEqual(result["data"]["status"],"error")
        self.assertEqual(result["links"]["status"],"error")
        self.assertEqual(self.service.query({"metric":"total"})["status"],"error")

    def test_sql_boundary_and_evidence_expiration(self):
        self.imported(model());self.sample();self.service.check();self.service.query({"metric":"total"})
        self.service.store.save_layout({"datasets:tasks":{"x":30,"y":80}})
        self.assertTrue(all(not r["stale"] for r in self.service.store.runs()))
        self.service.edit(self.req(kind="metrics",key="total",patch={"expr":"COUNT(*); DELETE FROM tasks"}))
        self.assertTrue(all(r["stale"] for r in self.service.store.runs()))
        self.assertEqual(self.service.query({"metric":"total"})["status"],"not_ready")
        self.service.edit(self.req(kind="metrics",key="total",patch={"expr":"COUNT(*)"}))
        self.assertEqual(self.service.query({"metric":"total"})["rows"],[[2]])

    def test_scene_profiles_and_unimplemented_runtimes(self):
        self.imported(model())
        for profile in ("metric","nl2sql","action","policy","decision"):
            self.service.scene(self.req(scene={"profile":profile,"question":"案例问题","datasets":["tasks"]}))
        scenarios=self.service.state()["scenarios"]
        self.assertEqual(len(scenarios),5)
        self.assertTrue(all(s["status"]=="needs_input" for s in scenarios))
        self.assertIn("仅完成需求",scenarios[-1]["runtime"])
        with self.assertRaisesRegex(ValueError,"场景"):
            self.service.edit(self.req(kind="datasets",key="tasks",remove=True))

    def test_consumer_endpoint_guard_and_projection(self):
        for endpoint in ("https://example.com", "http://127.0.0.1.evil/", "http://user@127.0.0.1/", "http://127.0.0.1/path"):
            with self.assertRaises(ValueError): local_json(endpoint,"/api/model")
        a={"datasets":[{"name":"x","primary_key":"id","fields":[{"name":"id","role":"pk","cn":"字段"}]}]}
        b={"datasets":[{"name":"x","primaryKey":"id","fields":[{"name":"id","role":"pk","cn":None}],"ignored":None}]}
        self.assertEqual(consumer_projection(a),consumer_projection(b))

    def test_http_origin_host_token_and_persistence(self):
        server=make_server(self.service);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        base=f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(base) as r:
            text=r.read().decode();self.assertIn("frame-ancestors 'none'",r.headers['Content-Security-Policy'])
        token=re.search(r'name="session-token" content="([^"]+)',text)[1]
        def request(path,headers=None,data=None):
            return urllib.request.urlopen(urllib.request.Request(base+path,headers=headers or {},data=json.dumps(data).encode() if data else None))
        for headers in ({},{"X-Workbench-Token":token,"Origin":"http://evil.example"},{"X-Workbench-Token":token,"Host":"evil.example"}):
            with self.assertRaises(urllib.error.HTTPError) as err:request('/api/state',headers)
            self.assertEqual(err.exception.code,403)
        with request('/api/state',{"X-Workbench-Token":token}) as r:
            self.assertEqual(json.load(r)['revision'],0)


class MaturityWorkbenchTest(unittest.TestCase):
    def test_twenty_grade_diagnostics_and_guidance_from_current_facts(self):
        """Run UI service, not the fixture's printed guidance, on all 20 staged inputs."""
        grades=ROOT/'tests/fixtures/grades'
        for spec in sorted(grades.glob('*/*/expected_diagnostics.yaml')):
            with self.subTest(case=str(spec.parent.relative_to(grades))), tempfile.TemporaryDirectory() as td:
                td=Path(td);folder=spec.parent
                for name in ('build_db.py','semantic.yaml'):
                    shutil.copyfile(folder/name,td/name)
                subprocess.run([sys.executable,str(td/'build_db.py')],capture_output=True,check=True,timeout=20)
                svc=Service(td/'project')
                for kind,name in [('model','semantic.yaml'),('sample','domain.db')]:
                    svc.import_file({'revision':svc.store.read()['revision'],'kind':kind,'filename':name,'provenance':'demo',
                                     'content':base64.b64encode((td/name).read_bytes()).decode()})
                expected=yaml.safe_load(spec.read_text(encoding='utf-8'))
                result=svc.check()
                for severity,field in [('ERROR','errors'),('WARN','warnings')]:
                    codes=set(re.findall(r'\[(?:ERROR|WARN)\s+(\w+)\]', '\n'.join(result['model'][field])))
                    self.assertTrue(set(expected['check_model'].get('errors' if field=='errors' else 'warns',[]))<=codes)
                failed={r['id'] for r in result['data']['records'] if r['status']=='fail'}
                self.assertEqual(failed,set(expected['check_constraints'].get('failed_ids',[])))
                self.assertEqual(result['data']['status'],expected['check_constraints']['status'])
                if folder.name=='L0':self.assertTrue(any('grain'==g['property'] for g in result['gaps']))
                if folder.name=='L1':
                    self.assertFalse(result['model']['errors'])
                    self.assertTrue(all(any(fid in hint for hint in result['next']) for fid in failed))
                    # Both axes can fail together; data checks must continue.
                    d=svc.store.read()['document']['model']['datasets'][0]
                    svc.edit({'revision':svc.store.read()['revision'],'kind':'datasets','key':d['name'],'patch':{'grain':''}})
                    combined=svc.check();self.assertTrue(combined['model']['errors'])
                    self.assertEqual({r['id'] for r in combined['data']['records'] if r['status']=='fail'},failed)
                if folder.name=='L2':self.assertTrue(any(g['property']=='on_zero_denominator' for g in result['gaps']))
                if folder.name=='L3':
                    for mid,want in expected.get('reconcile',{}).get('metrics',{}).items():
                        self.assertEqual(svc.query({'metric':mid,'expected':[[want]]})['status'],'pass')


if __name__ == '__main__':
    unittest.main()
