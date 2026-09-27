# ai-data-delivery · v0.0.5

面向 FDE、产品经理和甲方信息中心的语义交付 skill：从部分数据结构与业务描述出发，引导补齐语义，形成可审阅、可验证、可交换的标准结果。已有模型可直接进入检查和可视化。

本版以 `semantic.yaml` 的 datasets / concepts / relationships / metrics 为基础，新增持久补齐会话、复合关联键与查询粒度检查、SQLite 数据约束、离线可视化，以及更严格的证据门禁。保留 v0.0.4 的工具入口，收紧了原先会把缺报告或无效豁免当成成功的行为。

## 快速体验

需要 Python 3.10+，只有 PyYAML 一个第三方 Python 依赖。

```bash
python -m pip install -r requirements.txt
python examples/onboarding/run_demo.py --out tmp/demo
python mocks/run_mock.py --all
```

第一条示例从缺少粒度与口径的模型开始，加载**合成的已确认决策**，执行补丁审阅/应用、导出、关联/约束检查、评测、门禁及交换包生成。打开 `tmp/demo/model.html` 可搜索数据集、查看映射、补齐状态和验证证据。输出目录必须为空；重跑请换目录。

示例金额为 300；订单到客户 N:1 保持订单粒度，订单直接连接商品明细则会累计成 400。五行业 Mock 直接根据 metric/SQL 生成应答，拒答由模拟器提供，**不验证真实 AI 理解或拒答能力**。

## 按阶段使用

| 阶段 | 产品/业务负责人 | FDE | 信息中心 | 标准结果 |
| --- | --- | --- | --- | --- |
| S0 盘点 | 定义具体问题与价值 | 解析已有材料 | 提供可用结构与访问范围 | scope、源表/字段台账 |
| S1 补齐 | 确认口径与例外；PM 需相应授权 | 提出有证据的候选并记录答案 | 确认来源、身份、历史与时效能力 | gap、decision、审阅补丁 |
| S2 建模 | 审阅业务定义 | 映射实体/字段/关联与指标 | 核对实际数据契约 | semantic.yaml、结构与约束草案 |
| S3 验证 | 确认独立期望 | 检查关联、结果对拍与回归 | 检查全量快照和数据质量 | 绑定版本/快照的验证报告 |
| S4 交付 | 接受适用范围与剩余项 | 对接具体消费者、交付交换包 | 确認运行与权限条件 | manifest、字典、用例、证据、视图 |
| S5 演进 | 调整优先级与口径 | 分析变更、修复和回归 | 巡检结构/数据/运行变化 | 差异、影响候选、再验证记录 |

可以分段交付。没有数据库时，S1/S2 仍可推进；涉及真实数据的结论保留未验证。只有现状表时，历史月末问题应产出补采需求，不把当前状态当历史事实。

## 从你的材料开始

```bash
# 已有部分 semantic.yaml：先定义当前用例 scope（格式见 examples/onboarding/scope.yaml）
python scripts/guide_model.py init --model partial.yaml --scope scope.yaml --session session.json
python scripts/guide_model.py status --session session.json
# 根据真实回答创建 answers.json，审阅生成的补丁后再应用
python scripts/guide_model.py propose --session session.json --answers answers.json --patch review.json
python scripts/guide_model.py apply --session session.json --patch review.json
python scripts/guide_model.py export --session session.json --out draft

# 只有 DDL 时：生成台账及部分模型，不猜业务粒度/口径
python scripts/ingest_ddl.py --ddl schema.sql --out inventory --model-out partial.yaml
```

详细输入、回答、冲突修订和重新验证流程见 [补齐闭环](references/onboarding.md)。数据检查、关系与约束示例见 [合同与验证](references/contract.md)。

## 证据与门禁

```bash
python scripts/check_model.py -f semantic.yaml
python scripts/check_join_graph.py --model semantic.yaml --db snapshot.db --out joins.json
python scripts/check_constraints.py --model semantic.yaml --db snapshot.db --out constraints.json
python scripts/run_eval.py --gold cases.json --actual actual.json --model semantic.yaml --db snapshot.db --report eval.json
python scripts/release_gate.py --profile validated --model semantic.yaml --cases cases.json --db snapshot.db --eval-report eval.json --out gate.json
python scripts/visualize_model.py --model semantic.yaml --report joins.json --report constraints.json --report gate.json --out model.html
```

`static` 只证明指定结构检查通过；默认 `validated` 要求当前模型、用例、数据快照和完整评测证据；`production` 另要求真实端点证据和稳定性抽查。结论带 `mock/offline/live` 来源，有豁免时单独标记。技术门禁不代替业务签署、部署、身份认证或现场运行验收。

## 文档与兼容性

- [SKILL.md](SKILL.md)：Agent 入口与任务路由。
- [全部工具](references/tools.md)：保留原有 27 个工具，新增 4 个公开命令；共享辅助模块不属于 CLI。
- [交付及迁移](references/delivery-playbook.md)：阶段门禁、旧版报告/豁免迁移。
- [诊断手册](references/diagnosis-playbook.md)：已有 bad case 工作流。
- [标准边界](references/standards.md)：GB/T 48000.3—2026、Apache Ossie 与其他规范的适用范围。
- [本版验证记录](references/v0.0.5-validation.md)：测试范围和未验证项。

没有通用跨表 SQL 编译器、OWL 推理器、Ossie 适配器或实时血缘采集器。关系键借鉴了显式左右列的做法，但此格式仍是本项目合同；YAML lint 不等于国标符合性。大型库/其他数据库需要接入真实消费者再评估。

## 安装和维护

把仓库目录放入宿主的 skills 目录；或从 [Releases](https://github.com/franklinxkk/ai-data-delivery/releases) 下载 `ai-data-delivery_v0.0.5.skill`，在支持该格式的宿主导入。不同宿主的发现、权限及脚本运行行为需要现场确认。

```bash
python -m unittest discover -s tests -v
python maintainer/build_skill.py --out dist
```

构建脚本只打包 Git 已跟踪的运行资产，默认要求干净源码，生成确定性 `.skill` 与 SHA256 清单。开发态预览可加 `--allow-dirty`，不得将其当作已发布构建。

[MIT License](LICENSE)
