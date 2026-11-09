"""Submit explicit synthetic fixture proposals; never confirm or operate the UI.

Only for the examples/semantic-workbench acceptance case, not a text extractor.
Read material through the same host task API, bind actual fragment identities,
and leave every review decision to the workbench operator.
"""
import argparse
import copy
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workbench.knowledge import KnowledgeService
from workbench.store import Store


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project', required=True)
    ap.add_argument('--stage', choices=['first', 'conflict', 'second'], required=True)
    args = ap.parse_args()
    store = Store(args.project)
    service = KnowledgeService(store)
    state = service.state()
    filename = 'conflict-b.txt' if args.stage == 'conflict' else 'transport-v1.txt'
    source = next(s for s in state['sources'] if s['name'] == filename)
    rev = source['revisions'][-1]
    batch = next(b for b in reversed(state['batches']) if b['sources'][0]['source_id'] == source['id'] and b['sources'][0]['revision'] == rev['revision'])
    def call(method, **payload):
        return getattr(service, method)({'revision': store.read()['revision'], 'operation_id': uuid.uuid4().hex, **payload})
    task = call('task', batch_id=batch['id'], action='prepare')['result']
    def evidence(phrase):
        fragment = next(f for f in task['materials'][0]['parsed']['fragments'] if phrase in f['text'])
        return [{'source_id': source['id'], 'revision': rev['revision'], 'extraction_id': rev['current_extraction'],
                 'fragment_id': fragment['id'], 'quote': fragment['text']}]
    def asset(key, kind, name, definition, phrase, **values):
        return {'id': key, 'kind': kind, 'name': name, 'definition': definition, 'domain': '交通',
                'scope': '本次合成演示；同一统计日', 'aliases': [], 'refs': [], 'properties': {}, 'evidence': evidence(phrase), **values}
    groups = []
    def group(summary, assets):
        groups.append({'summary': summary, 'candidates': [{'op': 'upsert', 'asset': a} for a in assets]})
    if args.stage == 'first':
        group('核对企业、车辆及职责；物理外键不替代业务关系', [
            asset('company', 'entity', '企业', '承担本企业车辆维护职责的企业', '企业负责'),
            asset('vehicle', 'entity', '营运车辆', '获准从事运输经营的车辆', '营运车辆是', aliases=['营运车']),
            asset('registered', 'term', '登记车辆', '登记在册的车辆；登记不等于获准营运', '登记车辆是'),
            asset('regulator', 'entity', '监管机构', '监管企业运输经营活动的机构，不是企业或车辆所有者', '监管机构监管'),
            asset('supervision', 'relation', '监管职责', '监管机构监管企业运输经营活动，不表达所有权', '监管机构监管',
                  **{'from': 'regulator', 'to': 'company', 'predicate': '监管', 'relation_type': 'business'}),
            asset('maintenance', 'rule', '车辆维护职责', '企业负责本企业车辆维护', '企业负责', refs=['company', 'vehicle'],
                  properties={'condition': '本企业车辆', 'requirement': '企业负责车辆维护', 'exceptions': '材料未说明'})])
        group('核对异常车辆去重口径与在营定义', [
            asset('abnormal_count', 'metric', '异常车辆数', '按企业和统计日计有效异常车辆的不同车辆 ID，同车多条异常只计一辆', '异常车辆数按', refs=['company', 'vehicle'],
                  properties={'unit': '辆', 'grain': '企业、统计日', 'inclusions': '当日存在有效异常标记的车辆',
                              'exclusions': '正常和无效异常记录；同车重复记录不重复计数', 'time_scope': '所选统计日'}),
            asset('operating_company', 'term', '在营企业', '经营状态等于在营，不包括注销企业', '来源 A：')])
        group('核对同名收入在销售域和财务域的不同含义', [
            asset('sales_income', 'term', '收入', '统计期内已签约订单的含税合同金额', '销售域的', domain='销售'),
            asset('finance_income', 'term', '收入', '统计期内按履约确认的不含税金额', '财务域的', domain='财务')])
    elif args.stage == 'conflict':
        current = copy.deepcopy(next(a for a in state['assets'] if a['id'] == 'operating_company'))
        current.update(definition='经营状态为在营和注销的企业', evidence=evidence('来源 B：'))
        group('来源 B 与已确认来源 A 相矛盾：核对原文后裁定，不自动覆盖', [current])
    else:
        current = copy.deepcopy(next(a for a in state['assets'] if a['id'] == 'vehicle'))
        current.update(aliases=list(dict.fromkeys(current['aliases'] + ['运营车辆'])), evidence=evidence('营运车辆是'))
        group('第二批仅补充运营车辆别名，保留原身份与人工定义', [current])
        current = copy.deepcopy(next(a for a in state['assets'] if a['id'] == 'maintenance'))
        current.update(definition='企业负责本企业车辆维护并保存维护记录', evidence=evidence('企业负责'))
        current['properties']['requirement'] = '企业负责车辆维护并保存维护记录'
        group('职责条款增加保存维护记录；请核对修订后明确采纳或暂缓', [current])
    result = call('propose', batch_id=batch['id'], groups=groups, complete=True)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
