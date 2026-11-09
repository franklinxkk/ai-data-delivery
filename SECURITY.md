# 安全边界 / Security Policy · v0.2.1-dev

本工具在用户指定的本机项目中整理和验证语义，不是操作系统沙箱。SKILL.md 声明实际需要的文件、网络、子进程、环境和 SQL 能力；宿主和用户授权仍决定可执行范围。`allowed-tools: Read` 仅预声明读取，其他操作沿用已授权任务范围，不自动授予任意命令或网络权限。该字段是 Agent Skills 的实验能力，各宿主支持不同，不能当作强制隔离措施。

## 文件、数据库与工作台

- CLI 按输入/输出参数读写文件；材料里的命令、路径和链接不是用户授权。知识输入只解析，不执行 DDL 或文档中的命令。
- 工作台只监听 127.0.0.1，检查 Host、Origin 和会话令牌；这不是多人身份认证，也不防御同一系统账号下的恶意程序。
- 项目库保存语义、历史和原始附件。私人备份含附件；语义交付包不含原始附件，但模型及来源引用仍可能含业务信息，按用户指定的接收范围交付。
- YAML 使用安全加载器。快照检查使用共享只读连接、query_only 和 trusted_schema 防护；缺失数据库必须报错，不能创建空库并宣布检查通过。
- 可选数值工具使用有界只读编译器。旧指标提升工具只接受完整支持的 COUNT 与 AND 条件；遇到 OR、分组、函数、缺失字段或未映射枚举，保留问题并阻止进入可合并队列，不能截取局部表达式。
- 回归用例必须显式提供期望值或二维 rows；缺失不是 null，空 rows 和 0 不等于缺失。无效输入不能创建或覆盖已有金标准。
- 项目编辑与模拟数据生成会写本机数据库；业务快照只读不等于整个工具不写数据库。

## HTTP 请求

知识解析和离线读包不联网。可选 live 评测按显式目标逐条发送原始 question，主用例和多跳用例均在发送范围内。模型、快照和期望结果用于本地比对。使用前核对本次已授权的目标与问句范围；未知目标或范围不明时用离线入口。远端及本机引擎可能继续转发或记日志，不能把本工具的读取边界声称为下游保障。入口说明见 [Stage 6](references/story-map.md)。

共享传输实现 `scripts/_network.py`：

- 仅 HTTP(S)，拒绝 URL 凭据、控制字符、片段与 IPv6 scope；live 引擎基础 URL 也拒绝查询参数，避免路径拼接发错目标。
- 默认仅允许精确 localhost、回环和 RFC1918/ULA 私有 IP；其他域名或公网 IP 需 `--allow-remote`，且仍必须在用户任务授权范围内。
- 始终拒绝云元数据名单、链路本地、未指定、多播和不可路由地址；名单是阻断规则，不是探测目标。
- 检查全部 DNS 答案并固定 IP 连接，HTTPS 保留主机名及证书验证；不读取系统代理，不跟随重定向。
- 响应上限 4 MB，整体截止时间覆盖解析及慢速响应；明确失败、拒绝、未知或等待不能因数值碰巧相同判通过。

工作台消费者适配器范围更窄，只支持本机 IPv4 回环。上述策略不构成任意已授权服务的安全担保。

## 子进程、源码维护与依赖

安装包只含建模和验证所需入口。门禁与演示使用固定脚本、参数数组、shell=False 和最小子进程环境，不整包继承 CI/cloud/token 变量。PATH、用户目录等运行环境仍不构成隔离沙箱。

通用服务构建、启动、进程替换已经移到源码 `maintainer/rebuild.py` 和 `maintainer/_process.py`，不随 skill 分发，也不保留旧 scripts 路径入口。它们只供明确的源码维护任务使用；不是本体建模的一步。

可执行 `mocks/` 同样只留在源码维护树。其各入口只接受本仓库真实一级领域目录及已知脚本，拒绝绝对路径、路径穿越、符号链接、junction 和硬链接输出，避免执行或删除目录外文件。这些检查不抵御同账号恶意并发换文件。

运行依赖固定为 requirements.txt 中经过本次验证的版本。PyYAML 6.0.3 的发布信息可在 [PyPI](https://pypi.org/project/PyYAML/6.0.3/) 核对；固定版本便于复现，不代表今后永远没有漏洞。升级时重新评估与测试。

## 本次平台审计处置

本次核对的是 [ClawHub 公开报告](https://clawhub.ai/franklinxkk/skills/ai-data-delivery/security-audit)：被审版本 **0.1.2**，2026-11-09 07:48 UTC，显示 18 条发现、139/145 部件覆盖及部分分析降级，结论 Review / suspicious。

真实问题已按共同原因修复：指标条件丢失、未知字段仍可合并、缺失预期写入金标准、只读检查创建数据库、mock 路径越界；通用重建工具移出运行包，live 发送范围在使用处说明，依赖固定并补齐能力声明。元数据相关四条发现命中的是拒绝列表，保留防护，以拒绝地址、混合 DNS、地址编码和重定向反例核实。受控固定脚本的 subprocess 使用不等于命令注入，仍保留环境和参数边界。

这些是本地修复及测试结论，**尚未取得新版本的 ClawHub 复扫结果**，不能声称平台告警已撤销或完成生产安全认证。审查入口包括 `_network.py`、`run_eval.py`、`promote_draft.py`、`promote_gold.py`、`check_consistency.py`、工作台 service/serve 与源码 mock 测试。纯净安装包不携带测试、私人材料或本地审查记录。

安全问题可到[项目 Issues](https://github.com/franklinxkk/ai-data-delivery/issues)反馈，不要附真实密钥或未脱敏数据。

**English:** Local toolkit, not a sandbox. The installed skill excludes general service lifecycle and executable mock maintenance tools. Optional live evaluation sends authorized question text to an explicit destination; downstream behavior remains the target service's responsibility. Metadata addresses are denied. Strict metric promotion, explicit gold expectations and read-only snapshot inspection prevent silent integrity failures. Local verification is not a new ClawHub audit or production certification.
