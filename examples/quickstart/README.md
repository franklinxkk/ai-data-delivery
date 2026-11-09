# Equipment loans / 设备借用

These are fictional, authored materials for learning the semantic workflow. They are not real operating policies or inventory data. / 本目录是学习流程用的合成材料，不是真实制度或库存数据。

```bash
python -X utf8 scripts/start.py --project "./work/equipment-en" --example equipment --language en
python -X utf8 scripts/start.py --project "./work/equipment-zh" --example equipment --language zh
```

Run one command from the skill root, using a new project directory. Review the DDL candidates first. Return to Materials and prepare the authored business proposals, then review them. Open All knowledge in the graph, edit and save, publish and download the semantic package. Full steps: [English](../../README.md#try-it-with-included-materials) / [中文](../../README.zh-CN.md#直接跑通一份样例).

在 skill 根目录执行其中一条命令。先核对 DDL 候选，再回到材料页准备预先编写的业务候选，核对后进入图谱“全部知识”，编辑保存并发布。重开时去掉 `--example`；程序拒绝覆盖已有项目。变更了练习原文后，由宿主按新材料提出候选，程序不会套用旧的固定候选。

The exercise has two materials, five physical assets and seven business/mapping assets after explicit review. Both languages use stable IDs `demo.scope`, `demo.lab`, `demo.equipment`, `demo.belongs`, `demo.mapping`, `demo.eligible`, `demo.available`. DDL asset IDs are derived from the actual imported source identity, not copied from another project.

独立调用应保留实验室 L 范围、在库且未停用条件、编号去重口径和出处，并指出缺库存记录、借用权限及执行接口；不能回答虚构的当前台数或声称已办理借用。English users should reach the same conclusions from the English material. Switching interface language does not rewrite either material.
