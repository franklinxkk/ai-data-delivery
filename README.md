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

- **Kimi Work**：把本仓库作为技能安装（Skills 管理 → 从 GitHub 安装），或下载 Release 中的 `ai-data-delivery_v0.0.3.skill` 包导入。
- **手工**：clone 后将本目录放入你的 skills 目录即可，`SKILL.md` 为入口。

## 实测自证

全部脚本已在真实工程资产上回归自证：94 指标 / 15 宽表 / 4395 行物理库 / 62+12 条评测用例；发版门禁、双路径口径对账、计划稳定性检测均有正反两面的退出码验证。

## 实测修复（v0.0.3）

v0.0.3 由真实项目实测证据驱动，修复 10 项问题（P0×3 / P1×3 / P2×4），全部逐条对账并通过回归：

- `run_eval`：拒绝/追问类期望不再误判 FAIL（`expect_table` 拒绝标记 + 行内 `gold_results`），summary 增加 unknown 计数告警——实测 74/74 通过，修复前 8 条误报清零。
- `patch_model`：`--verify-with-db` 现在编译修订后**完整口径**（filters + extra_where 全量）验算，新增 `--expect/--tol` 数值对拍，不一致拒写（exit=2）——实测 180→107、45→15 两起失真拦截成功。
- `reconcile_paths`：对账 SQL 并入指标 filters，×100 百分比量纲差异单列不压门禁——实测全量 43 指标 0 不一致。
- `gold_lint` 新增 E5/W5/W6/W7 检出规则；`capture_case`/`suggest_card` 兼容真实引擎 list 响应；`harvest_metrics` 支持 `--from-meta` 映射，假"无来源"94→9；`gen_metadata`/`ingest_ddl` 角色推断修复（is_overdue→dim、deadline→time）。
- 另含跨平台建目录审计、promote_gold 自动初始化等健壮性修复；27 脚本 --help 冒烟与 release_gate 集成回归全过。

## License

[MIT](LICENSE)
