---
name: ai-data-delivery
description: AI+数据落地工具包，服务 FDE（驻场/交付工程师）、产品经理与信息中心人员，覆盖企业级 AI 问数/数据分析系统从立项、试点到生产的全周期。包含三个模块：语义资产建设（源表盘点→同构检测→指标收割→宽表草案→meta 草稿→指标绑定→覆盖检查→模型幂等维护，对齐真实 semantic.yaml 合同 Schema，写口径前物理库验算）、bad case 诊断修复闭环（取证→三层归因→补丁→双路对账→活引擎回归→回流 gold 集）、评估与验收纪律（gold 集建设/回归比对/模型 lint/评测集体检/发版门禁/口径字典/交换导出/结构漂移巡检/影响面分析）。当用户遇到以下场景时使用：智能问数答错、口径不一致、实体不识别、该拒未拒等 bad case 排查；本体模型 YAML（semantic.yaml 类：datasets/concepts/relationships/metrics）的修改与合规检查；评测集（gold 集）的建设与冲突排查；AI+数据项目的落地规划、试点验收、上线评审与生产运营；为 FDE/PM/信息中心准备交付物或操作规程。不用于通用模型微调、与数据无关的 AI 应用开发。
---

# AI Data Delivery v0.0.4

## Overview

企业 AI+数据落地的恒定量：**落地价值 = 语义对齐 × 可靠性闭环 × 交付界面**。模型能力会持续换代贬值；语义资产、回归集、操作规程不随之过时——本工具包锚定这三个常量。

**v0.0.2 的锚点：一切脚本围绕真实合同 Schema（semantic.yaml：`datasets[] / concepts[] / relationships[] / metrics[]`）。禁止发明第二套玩具结构；引擎可换，合同不动。**

三个模块对应三类受众的操作界面：

| 模块 | FDE（驻场/交付） | 产品经理 | 信息中心 |
| --- | --- | --- | --- |
| 一、语义资产 | 盘点与建模的执行者 | 口径定义的责任人（文号挂 caliber.basis） | 数据源与映射的提供方 |
| 二、诊断闭环 | 归因与修复的主场 | 提 bad case、确认期望 | 数据层问题的兜底 |
| 三、评估验收 | 跑回归与 lint、出报告 | 定验收门槛、签字 | 上线门禁的把关方 |

## 全周期工具地图（按交付阶段找工具）

| 阶段 | 标准输入 | 工具（scripts/） | 标准输出 |
| --- | --- | --- | --- |
| 立项盘点 | 各业务系统 DDL/库连接、历史指标公式 | `ingest_ddl.py` `profile_db.py` `detect_isomorphic.py` `harvest_metrics.py` `gold_seed.py` | inventory（表/字段台账）、枚举候选、同构族清单、指标三分清单（可执行/需改写/无来源）、gold v0 骨架 |
| PoC 建模 | inventory + 指标清单 + 领域知识 | `propose_dws.py` `gen_metadata.py` `bind_metrics.py` `coverage_check.py` `gen_eval_cases.py` | 宽表合并草案、meta 草稿、指标绑定结果、三方覆盖报告、评测用例草稿 |
| 试点闭环 | 活引擎 + gold 集 + 用户反馈 | `capture_case.py` `ingest_feedback.py` `suggest_card.py` `patch_model.py` `reconcile_paths.py` `promote_gold.py` `run_eval.py` | bad case 登记卡、修订建议卡、模型补丁、对账报告、回归报告、扩大的 gold 集 |
| 生产运营 | 已发布模型 + 物理库 | `release_gate.py` `gen_dictionary.py` `export_exchange.py` `check_consistency.py` `plan_stability.py` `impact_analysis.py` `probe_model.py` `check_model.py` `gold_lint.py` | 发版日志、口径字典、交换包（sha256 清单）、漂移告警、影响面清单 |

阶段门禁、交付物清单与角色分工矩阵见 [references/delivery-playbook.md](references/delivery-playbook.md)。

## 五条铁律（全模块通用）

1. **模型层 YAML 优先，引擎层次之，数据层最后**。能用模型定义解决的，绝不动引擎代码。
2. **指标必须自含全口径**。过滤、时间、粒度写进指标定义本身（expr/分子分母 + extra_where + time_field），不依赖"引擎默认行为"。**写入口径前必须对物理库验算**（patch_model.py --db 自动执行；验算不过拒绝写入）。
3. **引擎不承载业务口径**。为单个 case 在引擎里加特判 = 反模式。
4. **先回归再交付**。任何修改后全量回归，通过率不降才允许交付。
5. **一切修改走幂等脚本留痕**。禁止手改 YAML；补丁可复跑、可审计。

铁律 1/2 已由 `scripts/check_model.py` 落成机器检查（粒度必填、ratio 禁行级平均、口径自含、敏感标记、概念可执行展开等），发布门禁为零 ERROR。

## 模块一：语义资产建设

### 立项盘点：先有台账，再谈建模

```bash
# DDL 目录 → 表/字段台账（inventory/tables.yaml + columns.yaml）
python3 scripts/ingest_ddl.py --ddl-dir ddl/ --out inventory/
# 库画像 → 枚举候选列、取值分布、空值率（敏感列自动不取样；--out 自动建目录）
python3 scripts/profile_db.py --db physical.db --out inventory/profile.yaml
# 同构表检测（smart_check_item1..30 这类序号家族）→ 合并候选族
python3 scripts/detect_isomorphic.py --tables inventory/tables.yaml \
    --columns inventory/columns.yaml --out inventory/isomorphic.yaml
# 历史指标公式三分：可执行候选 / 需改写 / 无来源 → metrics_raw.yaml + gaps.yaml
# 存量场景：无 table 字段也不怕（自动解析 FROM）；--from-meta 用宽表 meta 的 sources 派生映射；
# 模型已建成时可直接 --model semantic.yaml 收割 legacy_formula
python3 scripts/harvest_metrics.py --metrics 指标导出.json --from-meta meta/ --out inventory/
python3 scripts/harvest_metrics.py --model semantic.yaml --out inventory/
```

### PoC 建模：一族一宽表，指标全绑定

```bash
# 同构族 + 前缀聚类 → 宽表合并草案（覆盖多少指标直接写在草案上）
python3 scripts/propose_dws.py --inventory inventory/tables.yaml \
    --metrics-raw inventory/metrics_raw.yaml --out proposals_dws.yaml
# 台账 + 库画像 → 宽表 meta 草稿（0/1 标志位归 dim、时长归 measure、枚举填实测值、敏感预标记、【】占位项）
python3 scripts/gen_metadata.py --tables inventory/tables.yaml \
    --columns inventory/columns.yaml --profile inventory/profile.yaml --out meta/
# 指标 × 宽表绑定（范围写法展开、剔除表名标识符）→ 可绑定/部分绑定/缺口
python3 scripts/bind_metrics.py --metrics-raw inventory/metrics_raw.yaml \
    --meta meta/ --model semantic.yaml --out bindings.yaml
# 指标 × 模型 × gold 三方覆盖检查（0 ERROR 才允许进试点）
python3 scripts/coverage_check.py --model semantic.yaml \
    --metrics-raw inventory/metrics_raw.yaml --cases cases.json --out coverage.md
```

### 模型维护：semantic.yaml 是唯一事实源

所有修改用 `scripts/patch_model.py`（幂等：无变化不写盘）：

```bash
# 补同义词：指标按 id；数据集（表别名）用 --dataset；概念别名用 --concept
python3 scripts/patch_model.py -f semantic.yaml syn inspect_count 检查单数量 查了多少次检查
python3 scripts/patch_model.py -f semantic.yaml syn --dataset enterprise 运输户 业户
python3 scripts/patch_model.py -f semantic.yaml syn --concept 重点营运车辆 重点车

# 结构化指标（自含全口径），--db 自动对物理库验算"patched 后完整口径"（filters+extra_where 全量）；
# 有金标准值时加 --expect 对拍（如 --expect 15），对拍失败拒绝写入
python3 scripts/patch_model.py -f semantic.yaml struct hazard_major \
    --expr "COUNT(*)" --extra-where "rectify_status = '待整改'" \
    --time-field stat_date --caliber-note "待整改重大隐患" --caliber-basis "金标准 Q11" \
    --db /path/to/physical.db --expect 15
# 验算边界：只保证口径可执行且有量/对拍一致，口径语义正确性仍须 run_eval 金标准回归把关
# ratio 型必须分子分母（禁行级平均）：--numerator "SUM(a)" --denominator "SUM(b)"
# 新建指标必须显式 --create 并给 --name/--type/--dataset（默认要求已存在，防笔误造重复）

# 改键值：指标键用 --key；全局点路径用 --path
python3 scripts/patch_model.py -f semantic.yaml set hazard_major --key status --value 已发布
python3 scripts/patch_model.py -f semantic.yaml set --path engine.timezone --value Asia/Shanghai
```

PM 职责：口径争议在评审会上定，不在引擎里猜；caliber.basis 挂依据文号（无文号写"内部约定"并挂待办）。信息中心职责：确认列映射与数据源新鲜度。

## 模块二：bad case 诊断修复闭环

五段工作流：**复现 → 归因 → 最小修复 → 重建+回归 → 留痕交付**。

复现阶段先排除"环境层假故障"（改了没生效），并一键取证：

```bash
# 核对运行时模型与本地权威源是否一致（版本/数据集数/指标数/结构化数）
python3 scripts/probe_model.py --endpoint http://localhost:7100 --model semantic.yaml
# 一键取证：应答 + 检索命中 + 模型快照三件套 → badcases/<id>.yaml 登记卡
python3 scripts/capture_case.py --endpoint http://localhost:7100 \
    --question "问句" --id BC001 --note "用户原话" --out badcases/
# 聊天里的口头反馈也能入池（同问句自动累计次数，热度即优先级）
python3 scripts/ingest_feedback.py --pool badcases/ --question "问句" --note "反馈内容"
```

归因决策树（拿不准时先假设模型层，补丁无效果再下沉）：

```
bad case
├── 实体/问法不识别 → 模型层：patch_model.py syn
├── 识别但口径不对
│     ├── 口径歧义 → 模型层：patch_model.py struct（先 --db 验算再写入）
│     ├── 解析/规划错（多跳断裂、时间错、过滤丢）→ 引擎层
│     └── 都对仍错 → 数据层（查底层数据，不改模型不改引擎）
└── 拒绝判定错（该拒未拒/不该拒却拒）→ 引擎层
```

症状→层定位→修复的完整对照表（8 类症状 + 层位验证动作 + 引擎不变式）见 [references/diagnosis-playbook.md](references/diagnosis-playbook.md)，疑难 case 先查表。登记卡 triage 出归因层后，`suggest_card.py` 生成修订建议卡（证据/建议动作/影响面/回归占位）：

```bash
python3 scripts/suggest_card.py --card badcases/BC001.yaml --out suggest_BC001.md
```

修复后双路对账 + 重建 + 回归 + 回流 gold 集：

```bash
# 双路径口径对账：编译结构化指标直算物理库 vs 活引擎问数路径，不一致即双口径
python3 scripts/reconcile_paths.py --model semantic.yaml --db physical.db \
    --endpoint http://localhost:7100 [--metric hazard_count]

# 停服→新鲜度校验→构建→起服→就绪校验（产物旧于源码时拒绝 --skip-build，防旧包）
python3 scripts/rebuild.py --project-dir /path/to/fde \
    --artifact target/fde-server.jar \
    --build-cmd "mvn -q package -DskipTests" \
    --start-cmd "java -jar target/fde-server.jar" \
    --health-url http://127.0.0.1:8080/health --port 8080

# 全量回归 · 模式 A 活引擎（推荐）：逐条打 /api/ask，失败明细带 SQL 与推理链
python3 scripts/run_eval.py --endpoint http://localhost:7100 \
    --cases cases.json [--gold-results gold_results.json] [--multihop mh.json] --out report.json
# 模式 B 离线文件比对（无引擎环境）：scalar 等值 / rows 行集合 / refusal 拒绝判定
python3 scripts/run_eval.py --gold eval_gold.yaml --actual eval_actual.jsonl --report eval_report.json

# 修好的 case 填好 expect 后回流 gold 集（同 id 覆盖，不重复追加）
python3 scripts/promote_gold.py --card badcases/BC001.yaml --gold cases_merged.json --fmt merged
```

## 模块三：评估与验收纪律

- **gold 集是资产**：每个修过的 bad case 沉淀进 gold（promote_gold.py），防止修 A 坏 B。
- **已声明冲突不入门禁但要留痕**：评审已定性、决议暂保留的口径冲突用例，在 case 上加 `declared_conflict: {ref: 决策出处, note: 说明}`——run_eval 判 DECL 不计入 acc、不压 exit，release_gate G3 展示声明数；缺 ref 会大声告警（无留痕的豁免 = 后门）；实测转 pass 会提示冲突已消解、建议移除标记。
- **gold 集自身要体检**：同一 SQL 两份期望、同一问句两个答案这类评测集口径冲突，用 `gold_lint.py` 在评审前拦截（不体检的 gold 集 = 验收标准崩塌）。
- **评测覆盖可以生成**：`gen_eval_cases.py` 按九组问法模板（单表聚合/分组/筛选/时间/TopN/比率/明细/跨表/拒绝）从模型生成草稿，人只补 gold；`gold_seed.py` 把问句清单变成 v0 骨架并强制质疑拒绝类覆盖。
- **验收门槛**：上线前必须满足——全量回归通过率不降、refusal 用例全过、`check_model.py` 零 ERROR、`gold_lint.py` 零 ERROR、同一问句连跑查询计划一致。

```bash
python3 scripts/check_model.py -f semantic.yaml            # 铁律 lint：发布门禁零 ERROR
python3 scripts/gold_lint.py --cases cases_gold.json --results gold_results.json --model semantic.yaml
python3 scripts/plan_stability.py --endpoint http://localhost:7100 --cases cases.json --times 10
```

- **验收在签约/上线前做，不是出事后补**：评估脚手架、指名工作流、范围边界是立项交付物，不是事后补救项。

### 生产运营：发版有门禁，日常有巡检

```bash
# 发版门禁：G1 模型自检 + G2 gold 体检 + G3 全量回归 + G4 计划稳定，全过才写发版日志
python3 scripts/release_gate.py --model semantic.yaml --cases cases_gold.json \
    --eval-report report.json --endpoint http://localhost:7100 --log release_log.yaml
# 口径字典：模型 → 人能读的 markdown（数据集/概念/指标口径含文号/未结构化清单）
python3 scripts/gen_dictionary.py --model semantic.yaml --out dictionary.md
# 交换导出：模型+字典+gold 打一个版本化整体，manifest 带 sha256
python3 scripts/export_exchange.py --model semantic.yaml --cases cases.json --out exchange/
# 上游结构漂移巡检：meta/模型承诺 vs 物理库实际，字段消失即 ERROR
python3 scripts/check_consistency.py --meta meta/ --db physical.db
# 变更影响面：改字段/数据集/指标前先看谁受影响（概念/指标/关系/多跳/gold 用例）
python3 scripts/impact_analysis.py --model semantic.yaml --target ent_id --cases cases_gold.json
```

落地全周期（立项→PoC→试点→生产）的阶段门禁、各阶段交付物、角色分工矩阵见 [references/delivery-playbook.md](references/delivery-playbook.md)。做落地规划、试点验收、上线评审时必读。

## 反模式

- ❌ 手改 YAML（无留痕、不可复跑）
- ❌ 引擎里为单 case 加特判（口径逃逸进代码）
- ❌ 写口径前不验算（把错口径写进合同，下游全部白干）
- ❌ 只验证修好的 case 就跑（没全量回归）
- ❌ 跳过构建直接重启旧包（rebuild.py 的新鲜度校验就是为此存在）
- ❌ 数据层问题改模型（越修越乱）
- ❌ 试点没有 gold 集就上线（验收无依据，死因第一名）
- ❌ 评测集不体检（同一 SQL 两份 gold，验收结论失真）
- ❌ 不看台账直接建模（298 张源表里有 30 张同构表，漏掉就是 30 倍重复劳动）
- ❌ 指标收割后不做三方覆盖检查就进试点（无来源指标混进合同）
- ❌ 发版不过门禁（发版日志是出事后唯一的免责证据）
- ❌ 改字段前不做影响面分析（一个 join_key 字段背后可能挂着 90+ 指标）

## 版本演进

| 版本 | 主题 | 变更 |
| --- | --- | --- |
| v0.0.1 | 调优闭环泛化版 | 三模块框架、五铁律、delivery/diagnosis playbook、patch/rebuild/run_eval（文件比对）三脚本 |
| v0.0.2 | 全周期完整版 | 在真实 semantic.yaml 合同上纠偏（指标按 id 寻址、分子分母、caliber 文号、--db 物理库验算）；run_eval 恢复活引擎模式；并按"立项盘点→PoC 建模→试点闭环→生产运营"补齐全周期 27 个脚本 |
| v0.0.3 | 真实项目实测修复版 | 经真实项目（15 宽表/94 指标/74 用例，Spring Boot 引擎 + SQLite）实测反馈修复 10 项：① run_eval 拒绝类用例静默误判（识别 expect_table 拒绝标记、期望不明显式 skip 并汇总告警、支持用例行内 gold_results）；② patch_model 验算改为 patched 后完整口径（filters+extra_where 全量）+ --expect 金标准对拍 + 验算边界声明；③ gold_lint 新增结果自洽性检查（OK 但空结果、row_count 与 rows 不符、孤儿期望、负值启发式）；④ reconcile_paths 直算并入 filters、百分比量纲差异单列不压门禁；⑤ capture_case/suggest_card 检索响应 list/dict 双兼容、reasoning list 兼容、layer 缺失时证据驱动推断候选不阻断；⑥ harvest_metrics 支持 FROM 子句解析 + --mapping/--from-meta 源表映射 + --model 存量收割（94 假"无来源"→ 9 真缺口）；⑦ 文档参数漂移修正 6 处；⑧ 全部 --out 自动建目录；⑨ promote_gold 自动初始化新 gold 文件；⑩ gen_metadata/ingest_ddl 角色与时间列推断修正（0/1 标志位归 dim、时长归 measure、deadline 归 time） |
| v0.0.4 | 领域无关化 + 收口验证修复版 | v0.0.3 收口验证（75/75、门禁 4/4）后修复 2 项遗留：① promote_gold 自动初始化丢首条（假成功：提示新增但落盘为空）；② run_eval/release_gate 支持 declared_conflict 声明式冲突——评审已定性、决议暂保留的口径冲突用例失败不计入 acc、不压门禁，单独留痕，缺决策出处 ref 大声告警；实测转 pass 提示冲突已消解。新增 mocks/ 多领域快速测试包：零售/金融/医疗/制造/政务 5 个自包含场景（确定性造数 + 迷你本体 + gold 用例），`run_mock.py --all` 无需活引擎端到端自检（建库→模型 lint→评测体检→口径编译→回归），证明合同 Schema 领域无关，并作为新领域 PoC 脚手架 |

版本纪律：小步演进（0.0.1→0.0.2→0.0.3→…），每版只加一类能力，每版必须用真实项目资产回归自证后发布。

## Resources

### scripts/（按交付阶段分组）

**立项盘点**
- `ingest_ddl.py` — DDL 目录 → inventory/tables.yaml + columns.yaml 台账。
- `profile_db.py` — 物理库画像：枚举候选列、取值分布、空值率；敏感列不取样。
- `detect_isomorphic.py` — 序号归一检测同构表家族（item1..item30 式），输出合并候选族。
- `harvest_metrics.py` — 历史指标公式三分：可执行候选/需改写/无来源；无 table 字段自动解析 FROM 子句；--mapping/--from-meta 源表名映射（范围写法展开）；--model 直接收割存量模型的 legacy_formula。
- `gold_seed.py` — 问句清单 → gold v0 骨架（cases_merged 兼容），支持从指标名/同义词反挖，缺拒绝类自动告警。

**PoC 建模**
- `propose_dws.py` — 同构族 + 前缀聚类 → 宽表合并草案（一族一宽表，标注覆盖指标数）。
- `gen_metadata.py` — 台账+库画像 → 宽表 meta 草稿：角色推断（0/1 标志位归 dim、时长归 measure、严格时间后缀）、枚举填实测值、敏感预标记、【】占位。
- `bind_metrics.py` — 指标 × meta 绑定：范围写法展开、表名标识符剔除，输出可绑定/部分绑定/缺口。
- `coverage_check.py` — 指标 × 模型 × gold 三方覆盖检查，0 ERROR 才进试点。
- `gen_eval_cases.py` — 按九组问法模板从模型生成评测用例草稿（expect_tbd 待补 gold）。

**试点闭环**
- `capture_case.py` — bad case 一键取证：应答+检索命中+模型快照三件套 → 登记卡（检索响应 list/dict 双兼容）。
- `ingest_feedback.py` — 用户口头反馈入 bad case 池，同问句自动累计次数。
- `suggest_card.py` — 登记卡归因层 → 修订建议卡（证据/建议动作/影响面/回归占位）；layer 缺失时依据证据推断候选并标注"待确认"，不阻断流水线。
- `patch_model.py` — semantic.yaml 幂等补丁：`syn`（指标/数据集/概念三类同义词）/ `struct`（结构化指标，ratio 分子分母，--db 对 patched 后完整口径验算，--expect 金标准对拍）/ `set`（指标键或全局点路径）。
- `promote_gold.py` — 登记卡 → gold 集（expect 未填拒绝入库；同 id 覆盖幂等；gold 文件不存在自动初始化，首条不丢）。
- `reconcile_paths.py` — 双路径口径对账：完整口径（filters+extra_where）编译直算物理库 vs 活引擎问数路径；百分比量纲差异单列不压门禁；也支持两份 json 离线比对。
- `rebuild.py` — 停服→构建→起服→就绪校验，内置防旧包。
- `run_eval.py` — 回归比对器双模式：活引擎（打 /api/ask，留痕 SQL+推理链）/ 离线文件比对；declared_conflict 声明式冲突判 DECL 不计入 acc 并留痕；退出码 0=全过。

**生产运营**
- `release_gate.py` — 发版门禁：G1 模型自检 + G2 gold 体检 + G3 全量回归（声明冲突留痕展示）+ G4 计划稳定，写发版日志。
- `gen_dictionary.py` — 模型 → 口径字典 markdown（含 caliber 文号、未结构化 backlog）。
- `export_exchange.py` — 语义资产交换导出：模型+字典+gold+manifest（sha256 清单）。
- `check_consistency.py` — 上游结构漂移巡检：meta/模型承诺 vs 物理库实际。
- `plan_stability.py` — 同一问句连跑 N 次 SQL 指纹一致性（服务不可用报"异常"不算稳定）。
- `impact_analysis.py` — 变更影响面：字段/数据集/指标 → 概念/指标/关系/多跳/gold 用例清单。

**门禁与体检（横切）**
- `probe_model.py` — 运行时模型快照核对：/api/model 与本地权威源比对，防"改了没生效"。
- `check_model.py` — 铁律 lint：粒度/枚举/敏感标记/ratio 禁行级平均/口径自含/概念可展开/关系完整性。
- `gold_lint.py` — 评测集体检：id 重复、同问句异答案、同 SQL 异 gold、refusal 覆盖、expect_table 存在性、结果自洽性（OK 但空结果/row_count 与 rows 不符/孤儿期望/负值启发式）。

### references/

- `diagnosis-playbook.md` — 症状→层定位→修复对照表（8 类）、层位验证动作、环境层假故障、引擎不变式、bad case 记录模板、领域症状包。
- `delivery-playbook.md` — 落地阶段门禁（立项/PoC/试点/生产）与各阶段工具、角色×阶段分工矩阵、常见死因与预防。

### mocks/（多领域快速 mock，领域无关自证 + 新领域 PoC 脚手架）

- `run_mock.py` — 一键端到端自检：建库 → check_model → gold_lint → 口径编译直算 → run_eval 离线比对；`--all` 跑全部领域，`--domain` 跑单个。
- 内置 5 个自包含行业场景（各含 build_db.py 确定性造数 + semantic.yaml 迷你本体 + cases.json gold 用例）：
  `retail/` 零售电商·销售运营、`finance/` 银行·信贷风控（含 declared_conflict 写法范本 F06）、
  `healthcare/` 医疗·门诊运营、`manufacturing/` 制造·设备与生产、`government/` 政务·民生服务。
- 新领域照抄模板：10 分钟建 3 文件（造数 + 本体 + 用例），第一天就有回归基线；详见 `mocks/README.md`。
