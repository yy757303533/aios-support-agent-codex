# AIOS Support

## 技能

| 技能 | 用途 |
|---|---|
| `aios-support-qa` | 销售与内部问答统一入口 |
| `aios-version-resolver` | 产品版本/开发分支解析为五仓库 commit |
| `aios-source-verification` | bare mirror 只读源码查询 |
| `aios-knowledge-verification` | 钉钉 AIOS 知识库查证 |
| `aios-event-analysis` | 日志归属、对应版本代码反查与多来源故障分析 |
| `aios-connectivity-check` | 安装和数据源验收 |
| `aios-redaction-review` | internal/sales/customer 发送前脱敏门禁 |

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

所有连接器查询文本先通过 `scripts/sanitize_query.py`，所有机器人答案在发送前通过 `scripts/validate_answer.py`。插件安装测试会执行严格 MCP 策略和秘密扫描。

售后日志先通过内置日志与代码地图定位 MN、Host、VM、Container、Model Center 或 Storage 层，再在目标版本 CodeContext 中反查错误生成点、logger 调用点和直接调用方。源码无命中或日志来源不明时保留 `unknown`，不得猜测归属。

## 发布状态

当前仓库是本地开发/验证插件，不是可直接上线的钉钉生产网关。CLI 门禁属于纵深防御，不能替代服务端身份和发送出口。生产机器人必须先完成服务端受众/RBAC 绑定、钉钉回调验签和防重放、唯一 fail-closed 发送适配器、TLS 或 mTLS 内部连接器、运行时 `tools/list` 校验、限流和审计；任一项缺失即禁止接入真实客户材料或自动发送答案。

## 创建 bare mirror

```bash
mkdir -p "$AIOS_CODE_MIRROR_ROOT"
git clone --mirror <aios-url> "$AIOS_CODE_MIRROR_ROOT/aios.git"
git clone --mirror <zstack-url> "$AIOS_CODE_MIRROR_ROOT/zstack.git"
git clone --mirror <premium-url> "$AIOS_CODE_MIRROR_ROOT/premium.git"
git clone --mirror <zstack-utility-url> "$AIOS_CODE_MIRROR_ROOT/zstack-utility.git"
git clone --mirror <zstack-ui-next-url> "$AIOS_CODE_MIRROR_ROOT/zstack-ui-next.git"
```

定时更新使用 `git --git-dir=<mirror> fetch --prune`。问答期间不执行 fetch，保证本次 CodeContext 不移动。源码查询必须使用 resolver 生成的完整 CodeContext 文件，不能直接指定任意 commit。

## 版本配置

复制 `config/version-sets.example.json` 到运行数据目录，补齐正式发布版本的真实 commit。示例文件故意包含空 commit，校验会失败，避免误把示例当作正式快照。
