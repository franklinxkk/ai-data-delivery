# Changelog

Versioning: keep published tags unchanged; continue from `0.3.0` with patch increments (`0.3.1`, `0.3.2`, …). Unreleased previews use `-dev`. / 版本约定：保留已发布标签，后续默认递增补丁号，开发预览加 `-dev`，不重写历史版本。

## 0.3.1-dev — 2026-11-12 (local development preview)

- Start from a saved business question, expected examples and selected definitions; inspect task-specific dependencies and gaps without claiming an answer or executing data/actions. / 新增业务问题入口、保存重开、预期线索及只读准备检查。
- Reuse existing transactional candidate review, scope-aware publication and offline packages. Show meaning, conditions and evidence before detailed editing fields. / 复用原候选核对和发布，先展示业务含义，详细配置收起。
- Add scenario-aware host tasks and `semantic_read.py resolve --question`; explicit meaning selection produces required context with evidence and execution boundaries. / 宿主任务可聚焦问题，Agent 可从问题发现候选、明确选择后读取上下文。
- Preserve source dispositions, optimistic concurrency and retry receipts. Restore scoped delivery after reload and refuse accidental empty-to-all expansion. / 保留处置与事务合同，修复范围交接及冲突恢复。
- Fix typed scope matching for zero, false, null and missing keys; shorten bilingual instructions through relevant references. / 修复范围类型匹配并精简双语入口。
- Exercise traffic, agriculture, university and finance semantics with 32 synthetic questions and 54 assets; fix short Chinese business terms missing compound labels. / 新增四域合成问题与反例，修复“批次怎么追溯”漏掉“产品批次”候选。
- Export confirmed objects/relations to OGS 1.1.0 with explicit per-asset coverage and opaque semantic/evidence preservation; audit actual roundtrip losses. No database mapping, import or rule execution is inferred. / 新增有覆盖报告的 OGS 离线投影和往返损失检查。
- No embedded LLM, production query gateway, authorization service or action executor. Existing v0.3.0 assets remain unchanged when scenarios are added. This is not a remote release. / 不增加嵌入模型或生产执行能力，未发布到远端。

## 0.3.0 — 2026-11-09

- Add English and Simplified Chinese skill instructions, README, workbench UI and guides; preserve original knowledge when switching language. / 新增中英文技能、说明和工作台界面，切换不改写领域知识。
- Add an executable equipment-loan semantic exercise: text + DDL, explicit review, graph maintenance and independent Agent consumption. / 新增可直接运行的设备借用建模练习。
- Publish bilingual human-review pages and reader instructions; show real graph screenshots and an input-to-answer example. / 交付阅读页及调用说明双语化，展示真实图谱及完整案例。
- Fix graph double-click editing after selection redraw and improve English node labels. / 修复选中重绘影响双击编辑，改善英文节点换行。
- Do not treat different asset kinds (such as a business object and its physical table) as mergeable duplicate identities; same-kind conflicts still require review. / 不把不同类型的同名对象误判为可合并身份；保留同类型冲突检查。
- Pre-1.0 projects and formats remain incompatible by default. / 1.0 前仍不承诺旧项目与格式兼容。

## 0.2.3-dev — 2026-11-09

- 修复分项适用范围在界面编辑时被转成字符串的问题，按分项维护并保留嵌套值和类型；修正上下文末页仍提示继续取页的诊断。
- 规则条件、要求、指标口径、业务范围及明确待补问题可检索，CLI返回命中字段；图谱搜索同步覆盖。
- 新增独立 Agent 的 describe/context 入口，一次返回必需依赖、业务范围、出处、缺口和只读能力；业务关系与定义引用分开。
- 当前请求与整包完整性分开，身份冲突返回触发词与具体候选；明确业务未知、日期适用和分页，不默认补齐。
- 来源登记范围随证据保留；建模与交付说明明确保留原文范围及禁止条件，共享范围规则参与子图依赖闭合。
- 新增可维护的业务待补问题；不增加数据库连接、HTTP/MCP服务或动作执行器。

## 0.2.2-dev — 2026-11-09

- 图谱自动布局改为基于关系拓扑和画布比例选择分层或紧凑布局，减少交叉；完整保留业务关系与去重后的定义引用。
- 新增正交避障、关系标签换行和碰撞避让，标签不压节点；专注模式充分使用屏幕，详情可收起。
- 手动拖动后重新布线，首次拖动或固定时保存整幅布局；自动布局可撤销，失败保留原坐标，异步计算不会写入已切换的视图。
- 本地随包提供固定版本 ELK 及其许可证，无运行时 CDN 或外网依赖。

## 0.2.1-dev — 2026-11-09

- 修复指标提升截取部分条件、未知字段或枚举仍输出可合并操作的问题；不支持的完整表达式明确阻断。
- 修复金标准缺失期望仍写入、只读结构检查意外创建数据库的问题。
- 修复源码 mock 目录越界和链接路径风险；通用服务重建与进程管理迁入 maintainer，可执行 mocks 同时移出安装包。
- 明确 live 评测发送对象和下游边界，拒绝在线/离线混用及歧义引擎 URL；补齐能力声明并固定运行依赖。
- 修复画像输出覆盖源数据库和指标公式来源表冲突仍可合并的问题。
- 新增展开画布、适应画布和相关连线突出显示；扩大默认节点间距，改善关系箭头落点。
- 1.0 前不保留旧 scripts/rebuild.py 和 scripts/_process.py 调用路径。

## 0.2.0-dev — 2026-11-09

- 新增知识材料、候选核对、语义图谱、交付与调用、项目历史主线；原数值工具保留为可选入口。
- 新增统一语义资产、稳定身份、逐项原文依据、来源内容修订及独立提取记录；支持文本、DDL、CSV/XLSX、DOCX、文本 PDF、JSON/YAML 材料。
- 新增宿主任务与候选 CLI；候选经操作者核对后整组写入，支持增量融合、拒绝重放、来源变更复核、合并与分离、停用和安全撤回。
- 新增图谱拖动、业务连线、详情编辑、搜索与邻域、表格视图；布局与语义分别保存。
- 新增固定语义 ZIP、依赖闭合、草稿缺口、人审页，以及无需原项目的只读 Agent 查询与来源接口。
- 修复本机服务被浏览器空闲连接阻塞、附件下载不稳定、旧依赖候选覆盖人工修正，以及来源原文未删但新增例外未触发复核的问题。
- 提交操作使用持久回执；浏览器恢复时先查询结果，不因回执丢失自动重复提交。
- 1.0 前不承诺旧项目、旧模型或命令兼容；`start --ddl/--model` 现在登记材料与候选，不直接生成已确认图谱。

本版不内置大模型、OCR、实时实例图或通用 SQL/规则执行器。语义确认与原有数值执行准备分别维护。
