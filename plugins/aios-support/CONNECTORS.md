# 连接器

## BBS

- 服务：`zstack-bbs-support`
- 认证：`ZSTACK_BBS_AUTHORIZATION`
- 权限：搜索和读取
- 禁止：`bbs_create_thread`

## Jira / Confluence

- 服务：`zstack_atlassian_shared`
- 认证：`ATLASSIAN_AUTHORIZATION`
- 权限：搜索、读取工单/版本/页面树
- 禁止：创建、更新、评论、流转、上传和附件下载

## Tavily

- 服务：`tavily_hikari`
- 认证：`TAVILY_HIKARI_TOKEN`
- 权限：仅 `tavily_search`
- 用途：查询第三方组件的一手官方资料

## 钉钉知识库

插件暂不在 `.mcp.json` 内固化个人钉钉凭证。开发验证可以使用已登录的 `dws` CLI，只读访问：

```text
ZStack终极知识库/ZStack AIOS 智塔
```

集中机器人上线前，应提供组织应用或服务账号连接器，并限制为目标空间只读。不得依赖个人桌面登录态作为长期服务认证。

## 本地源码

源码通过 `AIOS_CODE_MIRROR_ROOT` 下的五个 bare mirror 读取，不属于远端 MCP。脚本不提供 checkout、fetch、pull、push 或文件写入能力。
