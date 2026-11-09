# 固定语义包与离线调用

本入口交付对象、术语、属性、关系、指标、规则及其依据。术语和规则可以没有数据库或可执行 SQL。工作台生成 ZIP；消费方只需这份 ZIP 或解包目录，以及本工具的只读 CLI，不需要原项目 SQLite、原工作台会话或模型服务。

`model.json` 是包内唯一语义定义。图形查看、文件导出和 CLI 使用同一资产 ID、方向和来源。包中内容只是知识与执行说明；规则是否执行、数据是否正确，不能由“已确认”或包指纹推出。

## 从文件读取

在本工具目录运行以下命令。把路径替换为实际收到的包；有中文或空格的路径加引号。命令不读取当前目录中未指定的项目，不自动打开来源链接。

```powershell
python -X utf8 scripts/semantic_read.py --package "C:\交付资料\交通语义.zip" verify
python -X utf8 scripts/semantic_read.py --package "C:\交付资料\交通语义.zip" search --query "营运车"
python -X utf8 scripts/semantic_read.py --package "C:\交付资料\交通语义.zip" get --id ent_vehicle
python -X utf8 scripts/semantic_read.py --package "C:\交付资料\交通语义.zip" sources --id rule_maintenance
python -X utf8 scripts/semantic_read.py --package "C:\交付资料\交通语义.zip" neighbors --id ent_vehicle --direction in --depth 1
```

需要再次交付时，明确选择 ID。输出目录需要已经存在，输出文件不能存在；失败不覆盖已有快照。

```powershell
python -X utf8 scripts/semantic_read.py --package "C:\交付资料\交通语义.zip" export --id rule_maintenance --out "C:\交付资料\维护规则子图.zip"
```

`--package` 放在命令名前。每次命令标准输出只有一个 JSON 结果；文件损坏、参数错误、未知 ID 等返回退出码 2。正常读取、明确歧义、无匹配或结果截断均返回退出码 0，但调用方必须继续检查 `status`、`complete`、`truncated`，不能只判断进程退出码。

## 包内文件

| 文件 | 内容 |
|---|---|
| `model.json` | `schema_version: "1.0"`、资产列表 `assets`、旧 ID 到存续 ID 的 `redirects`。 |
| `sources.json` | 选中断言使用的来源、具体修订、原文位置和片段。只带这些片段，不能据此声称已带完整来源文档。 |
| `manifest.json` | `format_version: "semantic-package/1.0"`、快照 ID、项目身份、来源项目修订、实际范围、草稿状态、缺口、逐文件 SHA256 及规范化模型 SHA256。 |
| `README.md` | 包内调用及边界说明。 |
| `human-review.html` | 无外部依赖的只读页面，展示同一模型的定义、原始关系方向、范围及来源。 |

包不携带原附件、项目数据库或其他未引用来源片段。源码中的读取器只接受这份固定文件清单；混入文件、重复 ZIP 成员、损坏 JSON、指纹不符或不支持的格式均拒绝消费。指纹验证只证明文件与清单一致，不构成来源认证、电子签名或业务验收。

固定快照不会随工作图谱修改而变化。相同输入产生相同包内容；新内容或新项目修订产生新快照身份。离线始终返回 `is_latest: "unknown_offline"`，不能判断是否已经有更新，更不能撤回已发出的文件。

## 资产及依据

每个资产使用项目内唯一的稳定 `id`。`kind` 支持 `entity/term/attribute/relation/metric/rule/dataset/field/mapping`。资产包含名称、定义、领域、适用范围、别名、知识状态、属性、显式必须引用 `refs`、依据和业务有效期。状态为 `draft/confirmed/needs_review/retired`。

关系与映射另外保存 `from/to/predicate/relation_type`。反向查看只改变遍历方向，不改原谓词、不生成新业务事实。分类关系不会自动产生继承或推理。按 ID 读取只识别明确 ID 和合并重定向，绝不把同名对象当作 ID 替换。

来源依据使用 `source_id + revision + fragment_id + quote`。确认发布会核对这些身份、原文位置和内容指纹，并检查摘录确实位于指定片段中。人工依据保留 `type: manual`、原话、记录人和记录时间。发布不要求把人工决定假装成外部文档，但缺少依据的声明不能发布为完整确认包。

同一内容修订重新提取时，依据可同时携带 `extraction_id`，指向该次提取的片段。来源修订中的 `extractions` 保留各次结果；包只带实际引用的提取片段。旧依据没有提取 ID 时，可在全部提取中寻找同一片段 ID；若其内容或位置有多种解释，则必须明确提取身份，不能自动换绑到最新结果。

来源更新后仍可保留旧修订依据；是否已复核由资产状态表明。旧原文不会被悄悄换成新片段。读取 `sources` 返回当时的具体修订及摘录，不能声称读取了来源的最新全文。

## 发布范围和依赖

确认包要求范围内每个资产均 `confirmed`，有非空定义、领域、范围及有效依据；未解决冲突、必须引用缺失、需复核或停用依赖都阻止该范围发布。其他无关资产有问题时，仍可单独选择完整资产发布。

共用类型检查还要求：指标明确单位、粒度、包含项、排除项和时间范围；规则明确条件和要求；属性/字段明确值类型。关系检查起终点类型与物理外键字段数量；分类关系不得成环。保存草稿时允许缺少上述内容字段，但结构及明确引用仍需有效。导出草稿会如实保留不完整状态。

草稿可保存候选、缺口和缺失依据，`draft: true`，有缺口时 `complete: false`。读取器会复查包内状态和依据，不仅信任清单上的成功文字。

范围选择规则：

- `asset_ids` 为空时选择所有知识资产；默认不把 `dataset/field/mapping/physical_fk` 作为根节点。显式选定任何这些资产仍会交付它们。
- 顶层 `refs` 以及关系的 `from/to` 永远是必须依赖。递归补齐至引用闭合，循环去重。遇到跨领域或物理资产仍带上定义，不能为了缩图删掉必需内容。
- 不自动展开这些依赖的所有邻接关系。因此只选一条规则可以带齐规则所需对象，而不夹带这些对象的无关业务网络。
- `include_execution` 额外包含物理资产根节点和 `properties.execution` 块。执行块中的 `refs/data_refs` 仅在包含执行块时参与闭合；默认移除整个执行块，并在 `omitted_execution_ids` 中列明。其他业务属性保留。
- `scope.root_ids/dependency_ids/included_ids` 分别说明根节点、自动补入项和最终范围；`omitted_asset_count` 仅相对于输入模型，不代表整个领域的未知知识数量。

从离线包再导出子图只能使用父包已有内容。父包没有携带执行配置时，不能通过参数凭空恢复它。程序读取这些说明不会执行其中的 SQL、脚本、业务动作或 URL。

## 搜索、日期、关系与完整性

| 调用 | 结果要求 |
|---|---|
| `search --query` | 按名称/别名精确匹配优先，再查定义等文本；返回命中原因和候选。多条匹配返回 `ambiguous`，不自动选第一条。分页前计算是否歧义，`--limit 1` 不会隐藏第二种含义。 |
| `search --domain/--kind/--scope` | 依据调用方明确提供的条件过滤。`scope` 可以是完全匹配的范围文字，或用于匹配范围对象的 JSON 子集。业务范围不是权限。 |
| `search --as-of YYYY-MM-DD` | 未指定日期保留所有有效期。指定日期时排除明确不在区间内的项；缺少任一时间边界的项标 `applicability: unknown` 并保留，不能据此假定唯一答案。日期边界按日包含。 |
| `get --id` | 返回完整定义、状态与依据；提供 `--as-of` 也不隐藏指定资产，只报告是否位于已知区间。 |
| `neighbors --direction in/out/both --depth` | 深度 0–10，只遍历明确声明的关系。返回边原定义、实际正向/反向遍历、节点及其时间适用状态。可重复 `--relation-type` 限定类型。 |
| `sources --id` | 返回具体断言、来源修订、片段及位置。缺失或不匹配标明 `missing/invalid`，不能生成看似有效的引文。 |
| `export --id` | 可重复 ID；递归补齐明确必需依赖，生成新的固定子图包。 |

搜索和邻域支持 `--limit 1..500`、`--offset`；返回 `total/next_offset/truncated`。截断和非首页都不能标记为完整结果。`complete` 只针对本包或本次明确请求范围，并非“整个领域知识完整”。搜索的 `not_found` 只表示包内没有匹配，不能据此断言现实世界不存在该概念。

所有正常结果返回实际 `snapshot_id/source_revision/scope`。包通过完整性校验也不代表候选已确认、规则已执行、观点无争议或本包是最新版本。消费者先处理歧义与缺口，再基于已返回定义作答，并引用具体资产 ID 与来源。

## 程序接入与错误

工作台与 CLI 共用 `workbench.semantic_package`：

```python
content, manifest = build_package(
    assets, sources, project_id="project-id", revision=7,
    asset_ids=["rule_maintenance"], draft=False,
    include_execution=False, redirects={"old-id": "surviving-id"},
)
package = read_package("semantic.zip")
package.verify()
package.search("收入", domain="财务")
package.get("rule_maintenance")
package.sources("rule_maintenance")
package.neighbors("ent_vehicle", direction="in")
subgraph_bytes, subgraph_manifest = package.export(["rule_maintenance"])
```

`build_package` 和 `package_preview` 接受相同输入；后者只返回范围、状态和资产摘要。异常为 `PackageError(ValueError)`，其 `code/details/as_dict()` 可直接用于服务响应，不要只显示泛化“发布失败”。典型错误有 `NOT_PUBLISHABLE`（逐项 issues）、`UNKNOWN_ID`、`HASH_MISMATCH`、`UNSUPPORTED_FORMAT/UNSUPPORTED_SCHEMA`、`PACKAGE_CORRUPT`、`CONTENT_NOT_AVAILABLE`、`OUTPUT_EXISTS` 和 `INVALID_INPUT`。

`validate_semantic_assets(assets, redirects=None)` 是工作台与包共用的结构/类型检查入口，成功返回 `None`，失败抛上述异常；来源依据另由发布与读取共用的依据检查处理。它没有工作台或数据库访问副作用。

当前 CLI 没有编辑、确认、发布项目草稿或执行外部业务的命令。独立消费者不能通过包内角色文字提升权限；对文件的访问依赖操作系统。本期未提供 MCP/HTTP 消费服务。后续适配应复用这些方法，不能再写一套消歧、闭合或状态解释。

针对性验证运行：

```powershell
python -X utf8 -m unittest discover -s tests -p test_semantic_package.py -v
```

测试涵盖独立进程读取、中文/空格路径、来源修订、无数据库术语、同名消歧、时间未知、依赖闭合、关系方向、截断、损坏包、旧快照和只读边界。此类验证是代码与独立进程级证据，不替代工作台真实发布操作或独立 Agent 的业务理解验证。
