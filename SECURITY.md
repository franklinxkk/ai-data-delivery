# 安全声明 / Security Policy

本 Skill 面向 FDE 工程师、数据产品经理与信息中心人员，在**用户自己的项目环境**中执行本体建模与验证。
我们理解平台安全扫描（如 VirusTotal Code Insight）会对某些代码模式（网络请求、子进程执行）给出风险提示，
因此在此完整、明确地声明本 Skill 的全部能力边界，供用户与审查者核对。

## 能力清单（本 Skill 会做什么）

| 能力 | 范围 | 说明 |
| --- | --- | --- |
| 文件读/写 | 仅限用户通过命令行参数显式指定的路径（如 `--model semantic.yaml`、`--db physical.db`、`--out dir/`） | 不扫描、不递归读取用户未指定的目录（唯一例外：`rebuild.py` 为做产物新鲜度校验，在用户指定的 `--project-dir` 内遍历源码文件 mtime，只读时间戳不读内容） |
| 网络访问 | 仅限用户通过 `--endpoint` / `--health-url` 显式指定的地址 | 预期为本地或内网的验证/就绪端点（`http://localhost:*`、`http://127.0.0.1:*` 或用户内网地址）。**没有任何硬编码的外部 URL，不向任何第三方服务器发送数据** |
| 子进程执行 | `rebuild.py` 执行用户显式传入的 `--build-cmd` / `--start-cmd`（shell=False，参数数组方式，无 shell 注入面） | 该脚本的用途是"停旧服→构建→起服→就绪校验"的本地部署辅助，命令完全由用户自己提供 |
| SQL 执行 | 通过 SQLite/用户数据库连接执行**由语义模型编译出的只读单表聚合查询**（SELECT COUNT/SUM/AVG ... WHERE ...） | 不执行 INSERT/UPDATE/DELETE/DDL；`reconcile_paths.py` 的连接经 `readonly` 约束 |

## 本 Skill 明确不做的事

- 不读取任何环境变量中的凭据、token、密钥（唯一涉及 `os.environ` 的地方是 `release_gate.py` 把当前环境原样透传给用户主动运行的回归子进程，并附加 `PYTHONIOENCODING=utf-8`）
- 不访问 `~/.ssh`、`~/.aws`、`~/.config` 等敏感目录
- 不上传用户的模型文件、数据、SQL 或日志到任何远程服务器
- 不包含混淆代码、编码隐藏载荷、安装钩子或持久化机制
- 不修改自身代码、不自我复制

## 威胁模型

本 Skill 的威胁模型是：**脚本被用户在知情的情况下、在自己的项目环境里、对着自己的服务端点运行**。
所有副作用（写文件、发请求、起进程）都源自用户显式传入的参数，脚本本身没有任何自主的隐蔽行为。

## 已知误报模式说明

平台启发式扫描可能命中以下模式，均为上述正当用途：

1. `urllib.request.urlopen(endpoint)` —— 打用户指定的本地验证端点（健康检查/问数 API 复现）
2. `subprocess` —— 执行用户自己提供的构建/启动命令（`rebuild.py`）或进程内调用同仓库模块（`export_exchange.py` 已改为纯 import 调用）
3. `os.walk` —— `rebuild.py` 的构建产物新鲜度校验（防止用旧包起服）

## 报告安全问题 / 申诉

- 发现真实安全问题：请通过 GitHub Issues 反馈（见 README 仓库链接），或直接联系维护者
- 认为平台风险标记为误报：欢迎向平台申诉渠道提交本文件作为依据；每次版本发布都会触发重新扫描

## 审计建议

本 Skill 全部代码为纯 Python + Markdown，无构建产物、无二进制。
建议审查顺序：`scripts/_contract.py`（SQL 编译与只读约束）→ `scripts/rebuild.py`（唯一的子进程入口）→ 其余脚本均可独立阅读，每个文件头部有用途与安全声明。
