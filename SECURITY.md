# 安全声明 / Security Policy

本 Skill 面向 FDE 工程师、数据产品经理与信息中心人员，在**用户自己的项目环境**中执行本体建模与验证。
我们理解平台安全扫描（如 VirusTotal Code Insight、ClawScan）会对某些代码模式（网络请求、子进程执行）给出风险提示，
因此在此完整、明确地声明本 Skill 的全部能力边界，供用户与审查者核对。
SKILL.md frontmatter 中的 `capabilities` 段是本清单的机器可读版本。

## 能力清单（本 Skill 会做什么）

| 能力 | 范围 | 说明 |
| --- | --- | --- |
| 文件读/写 | 仅限用户通过命令行参数显式指定的路径（如 `--model semantic.yaml`、`--db physical.db`、`--out dir/`） | 不扫描、不递归读取用户未指定的目录（唯一例外：`rebuild.py` 为做产物新鲜度校验，在用户指定的 `--project-dir` 内遍历源码文件 mtime，只读时间戳不读内容） |
| 网络访问 | 仅限用户通过 `--endpoint` / `--health-url` 显式指定的地址 | **端点守卫**：默认仅允许本机回环/内网地址，其他地址必须显式 `--allow-remote` 才放行（`_contract.guard_endpoint`）。没有任何硬编码的外部 URL，不向任何第三方服务器发送数据 |
| 子进程执行 | `rebuild.py` 执行用户显式传入的 `--build-cmd` / `--start-cmd`；门禁/演示脚本调用同仓库 Python 脚本 | **全部参数数组方式，无任何 shell 调用**（不含 `sh -c`）；命令完全由用户自己提供 |
| 环境变量 | 子进程仅继承**白名单环境**（`_contract.minimal_env`：PATH/SystemRoot/TEMP/HOME 等运行必需项 + PYTHONIOENCODING） | 不透传 CI token、云凭据等敏感变量 |
| SQL 执行 | 通过 SQLite/用户数据库连接执行**由语义模型编译出的只读单表聚合查询**（SELECT COUNT/SUM/AVG ... WHERE ...） | 不执行 INSERT/UPDATE/DELETE/DDL；`reconcile_paths.py` 的连接经 `readonly` 约束。注意：`extra_where` 的关键字黑名单是**模型可信前提下的过滤器**（防误注入子查询/多语句/ATTACH/load_extension/readfile 等），不是不可信用户 SQL 的沙箱 |

## 本 Skill 明确不做的事

- 不读取任何环境变量中的凭据、token、密钥
- 不访问 `~/.ssh`、`~/.aws`、`~/.config` 等敏感目录
- 不上传用户的模型文件、数据、SQL 或日志到任何远程服务器（端点守卫默认拦截非内网地址）
- 不包含混淆代码、编码隐藏载荷、安装钩子、动态代码执行（无 eval/exec/importlib 动态加载）或持久化机制
- 不修改自身代码、不自我复制

## 威胁模型

本 Skill 的威胁模型是：**脚本被用户在知情的情况下、在自己的项目环境里、对着自己有权测试的服务端点运行**。
所有副作用（写文件、发请求、起进程）都源自用户显式传入的参数，脚本本身没有任何自主的隐蔽行为。
含业务敏感信息的提示词、SQL、推理链与报告，在对外分享前应由用户按接收方范围裁剪（SKILL.md 正文亦有此要求）。

## 已知误报模式说明

平台启发式扫描可能命中以下模式，均为上述正当用途：

1. `urllib.request.urlopen(endpoint)` —— 打用户指定的本机/内网验证端点（健康检查/问数 API 复现），有端点守卫
2. `subprocess`（参数数组）—— 执行用户自己提供的构建/启动命令（`rebuild.py`）或同仓库 Python 脚本（门禁/演示）
3. `os.walk` —— `rebuild.py` 的构建产物新鲜度校验（防止用旧包起服）

## 报告安全问题 / 申诉

- 发现真实安全问题：请通过 GitHub Issues 反馈（见 README 仓库链接），或直接联系维护者
- 认为平台风险标记为误报：欢迎向平台申诉渠道提交本文件作为依据；每次版本发布都会触发重新扫描

## 审计建议

本 Skill 全部代码为纯 Python + Markdown，无构建产物、无二进制。
建议审查顺序：`scripts/_contract.py`（SQL 编译、只读约束、端点守卫、环境白名单）→ `scripts/rebuild.py`（部署辅助，唯一的用户命令执行入口）→ 其余脚本均可独立阅读，每个文件头部有用途与安全声明。

---

**English summary**: ai-data-delivery runs entirely in the user's own project environment. File I/O is limited to user-specified paths; network access is limited to user-specified endpoints and guarded to loopback/private addresses unless `--allow-remote` is given; subprocesses use argv-only execution with a whitelist environment (no shell, no credential passthrough); SQL is read-only single-table aggregation compiled from the declared model. There are no hardcoded external URLs, no credential reads, no obfuscation, no dynamic code execution, and no persistence mechanisms. All side effects originate from explicit user-supplied arguments.
