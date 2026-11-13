# 四类业务语义练习

The four synthetic exercises cover traffic, agriculture, universities and finance. Use the runnable maintainer command below with a new output directory; relative paths with spaces or Chinese characters are supported. Context criteria, independent question-package consumption, summary/full consistency and source-change rechecks are included. Fixture calculations and operator records are synthetic validation, not live Agent queries or customer sign-off. [English workflow](../../references/question-delivery.md).

回归同时检查上下文预期、问题包的独立读取、摘要与完整内容一致性，以及来源更新后的待复验和旧包不变。合成操作者记录只验证保存与变化处理，参考计算不是生产 Agent 问数或客户验收。

先选一个问题，把已有材料交给宿主 Agent；核对候选定义后，再用问题检查和交付包验证上下文。无需先绘制整张行业本体。这里的 JSON 是可复现的维护者夹具，不是要求业务人员填写的表单。

全部材料、记录和规则均为**合成练习**，不代表真实客户制度、农业技术建议或金融监管口径。每个文件把来源段落、候选模型、独立问题预期和小样本观察数据放在一起；只有实际导入后，工具才绑定来源修订、提取与段落身份。候选不会自行确认。

| 练习 | 从什么问题开始 | 需要保留的区别 |
| --- | --- | --- |
| [交通](traffic.json) | 两来源同号行程能合并吗？隐患关闭是否风险归零？ | 人、车、企、线路、场地、隐患与风险；来源复合身份；历史任职；站序；职责与物理引用 |
| [农业](agriculture.json) | 混采再拆批还能追到哪块地？ | 地块边界版本与种植季；批次多来源贡献；调拨不新增产量；未给阈值或混合比例不能猜 |
| [高校信息化](university.json) | 研究生兼任教师算几个人？重修算几人次？ | 自然人与多角色；课程与开课实例；学期；选课记录；历史院系归属与成绩权限 |
| [金融](finance.json) | 合同连上多项担保后，余额为何翻倍？ | 主体与账户、合同、担保；按合同去重；币种与基准日；汇率缺失；余额不直接等于风险敞口 |

每域 8 个问题，分别验证定义和依赖、反例、未决含义、需要实际执行及问题发现。`expected_*` 是提前编写的测试预期，不是事实来源，也不是用户已签署验收。`source_paragraph` 只是夹具绑定标记，不进入正式语义资产。

在源码仓库中运行：

```bash
python -X utf8 maintainer/check_cross_domain.py --out ./work/cross-domain-check
```

输出目录必须为空。程序建立四个隔离项目，经导入、候选、明确的 synthetic-test-operator 核对、问题检查、快照发布，再启动独立 CLI 仅读取 ZIP。四个 `<domain>-semantic.zip` 可给另一个 Agent 盲读；传递问题即可，不应同时泄漏预期答案。程序不会连接客户数据库或调用模型。

小样本反例由维护者 Python 计算，并与独立固定预期比较：同号行程去重、任职交接日、采收与调拨重复累计、多角色与重修计数、担保连接翻倍及错误的 `SUM(DISTINCT amount)`。这些数值**不是语义读取器算出的业务答案**；实际业务仍需授权数据与执行环境。

交通观察集故意含租户 B 的一条反例：全夹具有 3 个来源行程，租户 A 只有 2 个。模型的范围过滤不会替消费者过滤业务记录，也不替代权限校验。农业“批次怎么追溯”期望同时发现“产品批次”与“批次追溯”；词法发现仍不证明理解整个问题，选择规则后还需检查闭合的依赖上下文。

这套练习检验可表达性、上下文保留和边界提示，不证明自动抽取质量、自然语言理解准确率、真实数据库兼容、行业正确性或新用户上手时间。
