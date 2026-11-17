# FDE：把同一个问题交付给接收方

先复用已有语义与实际资料，只补当前问题需要的含义和依赖。主数据源是 document.model.semantic.assets，不再手工维护第二份语义 YAML。

```bash
python -m pip install -r requirements.txt
python -X utf8 scripts/start.py --project ./work/equipment-fde --example equipment --language zh
```

按[业务负责人步骤](quickstart-pm.md)核对 DDL 和业务候选。真实项目不加 --example，用材料摄取/宿主任务处理授权路径。SQLite/PostgreSQL/MySQL 目录可使用[只读元数据入口](readonly-metadata.md)；只扫描获准表，不读取业务行。

| 要核对什么 | 交付要求 |
| --- | --- |
| 业务范围与反例 | 原文、负责人决定和独立预期可回查；缺失条件保持未知 |
| 指标与数据 | query_plan 引用实际数据集、字段、映射和必要规则；字段 ID 进入依赖闭包，避免改列后旧验收仍通过 |
| 单表与多表 | 单表不强造关系；声明多表关系不等于验证 JOIN、基数或去重；本版不生成通用 SQL |
| 查询边界 | 先看 control，再按需读 task 和 sources；结构完整与执行许可分别判断 |
| 变更 | 修改字段、来源或口径后，核对影响路径、失效案例和新来源适用性；保留失败证据 |

让宿主根据[查询约定](query-control.md)提出 metric.properties.query_plan，通过现有候选/编辑路径核对。不要让业务负责人填 JSON，也不要为消除 blocker 自动补 NULL、时间或关联策略。现有项目不会自动添加绑定。

```bash
python -X utf8 scripts/knowledge.py --project ./work/equipment-fde check --scenario SCENARIO_ID
python -X utf8 scripts/knowledge.py --project ./work/equipment-fde handoff --scenario SCENARIO_ID --out ./delivery/question.zip
python -X utf8 scripts/semantic_read.py --package ./delivery/question.zip control
python -X utf8 scripts/semantic_read.py --package ./delivery/question.zip task --detail summary
python -X utf8 scripts/semantic_read.py --package ./delivery/question.zip sources --id demo.available
```

替换真实 scenario ID；先建立输出目录，文件不可已存在。接收方不依赖原工作台。0.3.4 的 query/calculate 始终 blocked：执行需要另行核验当前源、数据时间、租户权限、资源限制和结果；不能把 CLI 退出码 0 当成执行许可。

如果任务本来就是核对数值，[旧数值与明细工具](metric-context.md)仍可使用 --demo 或显式模型/独立快照。它们与新语义图谱不自动双向同步，数值工具的成功也不授权 query_control 执行。远端目标必须在实际授权范围内。[安全边界](../SECURITY.md)
