# ai-data-delivery

AI+数据落地工具包（Kimi Work skill）：面向 FDE（驻场/交付工程师）、产品经理与信息中心人员的企业级智能问数/数据分析系统**全周期交付工具链**。

模型能力会持续换代贬值；语义资产、回归集、操作规程不随之过时——本工具包锚定这三个常量，一切脚本围绕真实合同 Schema（`semantic.yaml`：`datasets[] / concepts[] / relationships[] / metrics[]`）。

## 全周期工具地图（27 个脚本）

| 阶段 | 输入 | 工具 | 输出 |
| --- | --- | --- | --- |
| 立项盘点 | 业务系统 DDL、历史指标公式 | `ingest_ddl` `profile_db` `detect_isomorphic` `harvest_metrics` `gold_seed` | 字段台账、枚举画像、同构族清单、指标三分清单、gold v0 骨架 |
| PoC 建模 | 台账 + 指标清单 + 领域知识 | `propose_dws` `gen_metadata` `bind_metrics` `coverage_check` `gen_eval_cases` | 宽表草案、meta 草稿、绑定结果、覆盖报告、评测用例草稿 |
| 试点闭环 | 活引擎 + gold 集 + 用户反馈 | `capture_case` `ingest_feedback` `suggest_card` `patch_model` `reconcile_paths` `promote_gold` `run_eval` | bad case 登记卡、修订建议卡、模型补丁、对账报告、回归报告 |
| 生产运营 | 已发布模型 + 物理库 | `release_gate` `gen_dictionary` `export_exchange` `check_consistency` `plan_stability` `impact_analysis` `probe_model` `check_model` `gold_lint` | 发版日志、口径字典、sha256 交换包、漂移告警、影响面清单 |

## 五条铁律

1. 模型层 YAML 优先，引擎层次之，数据层最后
2. 指标必须自含全口径，写入口径前必须对物理库验算
3. 引擎不承载业务口径
4. 先回归再交付
5. 一切修改走幂等脚本留痕，禁止手改 YAML

## 目录结构

```
SKILL.md                      # 入口：铁律、模块工作流、全量工具清单
references/
  delivery-playbook.md        # 落地手册：阶段门禁、角色分工矩阵、死因预防
  diagnosis-playbook.md       # 诊断手册：症状→层定位→修复对照、引擎不变式
scripts/                      # 27 个幂等脚本（全部支持 --help）
```

## 安装

- **Kimi Work**：把本仓库作为技能安装（Skills 管理 → 从 GitHub 安装），或下载 Release 中的 `ai-data-delivery_v0.0.2.skill` 包导入。
- **手工**：clone 后将本目录放入你的 skills 目录即可，`SKILL.md` 为入口。

## 实测自证

全部脚本已在真实工程资产上回归自证：94 指标 / 15 宽表 / 4395 行物理库 / 62+12 条评测用例；发版门禁、双路径口径对账、计划稳定性检测均有正反两面的退出码验证。

## License

[MIT](LICENSE)
