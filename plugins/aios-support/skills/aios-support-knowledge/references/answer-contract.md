# 回答契约

Agent 必须先形成以下精确结构，再由服务端门禁验证并渲染：

```json
{
  "status": "answered",
  "audience": "sales",
  "version": "5.5.28",
  "conclusion": "...",
  "actions": [],
  "uncertainties": [],
  "completeness": "complete",
  "sources": [],
  "internal_sources": []
}
```

不允许增加任意字段承载原始 MCP 结果、日志或调试信息。

`status` 只能是：

- `answered`
- `needs_version`
- `needs_more_context`
- `conflicting_evidence`
- `insufficient_evidence`
- `source_unavailable`
- `permission_denied`
- `handoff_required`

`completeness` 只能是 `complete`、`partial` 或 `unknown`。

## 来源对象

公开来源使用：

```json
{"type": "official_product", "title": "...", "url": "https://..."}
```

sales 只允许 `official_product`、`public_docs`、`vendor_docs`、`dingtalk_knowledge`；customer 不允许钉钉和任何内部来源。internal 可以在 `internal_sources` 中保留 Jira/BBS/Confluence/代码证据。

## 强制验证

服务端基于用户和群权限确定受众，然后执行。以下 CLI 仅是验证器接口，不能让 Agent 或用户自行提供授权值：

```bash
python3 scripts/validate_answer.py --authorized-audience sales < answer.json
```

该验证合同用于销售或客户输出。当前仅供企业内部群使用的机器人直接返回纯文本或 Markdown，不调用此验证器；若未来扩大受众，必须重新启用结构化验证并绑定服务端授权。
