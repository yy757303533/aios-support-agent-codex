# AIOS Support Agent Codex

面向 AIOS 销售与技术支持场景的只读、版本感知 Codex 插件。

当前第一版提供：

- AIOS 问答和事件分析工作流
- 五仓库产品版本/开发分支解析
- bare mirror 上按 commit 查询源码
- BBS、Jira、Confluence 和外部资料只读连接器
- 钉钉 AIOS 知识库查证规范
- sales/internal 受众隔离和安全策略

## 仓库布局

```text
.agents/plugins/marketplace.json
plugins/aios-support/
```

## 安装

```bash
codex plugin marketplace add "$(pwd)"
codex plugin add aios-support@aios-support-marketplace
```

安装或升级后新开 Codex 任务，使技能和 MCP 工具重新注入。

## 开发机目录

推荐：

```text
/mnt/repos/zstack-workspace/aios-support-agent-codex
/mnt/repos/zstack-workspace/.aios-support-data/git
/mnt/repos/zstack-workspace/.aios-support-data/config/version-sets.json
```

运行时数据与凭证不提交到本仓库。

## 验证

```bash
bash scripts/test-plugin.sh
```

详细配置见 [插件 README](plugins/aios-support/README.md) 和 [连接器说明](plugins/aios-support/CONNECTORS.md)。
