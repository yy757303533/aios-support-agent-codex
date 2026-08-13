---
name: aios-connectivity-check
description: 只读检查 AIOS Support 插件的 bare mirrors、版本配置、BBS、Jira/Confluence、Tavily 和钉钉知识库可用性。用于安装后验收和连接器故障定位。
---

# AIOS Support 连通检查

按层报告状态，不得仅凭环境变量存在就写“已连接”。

## 本地代码层

1. `AIOS_CODE_MIRROR_ROOT` 已设置且目录可读。
2. 五个 bare mirror 均存在。
3. `AIOS_VERSION_SETS_FILE` 可读取并通过 `validate_version_sets.py`。
4. 选取一个 moving context 执行版本解析烟测。
5. 对一个已解析 commit 执行只读 `grep`。

## 连接器层

对 BBS、Atlassian 和 Tavily 分别报告：显式禁用、未配置、已配置但工具未注入、工具可见、结构化查询成功或查询未完成。只调用批准的只读工具。`enabled=false` 是不可用连接器的安全降级，不是配置校验失败。

连接器检查前先运行 `validate_mcp_config.py`。当前会话暴露任何非白名单工具时停止烟测并报告安全校验失败；不得为了完成烟测调用 BBS 发帖或其他写工具。

钉钉知识库报告：认证状态、目标空间可见性、AIOS 目录可见性和单文档读取烟测。不得在检查中创建或修改文档。

## 输出

逐项列出成功、失败和建议动作。连接器失败不代表“没有相关资料”。
