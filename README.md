# ai-data-delivery · v0.0.7

[![version](https://img.shields.io/badge/version-0.0.7-orange)](https://github.com/franklinxkk/ai-data-delivery/releases)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![tests](https://img.shields.io/badge/tests-114%20passed-brightgreen)](#三分钟跑起来)
[![host](https://img.shields.io/badge/host-Kimi%20%C2%B7%20Claude%20Code%20%C2%B7%20Cursor%20%C2%B7%20%E4%BB%BB%E4%BD%95%20SKILL.md%20%E8%BF%90%E8%A1%8C%E6%97%B6-blueviolet)](#与任何-agent-共存)

> 把零散的 DDL 和业务描述，变成有依据、可追溯、按阶段验证的语义资产——让 AI 问数答得对、错得明白。
>
> *Turn partial DDLs and business descriptions into an evidence-graded semantic contract for AI-powered data Q&A. Declaration, not inference. Evidence, not claims.*

## 如果你遇到过这些

| 症状 | 根因 |
| --- | --- |
| 问数 Demo 很惊艳，上线后答案"差不多但不对"，出了事没人敢认账 | 口径没有机器可校验的载体 |
| 同一个指标，BI、报表、AI 各给各的数 | 指标定义散落各处，无人对账 |
| 业务规则堆成越来越长的 Prompt，三个月后没人敢动 | 语义没有版本管理与 drift 检测 |
| 花力气建的"本体"，最后发现只是画了张数据库关系图 | 只有物理层，没有业务声明层 |

这不是模型能力问题，是**语义没有被当成工程资产**。ai-data-delivery 把语义交付拆成一条可落地的流水线：先声明业务世界，再映射物理数据，然后用与当前阶段相匹配的证据去验证。方法论依据：Stanford Ontology 101 七步法（Noy & McGuinness）+ GB/T 48000.3—2026 概念层对齐（适用范围见 [标准边界](references/standards.md)）。

## 它做什么

1. **部分输入就能开始**——只有几张表的 DDL 或数据字典也行；v0.0.7 起还可以从**冷启动模板包**开始（交通安全 16 实体 18 关系真实回迁包 + 通用包 + 5 个领域包，`--pack` 合并，已有对象不覆盖）。引导式补齐会话按角色分工提问（先业务后物理），每个问题带 **AI 建议+依据+备选**，可回"按 AI 建议"；每个答案带 actor/依据/修订记录，补丁应用前必须审阅
2. **本体不是 ER 图**——`ontology` 段声明业务对象、属性、语义谓词与落地方式；业务对象可以还没有表，无键关系（管辖/参加/弱匹配）不必假装是外键。数据集只是本体在物理世界的**投影**，lint 自动做两层对账，投影损失必须显式说明
3. **可维护性是设计出来的**——本体实体带稳定 `uid`（重命名后历史可追）、证据来源四级（用户提供/数据观测/模型推断/责任人确认）、主题域；`--drift` 与基线对比输出新增/删除/变更/**破坏**四级分类（破坏即门禁失败），`--history` 记录每次 release 的质量趋势
4. **每个结论带证据等级**——`mock / offline / live` 三级来源标记；门禁分 `static / validated / production` 三档；缺证据、过期证据、无效豁免、拒答失败一律不过
5. **诚实到近乎固执**——没有通用跨表 SQL 编译器、不做 OWL 推理、不采实时血缘。不能证明的，不写进广告，写进"未验证"清单

## 与同类路线对比

| | ai-data-delivery | dbt/Cube 语义层 | 平台型图谱（Palantir/Stardog） | 方法论 skill |
| --- | --- | --- | --- | --- |
| 形态 | SKILL.md + 脚本，零部署 | 数据栈组件 | 重型平台部署 | SKILL.md |
| 本体声明层（业务对象先于表） | ✅ | ❌（只有指标/维度） | ✅ | ✅ |
| 本体↔物理投影机器对账 | ✅ | 部分 | ✅ | ❌ |
| 数据约束实证（真实库跑） | ✅ | 部分（dbt test） | 部分 | ❌ |
| 问数 badcase 诊断+评测门禁 | ✅ | ❌ | ❌ | ❌ |
| drift 分级 + 质量趋势 | ✅ | 部分 | 部分 | ❌ |
| 冷启动模板包 | ✅ | ❌ | ✅（utopia 等） | 部分 |
| 上手成本 | 一条命令 | 需整套数据栈 | 需平台采购部署 | 一条命令 |

## 三分钟跑起来

需要 Python 3.10+，第三方依赖只有 PyYAML。

```bash
python -m pip install -r requirements.txt
python examples/onboarding/run_demo.py --out tmp/demo   # 从缺粒度/口径的模型到交换包全链路
python mocks/run_mock.py --all                          # 金融/政务/医疗/制造/零售 5 领域
python -m unittest discover -s tests -v                 # 114 项边界测试
```

打开 `tmp/demo/model.html`：双层语义图（上本体层/下投影层）——搜索定位、边类型过滤、主题域视图、证据来源着色、点击聚焦、导出 SVG；另有补齐进度与证据面板。离线单文件、零外部依赖。示例与 Mock 的应答由模拟器生成，**不验证真实 AI 理解或拒答能力**。

## 真实项目验证过

交通安全监管领域完整回迁（v0.0.6 起，v0.0.7 补齐 uid/主题域/证据分级）：16 个业务对象、18 条语义关系（16 等值键 + 2 弱关系）、94 个指标、15 张宽表——lint 0 ERROR；16 条关联的键唯一性在真实库全过；17 条数据约束（主键唯一/枚举字典/引用完整）全过。迁移还顺手抓出并修复了原合同两处异名键缺陷。测试范围与未验证项见 [验证记录](references/v0.0.7-validation.md)。

## 谁在什么阶段用它

| 阶段 | 产品/业务负责人 | FDE | 信息中心 | 标准结果 |
| --- | --- | --- | --- | --- |
| S0 盘点 | 定义具体问题与价值 | 解析已有材料 | 提供可用结构与访问范围 | scope、源表/字段台账 |
| S1 补齐 | 确认口径与例外；PM 需相应授权 | 提出有证据的候选并记录答案 | 确认来源、身份、历史与时效能力 | gap、decision、审阅补丁 |
| S2 建模 | 审阅业务定义 | 声明本体、映射实体/字段/关联与指标 | 核对实际数据契约 | semantic.yaml（本体层+合同投影） |
| S3 验证 | 确认独立期望 | 检查关联、结果对拍与回归 | 检查全量快照和数据质量 | 绑定版本/快照的验证报告 |
| S4 交付 | 接受适用范围与剩余项 | 对接具体消费者、交付交换包 | 确认运行与权限条件 | manifest、字典、用例、证据、视图 |
| S5 演进 | 调整优先级与口径 | 分析变更、修复和回归 | 巡检结构/数据/运行变化 | 差异、影响候选、再验证记录 |

可以分段交付。没有数据库时 S1/S2 仍可推进；涉及真实数据的结论保留未验证。只有现状表时，历史月末问题应产出补采需求，不把当前状态当历史事实。

## 从你的材料开始

```bash
# 已有部分 semantic.yaml：先定义当前用例 scope（格式见 examples/onboarding/scope.yaml）
python scripts/guide_model.py init --model partial.yaml --scope scope.yaml --session session.json
# 也可以从模板包冷启动（starter_packs/ 清单见该目录 README）
python scripts/guide_model.py init --model partial.yaml --scope scope.yaml --session session.json --pack starter_packs/general.yaml
python scripts/guide_model.py status --session session.json   # 待确认清零报告 + 每问 AI 建议
# 根据真实回答创建 answers.json，审阅生成的补丁后再应用
python scripts/guide_model.py propose --session session.json --answers answers.json --patch review.json
python scripts/guide_model.py apply --session session.json --patch review.json
python scripts/guide_model.py export --session session.json --out draft

# 只有 DDL 时：生成台账及部分模型，不猜业务粒度/口径
python scripts/ingest_ddl.py --ddl schema.sql --out inventory --model-out partial.yaml
```

详细输入、回答、冲突修订和重新验证流程见 [补齐闭环](references/onboarding.md)。

## 证据与门禁

```bash
python scripts/check_model.py -f semantic.yaml          # 结构 lint + 本体/投影对账
python scripts/check_model.py -f semantic.yaml --drift 上一版.yaml   # v0.0.7：drift 四级分类
python scripts/check_model.py -f semantic.yaml --history quality_history.jsonl   # v0.0.7：质量趋势
python scripts/check_join_graph.py --model semantic.yaml --db snapshot.db --out joins.json
python scripts/check_constraints.py --model semantic.yaml --db snapshot.db --out constraints.json
python scripts/run_eval.py --gold cases.json --actual actual.json --model semantic.yaml --db snapshot.db --report eval.json
python scripts/release_gate.py --profile validated --model semantic.yaml --cases cases.json --db snapshot.db --eval-report eval.json --out gate.json
python scripts/visualize_model.py --model semantic.yaml --report joins.json --report constraints.json --report gate.json --history quality_history.jsonl --out model.html
```

`static` 只证明指定结构检查通过；默认 `validated` 要求当前模型、用例、数据快照和完整评测证据；`production` 另要求真实端点证据和稳定性抽查。技术门禁不代替业务签署、部署、身份认证或现场运行验收。

## 与任何 Agent 共存

标准 `SKILL.md` 约定 + 纯 Python 脚本，**不绑定任何宿主**：Kimi、Claude Code、Cursor 或任何支持 SKILL.md 约定的 Agent 运行时均可加载；所有脚本也可脱离 Agent 在命令行/CI 里直接运行。欢迎提交到各 skill 市场与社区镜像。不同宿主的发现、权限及脚本运行行为需要现场确认。

## 文档

- [SKILL.md](SKILL.md)：Agent 入口与任务路由
- [合同与验证](references/contract.md)：本体声明层、投影、维护（drift/质量历史）、约束、指标与评测边界
- [补齐闭环](references/onboarding.md)：部分输入/模板包冷启动 → 可审阅合同
- [交付及迁移](references/delivery-playbook.md)：阶段门禁、旧版报告/豁免迁移
- [诊断手册](references/diagnosis-playbook.md)：bad case 取证瀑布与工作流
- [标准边界](references/standards.md)：GB/T 48000.3—2026、Apache Ossie 与其他规范的适用范围
- [冷启动模板包](starter_packs/README.md)：通用/交通/金融/政务/医疗/制造/零售
- [全部工具](references/tools.md) · [本版验证记录](references/v0.0.7-validation.md)

## 它不做什么

没有通用跨表 SQL 编译器、OWL 推理器、Ossie 适配器或实时血缘采集器。本体段是声明式事实清单，不做 is-a 传递/子类继承/逆关系等任何跨声明推导。关系键借鉴了显式左右列的做法，但此格式仍是本项目合同；YAML lint 不等于国标符合性。大型库/其他数据库需要接入真实消费者再评估。

## 安装和构建

把仓库目录放入宿主的 skills 目录；或从 [Releases](https://github.com/franklinxkk/ai-data-delivery/releases) 下载 `.skill` 包导入。

```bash
python -m unittest discover -s tests -v
python maintainer/build_skill.py --out dist   # 确定性构建：只打 Git 已跟踪文件，附 SHA256 清单
```

[MIT License](LICENSE) · 欢迎 Issue / PR / 领域症状包投稿
