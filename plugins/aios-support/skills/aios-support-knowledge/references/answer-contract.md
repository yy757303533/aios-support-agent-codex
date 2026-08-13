# 回答契约

Agent 先形成以下结构，再渲染为钉钉 Markdown：

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

`status` 只能是：

- `answered`
- `needs_version`
- `needs_more_context`
- `conflicting_evidence`
- `insufficient_evidence`
- `source_unavailable`
- `permission_denied`
- `handoff_required`

## Sales 输出

展示结论、适用版本、必要建议、查证完整性和允许公开的资料链接。隐藏内部端点、Jira/BBS 内部细节、完整 commit、代码路径、客户标识和原始日志。

## Internal 输出

可以展示仓库、commit、代码路径、Jira/BBS/Confluence 直达链接和证据边界，但仍不得输出凭证、个人信息、未脱敏附件或完整内部正文。

任何结论都不得把 `uncertainties` 静默丢弃。
