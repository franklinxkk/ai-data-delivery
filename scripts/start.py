#!/usr/bin/env python3
"""Open a local workbench with optional synthetic demo or existing files."""
import argparse
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'scripts'))


def prepare(project, demo=None, model=None, ddl=None, sample=None, provenance='unknown', example=None, language='en'):
    from workbench.service import Service
    from workbench.demo import sample as demo_sample, write_snapshot
    from derive_ontology import derive
    project=Path(project).resolve()
    initializing=bool(demo or model or ddl or sample or example)
    if (project/'project.sqlite').exists():
        if initializing:
            raise ValueError('Project exists; it will not be overwritten. Remove initialization flags to reopen or use a new --project. / 项目已存在；不会覆盖。去掉导入/演示参数继续使用，或指定新的 --project 目录。')
        return Service(project),{'status':'reopened','project':str(project)}
    if demo and any((model,ddl,sample)):
        raise ValueError('Keep demo and real inputs in separate project directories. / 演示与真实资料不能混合初始化；请分别使用项目目录。')
    if example and any((demo, model, ddl, sample)):
        raise ValueError('Use a separate project for the semantic example / 语义练习请使用独立项目')
    if model and ddl:
        raise ValueError('Choose either model or DDL for initialization / 模型与DDL二选一导入')
    inputs={kind:Path(value).resolve() for kind,value in [('model',model),('ddl',ddl),('sample',sample)] if value}
    for kind,path in inputs.items():
        if not path.is_file():raise ValueError(f'{kind} 文件不存在：{path}')
    project.parent.mkdir(parents=True,exist_ok=True)
    # Prepare separately, then install exactly one closed SQLite file without overwrite.
    with tempfile.TemporaryDirectory(prefix='.delivery-start-',dir=project.parent) as temporary:
        temp=Path(temporary);service=Service(temp/'project')
        def import_bytes(kind,name,data,source='unknown'):
            service.import_file({'revision':service.store.read()['revision'],'kind':kind,'filename':name,
                                 'content':base64.b64encode(data).decode(),'provenance':source})
        if example:
            from workbench.semantic_demo import initialize
            initialize(service, language)
        elif demo:
            m,rows,columns,expected=demo_sample(demo);m,_=derive(m)
            snapshot=temp/'synthetic.sqlite';write_snapshot(snapshot,m,rows)
            import_bytes('model','synthetic-'+demo+'.json',json.dumps(m,ensure_ascii=False).encode())
            import_bytes('sample','synthetic-'+demo+'.sqlite',snapshot.read_bytes(),'demo')
            def label(doc):
                doc['name']='合成演示 · '+('交通' if demo=='traffic' else '零售')
                doc['tutorial']={'kind':demo,'synthetic':True,'metric':next(iter(expected)),
                                 'columns':columns,'expected':expected}
            service.store.change(service.store.read()['revision'],'local','标记合成演示与练习目标',label)
        else:
            if language == 'en':
                service.store.change(service.store.read()['revision'], 'local', 'Create project', lambda doc: doc.update(name='New semantic project'))
            for kind,path in inputs.items():
                if kind == 'sample':
                    import_bytes(kind,path.name,path.read_bytes(),provenance)
                    continue
                result = service.knowledge.import_material({
                    'revision':service.store.read()['revision'], 'operation_id':uuid.uuid4().hex,
                    'filename':path.name, 'content_base64':base64.b64encode(path.read_bytes()).decode(), 'language':language})['result']
                parsed = result['parsed']
                if parsed['status'] in {'failed', 'needs_conversion'}:
                    raise ValueError(f"{path.name} 未能提取可用内容：{parsed.get('warnings', [])}")
        project.mkdir(parents=True,exist_ok=True)
        os.link(service.store.path,project/'project.sqlite')  # Atomic create, fails if another initializer won.
    return Service(project),{'status':'prepared','project':str(project),'demo':demo,'example':example,'language':language,
                             'boundary':('Authored synthetic materials loaded; review DDL, then prepare business proposals. / 已载入合成材料；请先核对 DDL，再准备业务候选。' if example else '本机单人项目；演示不是生产验证。') if demo or example else ('已登记材料与可提取的候选；请在工作台核对后写入图谱。' if model or ddl else ('已载入独立数值样本；尚未建立语义图谱。' if sample else '已创建空项目；可在工作台导入资料。'))}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',required=True,help='Project directory; reuse this path to reopen / 项目目录；重开使用同一路径')
    source=p.add_mutually_exclusive_group()
    source.add_argument('--example', choices=['equipment'], help='Bilingual semantic modeling exercise / 双语设备借用建模练习')
    source.add_argument('--demo',nargs='?',const='traffic',choices=['traffic','retail'],help='Optional numeric demo (default: traffic) / 可选数值练习，默认交通')
    source.add_argument('--model',help='Import YAML/JSON as material and candidates, not confirmed knowledge / 登记模型材料及候选，不覆盖图谱')
    source.add_argument('--ddl',help='Parse CREATE TABLE into physical candidates without executing SQL / 解析 DDL 为结构候选，不执行 SQL')
    p.add_argument('--sample',help='Optional independent SQLite snapshot / 可选独立 SQLite 快照')
    p.add_argument('--provenance',choices=['unknown','demo','deidentified','production'],default='unknown')
    p.add_argument('--prepare-only',action='store_true',help='Prepare project without starting server / 仅准备项目，不启动服务')
    p.add_argument('--port',type=int,default=0,help='Local port (0 selects an available port) / 本机端口，0 自动选择')
    p.add_argument('--language', choices=['en', 'zh'], default='en', help='Initial interface and example language / 界面及练习语言')
    a=p.parse_args(argv)
    if not 0<=a.port<=65535:p.error('port 必须在0–65535之间')
    try:
        _,result=prepare(a.project,a.demo,a.model,a.ddl,a.sample,a.provenance,a.example,a.language)
        print(json.dumps(result,ensure_ascii=False),flush=True)
        if a.prepare_only:
            import shlex
            path=Path(a.project).resolve().as_posix()
            quoted=("'"+path.replace("'","''")+"'") if os.name=='nt' else shlex.quote(path)
            print('Reopen / 继续打开：python scripts/start.py --project '+quoted)
            return 0
        from workbench.serve import main as serve
        return serve(['--project',str(Path(a.project).resolve()),'--port',str(a.port),'--language',a.language])
    except ImportError as exc:
        print('Missing dependencies. Run python -m pip install -r requirements.txt in the skill directory, then retry. / 缺少运行依赖，请安装 requirements.txt 后重试。',file=sys.stderr)
        return 2
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print('Unable to open project / 无法打开项目：'+str(exc),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
