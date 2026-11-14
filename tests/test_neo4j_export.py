import csv
import io
import json
import unittest
import zipfile

from tests.test_semantic_package import asset
from workbench.semantic_package import SemanticPackage, build_package
from workbench.neo4j_export import export_neo4j,CYPHER


def example(project='one',draft=False):
    hostile='名称 "quoted"\r\nC:\\path\\"; MATCH (n) DETACH DELETE n; //'
    items=[asset('a','entity',hostile),asset('b','entity','Other'),asset('edge','relation',hostile,
           **{'from':'a','to':'b','predicate':hostile,'relation_type':'business'})]
    items[0]['properties']['typed']={'zero':0,'false':False,'null':None,'list':['0',0]}
    if draft:items[0]['status']='draft'
    raw,_=build_package(items,[],project_id=project,revision=1,asset_ids=['edge'],draft=draft)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        return raw,SemanticPackage({n:z.read(n) for n in z.namelist()})


class Neo4jExportTests(unittest.TestCase):
    def test_json_and_direction_survive_csv_without_code_interpolation(self):
        _,package=example();raw,manifest=export_neo4j(package)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            rows=list(csv.DictReader(io.StringIO(z.read('assets.csv').decode())))
            self.assertEqual({r['id']:json.loads(r['asset_json']) for r in rows},package.index)
            relations=list(csv.DictReader(io.StringIO(z.read('relationships.csv').decode())))
            self.assertEqual([(r['from_id'],r['to_id']) for r in relations],[('a','b')])
            self.assertEqual(z.read('import.cypher').decode(),CYPHER)
            self.assertNotIn('DETACH DELETE',CYPHER)
            snapshot=next(csv.DictReader(io.StringIO(z.read('snapshots.csv').decode())))
            self.assertEqual(json.loads(snapshot['model_json']),package.model)
        self.assertEqual(raw,export_neo4j(package)[0])

    def test_draft_stays_draft_and_separate_projects_never_merge(self):
        _,first=example('one',True);_,second=example('two',True)
        left,right=export_neo4j(first)[1],export_neo4j(second)[1]
        self.assertTrue(left['draft']);self.assertFalse(left['complete'])
        self.assertNotEqual(left['namespace'],right['namespace'])


if __name__=='__main__':unittest.main()
