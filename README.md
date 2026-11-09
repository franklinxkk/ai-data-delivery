# ai-data-delivery · v0.2.3-dev

把表结构、业务知识、行业术语、指标口径和管理制度整理成**有原文依据、可视化维护、可交给 Agent 使用的统一语义图谱**。

主线是：**加入材料 → 形成候选 → 人工核对 → 维护图谱 → 发布固定语义包 → 离线调用**。对象、术语、属性、关系、指标、规则和数据映射使用同一套语义资产；没有数据库或 SQL，也可以建模和交付。

工作台负责本地存储、文件解析、候选审阅、图谱编辑和导出。业务语义的理解由当前宿主 Agent 协助完成，工具不自带大模型，也不会在上传文件后自动调用 AI 或自动确认定义。

[MIT](LICENSE) · [工作台操作](workbench/README.md) · [离线调用合同](references/semantic-package.md) · [安全边界](SECURITY.md)

本版已验证合成材料的完整主链路、双批次更新与独立 Agent 读取；范围、实际结果和未验项见[开发验证记录](references/m1-m2-validation.md)。

## 从一份真实材料开始

需要 Python 3.10+。在工具目录运行；中文或含空格的路径请加引号：

```bash
python -m pip install -r requirements.txt
python -X utf8 scripts/start.py --project "./work/ontology"
```

打开终端打印的本机网址，然后完成以下操作：

1. 在 **知识材料** 粘贴一段业务原文，或上传已有文件，检查解析位置和警告。DDL 的明确结构和受支持的语义模型可直接形成结构候选；其他材料先保留原文与片段。
2. 点击 **准备 Agent 任务**，把生成的指令交给当前宿主 Agent。Agent 读取该批次原文与现有图谱，提交带出处的候选。没有宿主时，也可以在图谱中手工新建知识并填写依据。
3. 在 **待核对** 比较现有定义、候选和原文，可修改后接纳整组，也可暂缓或拒绝。上传成功和候选提交成功都不等于定义已确认。
4. 在 **语义图谱** 搜索名称或别名，切换业务、指标与规则、数据映射视图；拖动节点整理布局，从连接点拖出关系并填写谓词、定义与依据。
5. 在 **交付与调用** 选择知识范围，发布确认快照或导出草稿。下载 ZIP 后打开 `human-review.html` 核对，或让另一个 Agent 使用只读 CLI。

以后使用相同的 `--project` 路径重开。项目保存在本机 SQLite；首次初始化可以加 `--ddl "./materials/schema.sql"` 或 `--model "./materials/model.json"`，文件仍进入材料和候选流程。已有项目请从页面增量加入材料，不重复使用初始化参数。

可以向已安装本 skill 的 Agent 直接说：

> 使用 ai-data-delivery。我要建立【领域】的语义图谱，资料在【路径】，项目保存在【目录】。请保留原文出处，先提出有依据的候选，帮我核对同名对象、关系和规则的适用范围；确认后生成可独立调用的语义包。不要把推测当作已确认知识。

## 可以输入什么

| 材料 | 当前读取能力 | 需要核对的边界 |
| --- | --- | --- |
| 粘贴原文、TXT、Markdown | 保留文字、行/段落位置；Markdown 保留标题路径 | 链接和文字中的命令不执行；业务含义由宿主提出候选或人工录入 |
| SQLite/MySQL DDL | 解析受支持的 `CREATE TABLE`、列、主键及显式外键，保留复合键顺序和原文位置 | 不连接数据库，不执行 SQL；未知语法明确提示。外键只表示物理引用，不推断业务所有权 |
| CSV、XLSX | 读取工作表、表头、行与单元格，支持选择工作表/表头行/区域 | 不重算公式；缺缓存值不当作 0，合并单元格不自动填充；术语、指标及规则清单仍需解释与核对 |
| DOCX | 提取可读取段落、标题及表格单元格 | 图片、嵌入对象、复杂版式等列出限制；不伪造页码 |
| 有文本层的 PDF | 按页提取文本并保留页码 | 不做 OCR；扫描页、加密内容需补充可读副本；表格结构、多栏顺序和图片内容需对照原页 |
| JSON、YAML | 安全解析并保留原文；包含受支持 `semantic.assets` / `assets` 的模型产生候选 | 任意旧模型不会自动变成已确认图谱；不能理解的结构作为材料交给宿主处理 |

每份文件最多 **32 MB**。解析会分别报告完成、部分完成、失败或待转换，保留可用片段和修复提示；“解析完成”只说明读取结果。完整限制和更新方法见[工作台操作](workbench/README.md)。

## 如何维护一份持续变化的图谱

材料有独立来源身份、内容修订和解析记录。相同内容默认复用，出处不同可以明确保留独立来源；同名新内容需要选择更新还是另建。来源变化时保留旧依据，并对受影响知识提出复核。

候选和已确认知识分开保存。稳定 ID 用来维护引用，名称和别名用来查找；同名不自动合并。操作者可以比较含义、合并身份或说明为何保持分离。整组接纳会重新检查当前来源、目标及依赖，冲突时保留输入供核对。拖动布局与修改业务语义分别保存。

## 给另一个 Agent 什么

交付 ZIP 包含 `model.json`、必要来源片段 `sources.json`、范围和指纹清单 `manifest.json`、`human-review.html` 与调用说明。默认不含原始附件或项目数据库；私人项目备份另行下载。

消费方需要这份包和本工具读取器，无需原项目或运行中的工作台：

```bash
python -X utf8 scripts/semantic_read.py --package "./delivery/semantic.zip" verify
python -X utf8 scripts/semantic_read.py --package "./delivery/semantic.zip" describe
python -X utf8 scripts/semantic_read.py --package "./delivery/semantic.zip" search --query "营运车辆"
python -X utf8 scripts/semantic_read.py --package "./delivery/semantic.zip" context --id "从搜索结果取得的资产ID" --intent explain
python -X utf8 scripts/semantic_read.py --package "./delivery/semantic.zip" sources --id "从搜索结果取得的资产ID"
```

调用方应检查返回的快照、实际范围、草稿/完整状态、歧义及截断信息，再读取定义和依据。固定快照不会随项目修改而变化；离线不能判断是否已有更新。文件指纹证明内容一致，不证明业务结论正确。邻域遍历、子图导出和程序接口见[离线调用合同](references/semantic-package.md)。

## 数值分析仍可按需使用

已有的单表指标试算、数值与明细核对、SQLite 约束检查、指标上下文包和本机演示引擎联调保留为次入口。在图谱页选择 **数值与明细核对**；在材料页选择 **打开数值试算资料**。这些工具使用自己的数值模型与快照，确认语义不会自动生成可执行 SQL，也不会自动同步数值口径。

想体验 A、A、NULL 的行数/非空数/去重数差异，可在新目录启动合成练习：

```bash
python -X utf8 scripts/start.py --project "./work/numeric-demo" --demo
```

打开工作台后进入 **数值与明细核对**。未填写独立预期只记计算完成，合成练习不代表生产验收。相关命令见[指标消费路径](references/metric-context.md)、[诊断手册](references/diagnosis-playbook.md)和[原有工具清单](references/tools.md)。

## 安装与开发状态

把完整目录安装到宿主支持的 skills 位置，再请 Agent 使用 `ai-data-delivery`。工作台和离线读取器也可独立使用；无需另装需求设计 skill。运行依赖为 PyYAML 与 pypdf，无需 Node、CDN 或 AI API 密钥。

**v0.2.3-dev 是开发版本。1.0 前不承诺旧项目、模型格式或命令行为兼容。** 本轮以新项目开始；升级前保留原目录和私人备份，不把旧项目直接覆盖为新格式。历史验证记录仅适用于其标注的版本和场景，本说明不宣称已完成业务验收、生产部署或性能验证。

维护者可按改动范围运行解析、知识流程、语义包及原有能力测试；源码中的完整检查入口为：

```bash
python -m unittest discover -s tests -v
python mocks/run_mock.py --all
```

安装包不含源码测试、可执行 mock 树或通用服务重建工具。维护任务在源码仓库进行，具体能力范围及本次审计处置见[安全说明](SECURITY.md)。

更多背景：[大会机制取舍](references/conference-practices-2026.md)、[领域起步包](starter_packs/README.md)、[标准边界](references/standards.md)。这些是按需参考，不是建图前必须完成的流程。

**English:** A local semantic workbench: import materials, review evidence-linked proposals, maintain one graph, publish fixed packages, and let an independent agent read them offline. The host supplies AI reasoning; the workbench does not include an LLM or automatically confirm knowledge.
