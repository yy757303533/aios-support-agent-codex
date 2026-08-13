---
name: aios-version-resolver
description: 将 AIOS 产品版本或开发分支确定性解析成 aios、zstack、premium、zstack-utility、zstack-ui-next 五仓库的不可变 commit 上下文。用于所有依赖版本的问答和源码查证。
---

# AIOS 版本解析

版本解析必须由脚本完成，禁止根据分支命名习惯自行拼接结果。

## 配置

运行时读取：

```text
AIOS_CODE_MIRROR_ROOT       五仓库 bare mirror 根目录
AIOS_VERSION_SETS_FILE      正式版本和常用开发版本配置
AIOS_REPOSITORY_MAP_FILE    可选；默认使用插件 config/repository-map.json
```

## 产品版本

```bash
python3 scripts/resolve_code_context.py \
  --version 5.5.28 \
  --mirror-root "$AIOS_CODE_MIRROR_ROOT" \
  --repository-map config/repository-map.json \
  --version-sets "$AIOS_VERSION_SETS_FILE"
```

正式版本的五个 commit 必须全部冻结。缺少 commit 时状态为 `release_commit_unpinned`，不得用分支当前 tip 补齐。

## 开发分支

```bash
python3 scripts/resolve_code_context.py \
  --branch feature-5.5.30-aios \
  --mirror-root "$AIOS_CODE_MIRROR_ROOT" \
  --repository-map config/repository-map.json
```

开发分支解析规则：

- `aios` 使用配置的固定 `master`。
- 其他仓库使用用户指定的分支。
- 某仓库不存在目标分支时返回 `branch_missing`。
- 不得回退到 `master`、`main` 或相似名称。

## 结果使用

- `complete=true`：可以进行完整代码查证。
- `complete=false`：可以查询已解析仓库，但结论必须列出 `missing` 并降低可信度。
- 本次问答始终使用返回的 commit；不得在问答中再次解析移动分支。
