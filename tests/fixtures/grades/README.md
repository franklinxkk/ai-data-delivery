# 分级测试装置（tests/fixtures/grades/）

验证工具链在**不成熟输入**面前是否说对话、指对路——不只测成品（L3），更测"从不全到全"的迁移路径。
四档取自两条正交轴的主对角线：**结构完备度**（模型侧）× **数据质量**（物理侧）。

| 档位 | 形态 | 期望工具反应 | 期望指引 |
| --- | --- | --- | --- |
| L0 不全 | 缺 grain/主键/边界说明，指标同义词与比率策略未补，第二张表未到货 | check_model 报 E01/E02 + W01/W11/W15/W17，门禁失败 | guide_model 补齐会话，先业务后物理 |
| L1 质量差 | 结构完整，数据注入 4 类脏数据（主键重复/枚举越界/负值/引用悬空） | check_model 全绿；check_constraints 精确报对应 4 条 fail | 逐条修数据，修复前阻塞 S3 交付 |
| L2 中等 | 结构与数据干净，语义薄（同义词 2 个/无除零策略/无展示刻度/无约束声明） | 0 ERROR + W11/W15/W17 警告组；constraints not_ready；指标可直算 | 语义加厚 + 补 constraints 段 |
| L3 完整 | 三轴齐备 | 全绿；约束全量快照 pass；指标直算与 gold 一致 | 本体评审 → S4 交付 → 供 AI 使用 |

## 覆盖领域

| 领域 | L3 来源 | 规制依据（caliber.basis 锚定的真实文件） |
| --- | --- | --- |
| edu_assess 高校审核评估 | mocks/edu_assess（手写四档） | 教发[2004]2 号、教发[2020]6 号、审核评估指标体系（2021-2025） |
| med_kpi 医院国考 | mocks/med_kpi | 国办发〔2019〕4 号三级公立医院绩效考核（55+1 指标中定量 50 个） |
| green_factory 绿色工厂 | mocks/green_factory | GB/T 36132-2025（五化、基准值/引领值双轨、官方公式） |
| elderly_care 养老机构 | mocks/elderly_care | GB/T 37276-2018 等级评定 + GB/T 42195-2022 能力评估 |
| diag_reform 高职诊改 | mocks/diag_reform | 教职成司函〔2015〕168 号诊改指导方案 + 职业院校数字基座高职数据标准 V3.0.3 |

正好覆盖四种最典型的规制形态：**部委考核**（教育/医疗）、**国标评价**（绿色工厂）、**等级评定**（养老）、**目标链诊改**（高职五横五纵）。

## 用法

```bash
python degrade.py                        # 由 mocks/ 重新生成四新域的 L0-L2（L3 复制）
python verify_grades.py                  # 验证全部领域全部档位（诊断 vs 金标准）
python verify_grades.py --grade L1       # 所有领域的 L1 档
python verify_grades.py --grade med_kpi/L1  # 指定领域指定档
```

每档目录 = 一个最小交付现场：`build_db.py`（确定性造数）+ `semantic.yaml` + `cases.json` + `expected_diagnostics.yaml`（**诊断金标准**：期望退出码、期望诊断码、约束 fail 集合、指标直算值、指引动作）。

断言语义：诊断码用**子集断言**（允许新规则加报，不因工具变强而误红）；L1 的 fail 规则用**精确集合断言**（四类脏数据必须各被对应规则抓到，一个不能多一个不能少）。

## 新增领域档位

1. 先在 `mocks/<domain>/` 把 L3 做成现役 mock（确定性造数 + 完整语义 + cases.json），跑通 `run_mock.py --domain <domain>`
2. 在 `degrade.py` 的 `DOMAINS` 登记该域（第二张表名、L1 脏数据注入 SQL、期望被抓的规则 id、reconcile 金值）
3. `python degrade.py` 生成四档 → `python verify_grades.py` 复审实际诊断 → 人工审定金标准

edu_assess 四档为手写（试点期），其余四域由 degrade.py 生成；两种来源等价，金标准纪律相同：**观测 → 人审 → 固化**。

注意：本目录故意不放进 `mocks/`（`run_mock.py --all` 会扫 mocks/ 下全部场景，而 L0-L2 的"失败"是预期行为）。
