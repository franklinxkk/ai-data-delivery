# 信息中心：核对来源、变化与访问边界

先复用企业已有数据定义，不必为同一个业务问题另建整套模型。权限由实际数据系统控制，工具中的范围文字不是授权。

1. 让宿主围绕真实业务问题登记授权材料，或使用[只读目录流程](readonly-metadata.md)连接明确允许的 SQLite、PostgreSQL、MySQL 表。扫描产生候选，物理关系不自动解释为业务责任。
2. 核对字段与业务对象、指标、规则的映射。实际使用的字段应通过稳定 ID 进入依赖闭包；新增无关列无需全部纳入当前问题。
3. 更新已登记来源或目录后，检查受影响问题、依赖路径和旧验收是否失效；对新增限制核对适用性，不为清除告警直接沿用旧结果。
4. 向接收方交付问题包，让其先读[查询控制单](query-control.md)。SOURCE_REVISION_AHEAD 提醒导出时已知另有新修订；未交付的新正文仍须回原项目核对。离线包无法保证最新性或租户权限。

当前缺口保留在语义资产的 properties.knowledge_gaps、问题检查与控制单中；不是每个任务都会生成 gaps.yaml。负责人确认有据的业务决定，不能替代实际数据检查和系统授权。

已有独立 SQLite 快照和历史执行模型时，可按需运行以下数值工具；它们不会自动同步到新语义图谱：

```bash
python scripts/profile_db.py --db physical.db --out profile.yaml
python scripts/check_consistency.py --model semantic.yaml --db physical.db
python scripts/check_constraints.py --model semantic.yaml --db physical.db --out constraints.json
```

输入路径必须真实且已授权，输出与源库分开。工具只读访问；文件不存在不创建空库。空表、无检查规则、未执行和执行失败都不能视为验证通过。敏感字段启发式不等于脱敏结论。[安全边界](../SECURITY.md)
