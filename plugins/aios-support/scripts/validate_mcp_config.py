#!/usr/bin/env python3
"""Strictly validate the checked-in MCP server and read-only tool policy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


COMMON_FIELDS = {
    "type",
    "url",
    "enabled",
    "default_tools_approval_mode",
    "enabled_tools",
    "disabled_tools",
}

EXPECTED = {
    "zstack-bbs-support": {
        "url": "http://172.18.250.27:8768/mcp",
        "extra_fields": {"http_headers", "env_http_headers"},
        "http_headers": {"Accept": "application/json, text/event-stream"},
        "env_http_headers": {"Authorization": "ZSTACK_BBS_AUTHORIZATION"},
        "enabled_tools": {"bbs_search", "bbs_get_thread", "bbs_latest", "bbs_get_forum"},
        "disabled_tools": {"bbs_create_thread"},
    },
    "zstack_atlassian_shared": {
        "url": "http://172.18.250.27:3340/mcp",
        "extra_fields": {"http_headers", "env_http_headers"},
        "http_headers": {"Accept": "application/json, text/event-stream"},
        "env_http_headers": {"Authorization": "ATLASSIAN_AUTHORIZATION"},
        "enabled_tools": {
            "jira_search",
            "jira_get_issue",
            "jira_get_project_versions",
            "jira_search_fields",
            "confluence_search",
            "confluence_get_page",
            "confluence_get_page_children",
            "confluence_get_space_page_tree",
        },
        "disabled_tools": {
            "confluence_add_comment",
            "confluence_add_label",
            "confluence_create_page",
            "confluence_delete_attachment",
            "confluence_delete_page",
            "confluence_download_attachment",
            "confluence_download_content_attachments",
            "confluence_get_page_images",
            "confluence_move_page",
            "confluence_reply_to_comment",
            "confluence_update_page",
            "confluence_upload_attachment",
            "confluence_upload_attachments",
            "jira_add_comment",
            "jira_add_issues_to_sprint",
            "jira_add_watcher",
            "jira_add_worklog",
            "jira_batch_create_issues",
            "jira_batch_create_versions",
            "jira_create_issue",
            "jira_create_issue_link",
            "jira_create_remote_issue_link",
            "jira_create_sprint",
            "jira_create_version",
            "jira_delete_issue",
            "jira_download_attachments",
            "jira_edit_comment",
            "jira_get_issue_images",
            "jira_link_to_epic",
            "jira_remove_issue_link",
            "jira_remove_watcher",
            "jira_transition_issue",
            "jira_update_issue",
            "jira_update_proforma_form_answers",
            "jira_update_sprint",
        },
    },
    "tavily_hikari": {
        "url": "https://tavily.zopen1.com/mcp",
        "extra_fields": {"bearer_token_env_var"},
        "bearer_token_env_var": "TAVILY_HIKARI_TOKEN",
        "enabled_tools": {"tavily_search"},
        "disabled_tools": {"tavily_crawl", "tavily_extract", "tavily_map", "tavily_research"},
    },
}

WRITE_WORDS = {
    "add",
    "assign",
    "comment",
    "create",
    "delete",
    "download",
    "edit",
    "merge",
    "move",
    "push",
    "reply",
    "transition",
    "update",
    "upload",
    "write",
}


def validate(config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(config, dict):
        return ["mcp_config_shape_invalid"]
    if set(config) != {"mcpServers"} or not isinstance(config.get("mcpServers"), dict):
        return ["mcp_config_shape_invalid"]

    servers = config["mcpServers"]
    if set(servers) != set(EXPECTED):
        errors.append("mcp_server_set_mismatch")

    for name, expected in EXPECTED.items():
        server = servers.get(name)
        if not isinstance(server, dict):
            errors.append(f"{name}:missing_or_invalid")
            continue

        allowed_fields = COMMON_FIELDS | expected["extra_fields"]
        if set(server) != allowed_fields:
            errors.append(f"{name}:field_set_mismatch")
        if server.get("type") != "streamable_http":
            errors.append(f"{name}:transport_invalid")
        if server.get("url") != expected["url"]:
            errors.append(f"{name}:url_mismatch")
        if not isinstance(server.get("enabled"), bool):
            errors.append(f"{name}:enabled_invalid")
        if server.get("default_tools_approval_mode") != "writes":
            errors.append(f"{name}:approval_mode_invalid")

        for field in ("http_headers", "env_http_headers", "bearer_token_env_var"):
            if field in expected and server.get(field) != expected[field]:
                errors.append(f"{name}:{field}_mismatch")

        enabled = server.get("enabled_tools")
        disabled = server.get("disabled_tools")
        if not isinstance(enabled, list) or any(not isinstance(tool, str) for tool in enabled):
            errors.append(f"{name}:enabled_tools_invalid")
            enabled_set: set[str] = set()
        else:
            enabled_set = set(enabled)
            if len(enabled) != len(enabled_set):
                errors.append(f"{name}:enabled_tools_invalid")
            if enabled_set != expected["enabled_tools"]:
                errors.append(f"{name}:enabled_tools_mismatch")
        if not isinstance(disabled, list) or any(not isinstance(tool, str) for tool in disabled):
            errors.append(f"{name}:disabled_tools_invalid")
            disabled_set: set[str] = set()
        else:
            disabled_set = set(disabled)
            if len(disabled) != len(disabled_set):
                errors.append(f"{name}:disabled_tools_invalid")
            if disabled_set != expected["disabled_tools"]:
                errors.append(f"{name}:disabled_tools_mismatch")
        if enabled_set & disabled_set:
            errors.append(f"{name}:tool_policy_overlap")
        for tool in enabled_set:
            if set(tool.lower().split("_")) & WRITE_WORDS:
                errors.append(f"{name}:write_semantic_enabled")

        static_headers = server.get("http_headers", {})
        if not isinstance(static_headers, dict):
            errors.append(f"{name}:http_headers_invalid")
        elif any(isinstance(key, str) and key.lower() == "authorization" for key in static_headers):
            errors.append(f"{name}:static_authorization_forbidden")

    serialized = json.dumps(config, ensure_ascii=False)
    if "${" in serialized or "Basic " in serialized or "Bearer " in serialized:
        errors.append("literal_or_interpolated_secret_forbidden")
    return sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        errors = validate(config)
    except (OSError, json.JSONDecodeError) as error:
        errors = [f"config_unreadable:{type(error).__name__}"]
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
