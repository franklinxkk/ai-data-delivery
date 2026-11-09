# AI Data Delivery · v0.3.0

**把表结构、业务文档和制度中的知识，变成一张你能审、能改、Agent 能用的统一语义图谱。**

[English](README.md) · [直接试用](#直接跑通一份样例) · [工作台说明](workbench/README.zh-CN.md) · [Agent 调用](references/semantic-package.md)

表名解释不了“可借”到底指什么，不同文档可能使用不同统计范围，Agent 还需要知道定义来自哪里、缺少什么。这个工具把业务对象、术语、关系、指标、规则和数据映射放在同一张图里：先对照原文核对，再可视化维护，最后交付带范围、依赖、依据和缺口的语义包。

![真实中文工作台：设备借用的业务定义、规则和数据映射](https://raw.githubusercontent.com/franklinxkk/ai-data-delivery/main/docs/images/equipment-zh.png)

*随包合成样例的真实工作台截图。实线箭头表示关系，虚线表示定义引用；这是语义模型，不是生产库存看板。*

## 一份材料最后能带来什么

| 输入 | 核对后形成的图谱 | 独立 Agent 能提供的服务 |
| --- | --- | --- |
| equipment 表的 id、lab_id、state、disabled 字段 | 设备、实验室、归属关系和数据映射 | 找到业务对象及其对应表结构 |
| “仅实验室 L，在库且未停用，按设备编号去重” | 适用范围规则、可借规则、可借设备数指标 | 按原文解释范围和统计口径 |
| “未提供库存记录和借用执行接口” | 随上下文返回的明确缺口 | 说明还缺什么，不编造台数、不擅自办理借用 |

把包交给另一个 Agent，问：**“能借其他实验室的设备吗？现在能借几台？”**

这份样例支持的回答是：“其他实验室不在本包范围内。实验室 L 的设备需在库且未停用才符合条件；当前可借台数还需要库存记录，语义定义本身也不提供办理权限或执行接口。”这是对虚构材料的预期解释，不是真实机构的业务结论。

## 直接跑通一份样例

需要 **Python 3.10+**。获取仓库后运行：

```bash
git clone https://github.com/franklinxkk/ai-data-delivery.git
cd ai-data-delivery
python -m pip install -r requirements.txt
python -X utf8 scripts/start.py --project "./work/equipment-zh" --example equipment --language zh
```

若已取得干净 `.skill`／ZIP 安装包，解压后进入其中的 `ai-data-delivery` 目录，执行最后两条命令即可。`.skill` 是 ZIP 格式；安装到宿主 Agent 时，把完整目录放入该宿主支持的 skills 位置。

打开终端打印的本机网址：

1. 点击 **先核对表结构**，展开候选并对照 DDL 原文，点击 **接纳整组**。
2. 回到 **知识材料**，点击 **准备练习业务候选**；核对范围、规则与映射后，**接纳整组**。
3. 打开 **语义图谱**，切换 **全部知识**，点击 **展开画布、自动布局**。双击节点修改别名，**保存并确认**，刷新检查结果。
4. 进入 **交付与调用**，**发布确认快照、下载语义包**。
5. 关闭原工作台，把 ZIP 和读取器交给另一个 Agent，或自行运行：

```bash
python -X utf8 scripts/semantic_read.py --package "./delivery/equipment.zip" verify
python -X utf8 scripts/semantic_read.py --package "./delivery/equipment.zip" search --query "可借设备"
python -X utf8 scripts/semantic_read.py --package "./delivery/equipment.zip" context --id demo.available --intent query
python -X utf8 scripts/semantic_read.py --package "./delivery/equipment.zip" sources --id demo.available
```

把路径替换为实际下载文件。上下文应包含实验室 L 范围、可借规则、数据映射、原文依据，以及缺少库存数据和执行连接器的提示。包完整不等于可以执行问数。

样例包含文本、DDL 和**预先编写的候选**，不用 AI 密钥即可体验完整流程；它不是通用文本抽取器，确认仍由你完成。重开时使用同一 `--project`，**去掉 `--example`**；初始化不会覆盖已有项目。

要体验英文材料，在新目录用 `--example equipment --language en`。右上角可切换 English／简体中文；切换只改界面，不改领域知识或原文。切换前先保存或清除未保存输入并关闭弹窗，避免丢失编辑。

## 换成你自己的知识

```bash
python -X utf8 scripts/start.py --project "./work/my-domain" --language zh
```

粘贴或上传材料，点击 **准备 Agent 任务**，把指令交给当前宿主 Agent。Agent 理解材料并提交带出处的候选，你核对后才写入已确认图谱；也可以手工新建知识。

> 使用 ai-data-delivery，根据【资料路径】为【领域】建立语义图谱，项目保存在【目录】。保留原文依据和适用范围，指出同名异义及尚未明确的问题，先提交候选供我核对；确认后导出可供独立 Agent 使用的语义包。

| 材料 | 当前能力 |
| --- | --- |
| 粘贴原文、TXT、Markdown | 保留原文及行、章节位置 |
| SQLite/MySQL DDL | 读取支持的表、字段、主外键；不执行 SQL |
| CSV、XLSX | 工作表、表头、单元格及选定读取区域；不重算公式 |
| DOCX、有文本层的 PDF | 可读取段落、表格或页文本；明确提示提取限制，不做 OCR |
| JSON、YAML | 安全解析；受支持的语义模型形成待核对候选 |

每份最多 **32 MB**；未知语法、扫描页、缺公式缓存等不会补造内容。物理外键不推断业务所有权。完整限制和恢复方法见[工作台说明](workbench/README.zh-CN.md)。

## 可以维护和交付什么

- **统一图谱：**对象、术语、属性、关系、指标、规则、数据集、字段和映射使用稳定 ID。
- **可核对的变化：**并排比较定义、候选和原文，保留接纳／拒绝／暂缓、来源修订及身份分离判断。
- **可视化维护：**图表切换、名称与规则检索、邻域展开、拖拽、自动布局、固定节点与布局撤销；复杂图仍可按范围筛选。
- **面向 Agent 的上下文：**检索消歧、必需依赖、原文依据、明确缺口、分页及子图导出，不依赖原项目或运行中的工作台。
- **本机运行：**项目 SQLite 与浏览器资源都在本地；没有运行时 CDN、内置大模型、模型密钥或自动上传文档。

语义 ZIP 包含 `model.json`、`sources.json`、`manifest.json`、双语 `human-review.html` 和读取说明，不含原始附件与私人项目库。模型及引文仍可能含业务信息，按实际接收范围交付。

## 边界与验证

语义理解由宿主 Agent 提供。本工具不是 OWL/SHACL 推理器、生产问数网关、企业权限系统或动作执行器。规则定义不等于规则已执行。原有数值工具保留在 **数值与明细核对**，`--demo` 是独立的数值练习。

本版实际验证范围和结果见 [v0.3.0 验收记录](references/v0.3.0-validation.md)。历史报告仅适用于标注版本；平台审查另行进行，本说明不宣称已经取得新版 ClawHub／SkillHub 通过结果。

**1.0 前不承诺旧项目和格式兼容。** 保留旧目录和备份，本版用新项目开始。

[MIT](LICENSE) · [安全边界](SECURITY.zh-CN.md) · [更新记录](CHANGELOG.md) · [候选 API 合同](references/m1-m2-contract.md)
