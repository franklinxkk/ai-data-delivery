"""An authored bilingual exercise, not a general text extractor or auto-reviewer."""
import base64
import uuid
from pathlib import Path

EXAMPLES = Path(__file__).resolve().parents[1] / 'examples' / 'quickstart'


def initialize(service, language):
    zh = language == 'zh'
    domain = '实验室设备借用（合成）' if zh else 'Equipment loans (synthetic)'
    scope = '仅限虚构实验室 L；不含跨实验室调拨及自动采购' if zh else 'Fictional Lab L only; no cross-lab transfers or automatic purchases'
    records = []
    for filename in ('equipment.sql', f'equipment.{language}.txt'):
        result = service.knowledge.import_material({'revision': service.store.read()['revision'],
            'operation_id': uuid.uuid4().hex, 'filename': filename,
            'content_base64': base64.b64encode((EXAMPLES / filename).read_bytes()).decode(),
            'domain': domain, 'scope': scope, 'language': language})['result']
        source = next(s for s in service.knowledge.state()['sources'] if s['id'] == result['source_id'])
        records.append({'source_id': source['id'], 'sha256': source['revisions'][-1]['sha256'], 'batch_id': result['batch_id']})
    def label(doc):
        doc['name'] = '设备借用 · 合成练习' if zh else 'Equipment loans · synthetic exercise'
        doc['semantic_example'] = {'kind': 'equipment', 'language': language, 'sources': records}
    service.store.change(service.store.read()['revision'], 'local', 'Initialize authored semantic exercise / 初始化语义练习', label)


def propose(service, req):
    state = service.state()
    example = state['document'].get('semantic_example', {})
    if example.get('kind') != 'equipment':
        raise ValueError('This command is only for --example equipment projects / 仅用于设备借用练习项目')
    zh = example['language'] == 'zh'
    sources = []
    for record in example['sources']:
        source = next((s for s in state['sources'] if s['id'] == record['source_id']), None)
        if not source or source['revisions'][-1]['sha256'] != record['sha256']:
            raise ValueError('Example material changed. Ask your host Agent to propose from the new source / 练习材料已变化，请宿主按新原文提出候选')
        sources.append(source)
    dataset = next((a for a in state['assets'] if a['kind'] == 'dataset' and a['name'] == 'equipment' and
                    a['status'] == 'confirmed' and any(e.get('source_id') == sources[0]['id'] for e in a['evidence'])), None)
    if not dataset:
        raise ValueError('First review and accept the DDL structure group / 请先核对并接纳 DDL 结构候选组')
    source = sources[1]; revision = source['revisions'][-1]
    fragments = revision['parsed']['fragments']
    paragraphs = [f for f in fragments if f['text'].strip()]
    if len(paragraphs) != 6:
        raise ValueError('Example text structure changed / 练习原文结构已变化')
    def ev(index):
        f = paragraphs[index]
        return {'source_id': source['id'], 'revision': revision['revision'],
                'extraction_id': revision['current_extraction'], 'fragment_id': f['id'], 'quote': f['text']}
    def item(key, kind, en, cn, paragraph, **extra):
        return {'id': 'demo.' + key, 'kind': kind, 'name': cn if zh else en,
                'aliases': [en if zh else cn], 'definition': paragraphs[paragraph]['text'],
                'domain': source['domain'], 'scope': paragraphs[0]['text'],
                'refs': [] if key == 'scope' else ['demo.scope'], 'properties': {},
                'evidence': [ev(i) for i in sorted({0, paragraph})], **extra}
    assets = [
        item('scope', 'rule', 'Exercise scope', '练习适用范围', 0, properties={
            'condition': '本练习' if zh else 'This exercise', 'requirement': paragraphs[0]['text']}),
        item('lab', 'entity', 'Lab', '实验室', 1),
        item('equipment', 'entity', 'Equipment', '设备', 1),
        item('belongs', 'relation', 'Equipment belongs to lab', '设备归属实验室', 1,
             **{'from': 'demo.equipment', 'to': 'demo.lab', 'predicate': '归属于' if zh else 'belongs to',
                'relation_type': 'business', 'properties': {'cardinality': 'N:1'}}),
        item('mapping', 'mapping', 'Equipment registration', '设备登记映射', 2,
             **{'from': 'demo.equipment', 'to': dataset['id'], 'predicate': '登记于' if zh else 'recorded in',
                'relation_type': 'maps_to', 'properties': {'transformation': 'id → equipment ID; lab_id → lab ID; state / disabled → eligibility'}}),
        item('eligible', 'rule', 'Borrowing eligibility', '设备可借规则', 3,
             refs=['demo.scope', 'demo.equipment'], properties={
                 'condition': "state='in_store' AND disabled=0", 'requirement': paragraphs[3]['text']}),
        item('available', 'metric', 'Available equipment count', '可借设备数', 4,
             refs=['demo.scope', 'demo.lab', 'demo.equipment', 'demo.eligible', 'demo.mapping'],
             evidence=[ev(0), ev(4), ev(5)], properties={
                 'unit': '台' if zh else 'items', 'grain': '实验室' if zh else 'Lab',
                 'inclusions': "lab_id='L' AND state='in_store' AND disabled=0",
                 'exclusions': '其他实验室、非在库、已停用；同编号不重复计数' if zh else 'Other labs, not in storage, disabled; do not double-count an ID',
                 'time_scope': '所询时点' if zh else 'Requested point in time',
                 'expression': 'COUNT(DISTINCT equipment.id)', 'knowledge_gaps': [paragraphs[5]['text']]})]
    return service.propose({**req, 'batch_id': example['sources'][1]['batch_id'],
        'groups': [{'summary': '核对练习的业务定义、范围和映射（预先编写的候选）' if zh else
                    'Review business definitions, scopes and mapping (authored example proposals)',
                    'candidates': [{'op': 'upsert', 'asset': a} for a in assets]}]})
