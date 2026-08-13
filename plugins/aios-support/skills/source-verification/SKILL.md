---
name: aios-source-verification
description: 对 AIOS 五个本地 bare mirror 进行只读、commit 绑定的源码查证。用于类名、API、错误文本、配置键、页面入口、调用链、提交历史和版本差异问题。
---

# AIOS 源码查证

源码查证前必须获得 `aios-version-resolver` 生成的 CodeContext。不得直接使用工作目录当前分支。

## 仓库路由

- `aios`：应用、推理引擎、Model Center 辅助服务和部署资产。
- `zstack`：核心 API、资源编排和后端业务逻辑。
- `premium`：商业 AI 功能和高级后端能力。
- `zstack-utility`：主机 Agent、脚本和系统侧执行逻辑。
- `zstack-ui-next`：页面、菜单、权限条件和前端交互。

## 查询

将 resolver 输出保存为只读 CodeContext 文件，再使用 `scripts/query_code.py`；查询脚本从上下文读取 commit，不接受调用者另传主 commit：

```bash
python3 scripts/query_code.py \
  --mirror-root "$AIOS_CODE_MIRROR_ROOT" \
  --repository-map config/repository-map.json \
  --repository zstack \
  --context-file <resolved-context.json> \
  --version-sets "$AIOS_VERSION_SETS_FILE" \
  grep --pattern ModelService
```

正式发布上下文必须传 `--version-sets`，查询脚本会复核五仓库集合以及每个 ref/commit 与受控版本映射完全一致。开发分支上下文会复核当前未更新 mirror 的 ref tip；问答期间不得 fetch。

支持 `grep`、`show`、`log`、`diff`。命令通过参数数组调用 Git，不接受 shell 片段。

## 禁止操作

- 不运行 `checkout`、`switch`、`reset`、`pull`、`push`。
- 不修改 bare mirror 或业务仓库。
- 不从另一个版本的搜索结果补齐当前版本证据。
- 不把源码中存在的未发布功能表述为正式产品能力。

## 输出

内部输出记录仓库、ref、完整 commit、文件路径和符号。销售输出只展示必要的版本完整性，隐藏无价值的内部实现细节。
