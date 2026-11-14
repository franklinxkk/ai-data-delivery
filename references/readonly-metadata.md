# Read-only catalogs → reviewed semantics / 只读元数据到语义发布

[English quickstart](../README.md) · [中文快速开始](../README.zh-CN.md)

## Try SQLite without another server

From the installed skill directory, create a **new** synthetic directory outside the installation, then open a project:

```bash
python -X utf8 examples/readonly-metadata/create_example.py --out "../metadata-demo"
python -X utf8 scripts/start.py --project "../metadata-project" --language en
```

In **Database connections**, name the connection, select SQLite, paste the absolute `plants.sqlite` path printed above, and enter `plant` and `care` on separate lines. Save, reopen the page, then **Scan structure**. Review the table, column and physical-FK candidates in **Review changes**. Nothing is confirmed at connection or scan time.

Create a **Business question**, search for `moisture`, explicitly select the intended field, and select that field under **Question acceptance → Context must include**. Save. This first exercise checks declared structure only; it supplies no threshold or plant-care recommendation. Real questions should reference reviewed business definitions that depend on the selected fields, with independently supplied examples where needed.

After recording those dependencies, an external database administrator can change the example. For this **synthetic database only**, this command adds a column; the connector itself never executes it:

```bash
python -c "import sqlite3,sys; d=sqlite3.connect(sys.argv[1]); d.execute('ALTER TABLE plant ADD COLUMN humidity REAL'); d.commit(); d.close()" "../metadata-demo/plants.sqlite"
```

Scan again. Inspect **Before / After** and the affected-question paths; accept revised candidates, run **Regress affected questions**, then publish or use the question's handoff. If examples were configured, check and record their actual results again: old observations become stale. Download the semantic ZIP or Neo4j CSV/Cypher ZIP. A successful context check does not validate a business answer.

## 中文：无服务依赖的最短练习

在安装目录运行上方两条命令，`--language zh` 切换中文。样例目录必须是安装目录之外的新目录；不会覆盖旧库。在“数据库连接”选择 SQLite，填写命令输出的绝对路径，选表每行填写 `plant`、`care`。保存后重开，再“读取结构变化”，到“待核对”接纳表、字段与物理外键候选。

在“业务问题”检索 `moisture`，明确选择该字段，并在“问题验收→上下文必须包含”勾选它、保存。这只是结构练习，没有给出养护阈值或建议。真实任务应先核对业务定义与物理字段的依赖，并配置独立样例。仅针对这个新建的合成库，可执行上方 `ALTER TABLE` 演练命令；连接器本身不执行它。

再次扫描，查看变化前后与问题影响路径，核对候选、回归问题后发布。配置过人工样例时，旧记录会变成待复验；重新检查并记录真实结果后才能发布。下载语义包或 Neo4j 导入包。上下文通过不等于业务答案正确。

## PostgreSQL and MySQL / PostgreSQL 与 MySQL

SQLite uses Python's built-in driver. Install optional server drivers only when needed:

```bash
python -m pip install -r requirements-connectors.txt
```

Use an administrator-provisioned read-only account with visibility on the explicitly selected base tables. PostgreSQL needs database CONNECT, schema USAGE and table SELECT; MySQL needs table SELECT. The connector issues only fixed catalog queries inside read-only transactions, despite that account's ability to read table rows. It does not accept user SQL, DSNs, connection options or business-row queries. Views and virtual tables are rejected. PostgreSQL partitioned base tables are supported as declared catalog objects; partition data is not read. MySQL uses two matching catalog captures because its catalog is not a transactional DDL snapshot. An absent table can mean lost visibility; it is never automatically deleted.

A PostgreSQL profile (`connection.json`) can be:

```json
{"name":"Operations catalog","engine":"postgresql","host":"db.example.internal","port":5432,"database":"operations","schema":"public","user":"metadata_reader","password_env":"METADATA_DB_PASSWORD","tables":["equipment","loan"],"auto_indexes":false}
```

For MySQL use `"engine":"mysql"`, port `3306`, and the **same database/schema value**. Remote endpoints require certificate and hostname verification; optional `tls_ca` is an absolute trusted CA file. Plaintext is limited to literal localhost/loopback endpoints resolving entirely to loopback. DNS is resolved by the database driver; this is not the HTTP adapter's pinned-IP transport. Do not treat this connector as a network sandbox.

Set the named secret in the **same host environment before launching** `start.py` or `knowledge.py`. The profile stores the environment variable's name only. Do not put secrets in command arguments, chat, JSON or browser fields. For example, PowerShell can prompt without putting a literal password in history:

```powershell
$credential = Get-Credential -UserName metadata_reader
$env:METADATA_DB_PASSWORD = $credential.GetNetworkCredential().Password
python -X utf8 scripts/start.py --project "../metadata-project" --language en
```

SQLite 无额外驱动。PostgreSQL/MySQL 按需安装 `requirements-connectors.txt`，使用管理员配置的所选表只读账号；不要求给写权限。PostgreSQL 需要 CONNECT、USAGE、SELECT，MySQL 需要所选表 SELECT。工具只在只读事务中执行固定目录查询，不开放自定义 SQL、DSN、任意连接参数或业务查询。远端强制校验证书与主机名，可用 `tls_ca` 指定 CA。只有严格本机端点允许明文。数据库驱动自行处理 DNS，不声称具备 HTTP 适配器的固定 IP 传输能力。

密码通过启动宿主前设置的环境变量读取；页面、配置、操作回执、语义包均不保存连接密码。项目及备份包含主机、用户名、路径与环境变量名。目录注释、默认值、约束定义本身也可能敏感；发布前核对范围。修改端点、选表或账号须新建连接，原身份保留；第一版不提供后台 CDC、自动发现全部表或定时扫描。

## Shared review and release rules / 统一核对与发布规则

| Change / 变化 | Result / 处理 |
| --- | --- |
| Identical observations / 无变化 | No new revision or proposals / 不重复生成修订与候选 |
| Nonunique-index-only change, policy explicitly enabled, generated physical definitions unchanged / 已授权、仅非唯一索引变化且人工未改动采集定义 | Synchronize physical index metadata only; still invalidate affected observations and require applicable question regression / 仅自动同步物理索引，仍使相关记录待复验并要求回归 |
| New/missing table or column, rename, type/default/nullability/comment/collation/generated mode, PK/FK/unique/check constraint / 表字段增减、改名、类型、默认值、可空性、注释、排序规则、生成方式、键及约束变化 | Explicit candidate review; never infer business meaning or a renamed identity / 人工核对，不推断业务含义或自动同名换绑 |
| Read failure or selected table initially invisible / 读取失败或首扫不可见 | Keep baseline and graph unchanged; fix endpoint/permissions/selection, retry / 保留基线和图谱，修复后重试 |
| Table disappears after initial scan / 后续表不可见 | Manual missing-or-hidden candidates; absence does not prove deletion / 生成缺失或不可见候选，不自动断言已删除 |
| Rejected/stale candidates / 拒绝或过时的候选 | No silent revival. Explicit **Refresh unresolved candidates** takes new evidence and preserves historical disposition / 不自动复活；用户明确重新生成时按新观察提出候选，保留历史处置 |

The canonical graph stays in the project. Connection IDs plus exact table/column coordinates determine physical identities. Keep them separate; use mappings/dependencies for business meaning instead of merging physical IDs. New scan proposals carry unresolved tables forward, so a later change cannot lose earlier unreviewed work. Question influence uses explicit dependency paths; missing mappings mean **no known linked questions**, not “no business impact”. No undeclared business dependency is invented.

Review, regression and confirmed publication re-read the selected catalog. A different fingerprint blocks the operation and asks for a scan. Publication requires resolved relevant candidate groups, publishable definitions and current passing results for every saved question affected by included dirty definitions. Regression checks explicit required definitions/gaps plus current operator example records. Unconfigured expectations, stale/failed examples, missing/retired dependencies or identity conflicts block it. No linked question is reported as `not_applicable`, never a fabricated pass; a reviewed metadata-only graph can still be published. Unrelated publication scopes do not clear pending changes elsewhere. Issued packages remain immutable; offline freshness stays unknown.

规范图谱仍存于项目，连接身份＋准确表字段坐标决定物理身份，业务映射必须显式建立。新扫描保留未核对表的候选。影响仅沿已登记依赖查找；“没有关联问题”不代表业务上没有影响。核对、回归和确认发布时重新读取目录；结构再次变化则阻断并提示先扫描。发布重检相关候选、语义完整性及受影响问题当前回归结果。未配置预期、过时/失败记录、缺失/停用依赖或身份冲突不会通过。无关联问题明确为“不适用”，允许已核对的纯元数据图谱发布；无关范围发布不清除其他待办。离线包保持原样，不能自动感知最新状态。

## Host commands / 宿主命令

Use actual returned IDs and receipts. Mutations have the existing revision/operation-ID contract; after an uncertain response, read the receipt before repeating.

```bash
python -X utf8 scripts/knowledge.py --project "../metadata-project" connect --file "../metadata-demo/connection.json"
python -X utf8 scripts/knowledge.py --project "../metadata-project" scan --connection CONNECTION_ID
python -X utf8 scripts/knowledge.py --project "../metadata-project" scan --connection CONNECTION_ID --refresh-review
python -X utf8 scripts/knowledge.py --project "../metadata-project" regress --connection CONNECTION_ID
python -X utf8 scripts/neo4j_export.py --package "../delivery/semantic.zip" --out "../delivery/neo4j.zip"
```

Do not run `--refresh-review` automatically after rejection. Follow user review through the existing candidate page/API. Boundaries: at most 200 exact table names, 2,000 columns per table and 8 MB normalized catalog data per capture; capture/query limits fail explicitly rather than returning partial success. Narrow large selections. Tested engine versions and evidence are in the [release validation](v0.3.2-release-validation.md).

Neo4j remains optional: the new CSV/Cypher export imports snapshot-scoped assets, directed relationships, dependencies and evidence; complete original JSON is retained. See its generated bilingual README for server import settings. It is separate from [OGS design projection](neo4j-interop.md), does not upload automatically and is not a business-query or authorization service.
