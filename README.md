# ai-data-delivery

AI+数据落地工具包（Kimi Work skill）：面向 **FDE（驻场/交付工程师）**、**产品经理** 与 **信息中心人员** 的企业级智能问数/数据分析系统**全周期交付工具链**，领域无关——同一套合同 Schema（`semantic.yaml`：`datasets[] / concepts[] / relationships[] / metrics[]`）已在交通安全真实项目与零售、金融、医疗、制造、政务 5 个行业 mock 上验证同构适用。

模型能力会持续换代贬值；**语义资产、回归集、操作规程**不随之过时——本工具包锚定这三个常量。

## 5 分钟快速体验（无需活引擎）

```bash
python mocks/run_mock.py --all     # 5 个行业场景端到端自检：建库→模型lint→评测体检→口径编译→回归
```

每个场景自包含（造数脚本 + 迷你本体 + gold 用例），是了解工具链最快的方式，也是新领域 PoC 的脚手架。详见 [mocks/README.md](mocks/README.md)。

## 你是哪类角色？——角色 × 阶段 × 价值地图

### 🔧 FDE（驻场/交付工程师）——落地执行者

| 阶段 | 你要做的事 | 跑什么 | 拿到什么 |
| --- | --- | --- | --- |
| 立项盘点 | 把甲方的业务系统 DDL 变成台账 | `ingest_ddl` `profile_db` `detect_isomorphic` | 字段台账、枚举画像、同构族清单（298 张源表里揪出 30 张同构表，避免 30 倍重复劳动） |
| PoC 建模 | 起草宽表与语义模型 | `propose_dws` `gen_metadata` `bind_metrics` `coverage_check` | 宽表合并草案、meta 草稿、指标绑定缺口清单、三方覆盖报告 |
| 试点闭环 | 排查 bad case、修模型 | `capture_case` `suggest_card` `patch_model` `reconcile_paths` `run_eval` | 一键取证登记卡、修订建议卡、验算过的幂等补丁、双路对账报告、回归报告 |
| 生产运营 | 发版与巡检 | `release_gate` `check_consistency` `impact_analysis` | 四闸发版结论 + 发版日志（出事后唯一的免责证据）、上游漂移告警、变更影响面 |

**核心价值：所有操作幂等留痕、可复跑、可审计——换人来接手不需要口口相传。**

### 📋 产品经理——口径定义的责任人

| 阶段 | 你要做的事 | 跑什么 | 拿到什么 |
| --- | --- | --- | --- |
| 立项盘点 | 盘点历史指标公式能不能落地 | `harvest_metrics` | 指标三分清单：可执行 / 需改写 / 无来源（无来源指标第一天就暴露，不混进合同） |
| PoC 建模 | 定义口径并挂依据文号 | `patch_model struct`（带 `--db` 验算 + `--expect` 对拍）、`gen_eval_cases` | 自含全口径的指标定义（口径争议在评审会上定，不在引擎里猜）、评测用例草稿（你只补 gold） |
| 试点闭环 | 提 bad case、确认期望 | `ingest_feedback` `promote_gold` | 反馈热度池（同问句自动累计次数=优先级）、不断长大的 gold 集 |
| 生产运营 | 验收签字 | `run_eval` 报告 + `gold_lint` 体检 + `gen_dictionary` | 验收三件套：回归通过率、评测集无矛盾证明、人能读的口径字典 |

**核心价值：你说的"口径"不再是微信群里的截图，而是写进 YAML、经过物理库验算、有文号依据的合同条款。**

### 🏛 信息中心——数据源与门禁的把关方

| 阶段 | 你要做的事 | 跑什么 | 拿到什么 |
| --- | --- | --- | --- |
| 立项盘点 | 提供数据源、评估数据质量 | `profile_db` | 空值率/枚举分布/敏感列画像（敏感列自动不取样） |
| PoC 建模 | 确认列映射与新鲜度 | meta 草稿中的 `【】` 占位项清单 | 一份明确的"待信息中心确认"事项表 |
| 试点闭环 | 区分"模型错"还是"数据错" | `reconcile_paths` | 双路径对账报告：指标口径直算 vs 引擎问数，不一致即双口径，责任边界一目了然 |
| 生产运营 | 上线门禁与合规 | `release_gate` `check_consistency` `export_exchange` | 门禁结论（零失败才放行，已声明冲突豁免但留痕）、上游结构漂移巡检、带 sha256 清单的交换包 |

**核心价值：上游表结构一变、字段一删，巡检立即报警——不再等业务投诉才发现数据断了。**

## 全周期工具地图（27 个脚本 + 1 个 mock 运行器）

| 阶段 | 输入 | 工具 | 输出 |
| --- | --- | --- | --- |
| 立项盘点 | 业务系统 DDL、历史指标公式 | `ingest_ddl` `profile_db` `detect_isomorphic` `harvest_metrics` `gold_seed` | 字段台账、枚举画像、同构族清单、指标三分清单、gold v0 骨架 |
| PoC 建模 | 台账 + 指标清单 + 领域知识 | `propose_dws` `gen_metadata` `bind_metrics` `coverage_check` `gen_eval_cases` | 宽表草案、meta 草稿、绑定结果、覆盖报告、评测用例草稿 |
| 试点闭环 | 活引擎 + gold 集 + 用户反馈 | `capture_case` `ingest_feedback` `suggest_card` `patch_model` `reconcile_paths` `promote_gold` `run_eval` | bad case 登记卡、修订建议卡、模型补丁、对账报告、回归报告 |
| 生产运营 | 已发布模型 + 物理库 | `release_gate` `gen_dictionary` `export_exchange` `check_consistency` `plan_stability` `impact_analysis` `probe_model` `check_model` `gold_lint` | 发版日志、口径字典、sha256 交换包、漂移告警、影响面清单 |
| 领域自检 | mocks/ 场景包 | `mocks/run_mock.py` | 5 行业端到端通过证明 |

## 五条铁律

1. 模型层 YAML 优先，引擎层次之，数据层最后
2. 指标必须自含全口径，写入口径前必须对物理库验算（`patch_model --db --expect` 强制）
3. 引擎不承载业务口径
4. 先回归再交付（声明式冲突豁免必须带决策出处留痕）
5. 一切修改走幂等脚本留痕，禁止手改 YAML

## 目录结构

```
SKILL.md                      # 入口：铁律、模块工作流、全量工具清单
references/
  delivery-playbook.md        # 落地手册：阶段门禁、角色分工矩阵、死因预防
  diagnosis-playbook.md       # 诊断手册：症状→层定位→修复对照、引擎不变式
scripts/                      # 27 个幂等脚本（全部支持 --help）
mocks/                        # 5 个行业 mock 场景 + run_mock.py 一键自检
```

## 安装

- **Kimi Work**：把本仓库作为技能安装（Skills 管理 → 从 GitHub 安装），或下载 Release 中的 `ai-data-delivery_v0.0.4.skill` 包导入。
- **手工**：clone 后将本目录放入你的 skills 目录即可，`SKILL.md` 为入口。

## 实测自证

- **真实项目**（交通安全监管，15 宽表 / 94 指标 / 4395 行物理库 / 75 评测用例）：全链路回归 75/75，发版门禁 4/4 通过；v0.0.3 实测修复 10 项、v0.0.4 收口验证再修 2 项（promote_gold 首条丢失、声明式冲突机制）。
- **多领域 mock**：零售 / 金融 / 医疗 / 制造 / 政务 5 场景 `run_mock.py --all` 5/5 通过——合同 Schema 领域无关。

## License

[MIT](LICENSE)
