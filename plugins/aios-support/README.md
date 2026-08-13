# AIOS Support

## 技能

| 技能 | 用途 |
|---|---|
| `aios-support-qa` | 销售与内部问答统一入口 |
| `aios-version-resolver` | 产品版本/开发分支解析为五仓库 commit |
| `aios-source-verification` | bare mirror 只读源码查询 |
| `aios-knowledge-verification` | 钉钉 AIOS 知识库查证 |
| `aios-event-analysis` | 多来源故障分析 |
| `aios-connectivity-check` | 安装和数据源验收 |

## 必要环境变量

```text
AIOS_CODE_MIRROR_ROOT
AIOS_VERSION_SETS_FILE
```

可选连接器变量：

```text
ZSTACK_BBS_AUTHORIZATION
ATLASSIAN_AUTHORIZATION
TAVILY_HIKARI_TOKEN
```

不要将任何变量值写入仓库、聊天、截图或工单。

## 创建 bare mirror

```bash
mkdir -p "$AIOS_CODE_MIRROR_ROOT"
git clone --mirror <aios-url> "$AIOS_CODE_MIRROR_ROOT/aios.git"
git clone --mirror <zstack-url> "$AIOS_CODE_MIRROR_ROOT/zstack.git"
git clone --mirror <premium-url> "$AIOS_CODE_MIRROR_ROOT/premium.git"
git clone --mirror <zstack-utility-url> "$AIOS_CODE_MIRROR_ROOT/zstack-utility.git"
git clone --mirror <zstack-ui-next-url> "$AIOS_CODE_MIRROR_ROOT/zstack-ui-next.git"
```

定时更新使用 `git --git-dir=<mirror> fetch --prune`。问答期间不执行 fetch，保证本次 CodeContext 不移动。

## 版本配置

复制 `config/version-sets.example.json` 到运行数据目录，补齐正式发布版本的真实 commit。示例文件故意包含空 commit，校验会失败，避免误把示例当作正式快照。
