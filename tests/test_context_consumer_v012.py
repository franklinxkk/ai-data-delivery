import base64
import copy
import json
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/'scripts'))
from select_context import select_context, verify_context
from derive_ontology import derive
from workbench.service import Service, consumer_projection


def model():
    return {'datasets':[{'name':'items','source':'items','primary_key':['id'],
            'fields':[{'name':x} for x in ['id','amount','state','unused']]}],
            'metrics':[{'id':'total','dataset':'items','type':'sum','expr':'SUM(amount)',
                        'filters':[{'field':'state','values':['ok']}]}]}


class Context(unittest.TestCase):
    def test_impact_ignores_unrelated_composite_edge_without_crashing(self):
        m=model(); m['relationships']=[{'from':'a','to':'b','join_key':['x','y']}]
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'model.json';source.write_text(json.dumps(m),encoding='utf-8')
            r=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/impact_analysis.py'),'--model',str(source),'--target','total'],capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(r.returncode,0,r.stderr)

    def test_required_filter_not_output_and_inference_not_promoted(self):
        m,_=derive(model()); result=select_context(m,'total',['amount'])
        self.assertEqual({f['name'] for f in result['context']['dataset']['fields']},{'id','amount','state'})
        self.assertEqual(result['context']['entity_excerpt']['evidence']['source'],'model_inferred')
        self.assertEqual(verify_context(m,result)['status'],'matched')
        result['context']['metric']['expr']='SUM(DISTINCT amount)'
        self.assertEqual(verify_context(m,result)['error']['code'],'CONTEXT_INVALID')

    def test_stale_scope_and_removed_field_rejected(self):
        m=model(); old=select_context(m,'total')
        m['metrics'][0]['filters'][0]['values']=['bad']
        self.assertEqual(verify_context(m,old)['error']['code'],'CONTEXT_STALE')
        m['datasets'][0]['fields']=[{'name':'id'}]
        with self.assertRaises(ValueError):select_context(m,'total')

    def test_same_name_not_positional_rebinding_and_invalid_columns(self):
        m=model(); m['datasets'][0]['fields'][1]['name']='revenue'
        with self.assertRaises(ValueError):select_context(m,'total')
        for columns in ('amount',['missing'],['amount','amount']):
            with self.assertRaises(ValueError):select_context(model(),'total',columns)


class Consumer(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.service=Service(Path(self.temp.name)/'project')
        self.service.import_file({'revision':0,'kind':'model','filename':'model.json',
                                 'content':base64.b64encode(json.dumps(model()).encode()).decode()})

    def test_failure_and_unknown_status_never_pass_even_with_matching_value(self):
        payloads=[{'status':s,'value':130} for s in ['rejected','error','pending','cancelled','timeout','unknown','not_ready']]
        payloads += [{'success':False,'value':130},{'rejected':True,'value':130},{'error':'failure','value':130}]
        for payload in payloads:
            with self.subTest(payload=payload),patch('workbench.service.local_json',side_effect=[model(),payload]):
                result=self.service.consumer({'question':'总额','expected':[[130]]})
                self.assertEqual(result['status'],'consumer_not_completed')

    def test_null_is_result_not_missing(self):
        with patch('workbench.service.local_json',side_effect=[model(),{'value':None,'status':'completed'}]):
            self.assertEqual(self.service.consumer({'question':'无记录合计','expected':[[None]]})['status'],'pass')

    def test_keys_normalized_without_losing_conflicts(self):
        a=model(); a['relationships']=[{'from':'items','to':'other','from_columns':['id'],'to_columns':['other_id']}]
        b=copy.deepcopy(a); b['relationships']=[{'from':'items','to':'other','joinKeyFrom':'id','joinKeyTo':'other_id'}]
        b['datasets'][0]['primary_key']='id'
        self.assertEqual(consumer_projection(a),consumer_projection(b))
        b['relationships'][0]['joinKeyTo']='wrong'
        self.assertNotEqual(consumer_projection(a),consumer_projection(b))
        b['relationships'][0]['from_columns']=[]
        with self.assertRaises(ValueError):consumer_projection(b)

    def test_non_traversable_semantic_edge_need_not_invent_join_keys(self):
        m=model(); m['relationships']=[{'from':'items','to':'other','traversable':False,'cardinality':'N:M','note':'仅语义关联'}]
        self.assertEqual(consumer_projection(m)['relationships'][0]['traversable'],False)
        m['relationships'][0]['from_columns']=[]
        with self.assertRaises(ValueError):consumer_projection(m)


if __name__=='__main__':unittest.main()
