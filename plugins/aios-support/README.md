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

所有连接器查询文本先通过 `scripts/sanitize_query.py`。`scripts/validate_answer.py` 保留给未来的销售或客户输出场景；当前内部售后机器人不执行结构化答案门禁。插件安装测试会执行严格 MCP 策略和秘密扫描。

机器人必须通过 `scripts/robot_gateway.py` 作为唯一 Agent 命令运行。网关从 root-only 策略文件读取固定的 `internal` 受众，输入先脱敏，并用只读 sandbox 运行 Codex。内部群问答直接返回纯文本或 Markdown；模型调用失败时明确返回运行错误，不使用安全降级文案。不得把 DWS 直接连接到裸 `codex` 渠道。

workspace 的 `zdev` 必须由 `scripts/configure_runtime.py mcp` 改造成禁用的 `zdev_upstream` 与启用的 `zdev_readonly`。只读代理只暴露 Jira 和 Confluence 查询工具，不暴露任何 GitLab 代码读取或搜索工具；源码始终查询开发机本地五仓或 bare mirror。评论、修改 Issue、提交和 push 均不可见且伪造调用会被拒绝。`aios_refresh_code_mirrors` 是唯一批准的本地写操作，只能对 `config/repository-map.json` 中登记的 bare mirror 执行 `git fetch --prune origin`，不 checkout、不 commit、不 push，并且不得配置定时执行。

售后日志先通过内置日志与代码地图定位 MN、Host、VM、Container、Model Center 或 Storage 层，再在目标版本 CodeContext 中反查错误生成点、logger 调用点和直接调用方。源码无命中或日志来源不明时保留 `unknown`，不得猜测归属。

钉钉知识使用人工双阶段发布：`scripts/sync_knowledge.py prepare` 生成已脱敏的 `pending_review` 候选，审核后用 `publish --confirm-reviewed` 发布不可变 release 并原子切换 `current`。禁止定时同步，禁止提交知识正文到 Git，禁止从未审核候选回答。

```bash
python3 scripts/sync_knowledge.py prepare \
  --sources config/knowledge-sources.json \
  --candidate-root /var/lib/aios-support/knowledge-candidates

python3 scripts/sync_knowledge.py publish \
  --candidate /var/lib/aios-support/knowledge-candidates/<snapshot-id> \
  --destination /var/lib/aios-support/knowledge \
  --confirm-reviewed \
  --reviewed-by <reviewer>
```

机器人只挂载 `/var/lib/aios-support/knowledge/current`。发布前必须人工检查候选 manifest、脱敏统计和切片内容；需要更新发布资料时重新执行上述流程。

## 发布状态

内部售后机器人只在企业内部应用和内部群中使用，不维护人员白名单，受众固定为 `internal`。Codex 可以免交互执行代理暴露的查询和受控 mirror 更新，但不得暴露裸 `zdev` 或任意工作区写权限。BBS 没有 HTTPS 地址，当前按固定内网 HTTP 端点的只读风险例外运行；不得扩大到外部客户，也不得增加发帖或修改工具。

## 创建 bare mirror

```bash
mkdir -p "$AIOS_CODE_MIRROR_ROOT"
git clone --mirror <aios-url> "$AIOS_CODE_MIRROR_ROOT/aios.git"
git clone --mirror <zstack-url> "$AIOS_CODE_MIRROR_ROOT/zstack.git"
git clone --mirror <premium-url> "$AIOS_CODE_MIRROR_ROOT/premium.git"
git clone --mirror <zstack-utility-url> "$AIOS_CODE_MIRROR_ROOT/zstack-utility.git"
git clone --mirror <zstack-ui-next-url> "$AIOS_CODE_MIRROR_ROOT/zstack-ui-next.git"
```

代码镜像只允许人工更新。问答期间不执行 fetch，保证本次 CodeContext 不移动。源码查询必须使用 resolver 生成的完整 CodeContext 文件，不能直接指定任意 commit。

## 版本配置

`config/release-refs*.json` 声明人工批准的发布分支映射。每次版本发布并人工同步本地代码后，使用 `scripts/freeze_version_set.py` 从五个 bare mirror 将对应 ref 冻结为 40 位 commit，并合并写入 root-only 的正式运行清单；随后必须同时通过 `validate_version_sets.py` 和 `resolve_code_context.py --version`。分支继续移动不会改变已冻结清单，更新发布基线必须重新人工执行冻结流程。
