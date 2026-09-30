# FDE 工程师 · 快速通道

你负责把语义合同落地并验证。你的主干只有 5 步，其余命令用到再查。

## 你的一天（5 条命令）

```bash
# 1. S0 盘点：DDL → 台账（mysqldump 风格 COMMENT 也吃得下；解析失败的表记台账不拖垮文件）
python scripts/ingest_ddl.py --ddl source.sql --out inventory/ --model-out draft.yaml

# 2. S1/S2 建模：开补齐会话（可从模板包冷启动），agent 会按角色分工提问
python scripts/guide_model.py init --model draft.yaml --scope scope.yaml --session session.yaml --pack general
python scripts/guide_model.py status --session session.yaml   # 看 outstanding 清零报告

# 3. S3 验证：lint + 关联键 + 全量约束（lint 过了才谈数据）
python scripts/check_model.py -f exported/semantic.yaml
python scripts/check_join_graph.py --model exported/semantic.yaml --db physical.db --out joins.json
python scripts/check_constraints.py --model exported/semantic.yaml --db physical.db --out constraints.json

# 4. S3 口径实证：指标编译 SQL 直算，与问数路径对账（有活引擎才加 --endpoint）
python scripts/reconcile_paths.py --model exported/semantic.yaml --db physical.db --out reconcile.json

# 5. S4 门禁：按当前阶段选档（static 只 lint；validated 要评测报告+快照）
python scripts/release_gate.py --model exported/semantic.yaml --cases cases.json \
    --profile validated --db physical.db --eval-report eval_report.json --out gate.json
```

## 边界提醒

- `--out` 多数是**目录**，但 `detect_isomorphic.py`/`profile_db.py` 是**文件路径**（给目录会报明确错误）。
- `impact_analysis --target` 写裸名（如 `hazard`），不带 `dataset:` 前缀。
- live 工具（capture_case / plan_stability / probe_model / rebuild）需要活引擎；没有引擎时 S0–S4 合同侧照常闭环。
- 端点默认仅本机/内网，远程加 `--allow-remote`。

## 出问题时去哪

bad case 诊断 → [诊断手册](diagnosis-playbook.md)；全量工具表 → [工具清单](tools.md)；模型字段语义 → [合同与验证](contract.md)。
