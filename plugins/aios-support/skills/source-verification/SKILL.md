---
name: aios-source-verification
description: 对 AIOS 五个本地 bare mirror 进行只读、commit 绑定的源码查证。用于类名、API、错误文本、配置键、页面入口、调用链、提交历史和版本差异问题。
---

# AIOS 源码查证

源码查证前必须获得 `aios-version-resolver` 生成的 CodeContext。不得直接使用工作目录当前分支。

## 仓库路由

- `aios`：整个仓库都属于 AIOS 查询范围。
- `zstack`：只查询由 AIOS API、消息、资源类型或已命中调用方定位到的代码。
- `premium`：只查询 AI 模块、GuestTools 及其直接调用方。
- `zstack-utility`：只查询 GPU、GuestTools、Host Agent 中与 AIOS 直接相关的代码。
- `zstack-ui-next`：只查询 AI Store、模型、推理服务、GPU 等 AIOS 页面和请求代码。

禁止无条件扫描后四个仓库。先按问题定位仓库和模块，再用错误文本、类名、API 或配置键执行带路径的 `git grep`；只有命中代码的直接调用链跨模块时才能扩大一次范围。不得遍历构建产物、依赖、缓存、测试报告和无关产品目录。

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
