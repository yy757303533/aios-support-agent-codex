#!/usr/bin/env python3
"""Validate a structured answer against a server-authorized audience."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from typing import Any
from urllib.parse import unquote, urlparse

from security_common import (
    ANY_IPV4_PATTERN,
    COMMIT_PATTERN,
    DOMAIN_PATTERN,
    EMAIL_PATTERN,
    HEX_ID_PATTERN,
    IPV6_PATTERN,
    LABELED_IDENTIFIER_PATTERN,
    MAC_PATTERN,
    UUID_PATTERN,
    secret_rule_names,
)


MAX_ANSWER_CHARS = 256_000
AUDIENCES = {"sales", "internal", "customer"}
STATUSES = {
    "answered",
    "needs_version",
    "needs_more_context",
    "conflicting_evidence",
    "insufficient_evidence",
    "source_unavailable",
    "permission_denied",
    "handoff_required",
}
FIELDS = {
    "status",
    "audience",
    "version",
    "conclusion",
    "actions",
    "uncertainties",
    "completeness",
    "sources",
    "internal_sources",
}
SALES_SOURCE_TYPES = {"official_product", "public_docs", "vendor_docs", "dingtalk_knowledge"}
CUSTOMER_SOURCE_TYPES = {"official_product", "public_docs", "vendor_docs"}
INTERNAL_SOURCE_TYPES = {"jira", "bbs", "confluence", "code", "dingtalk_knowledge", "official_product", "public_docs", "vendor_docs"}
INTERNAL_HOSTS = {
    "jira.zstack.io",
    "bbs.zstack.io",
    "confluence.zstack.io",
    "dev.zstack.io",
    "gitlab.zstack.io",
    "devops.zstack.io",
}
SOURCE_HOSTS = {
    "official_product": {"zstack.io", "www.zstack.io", "docs.zstack.io"},
    "dingtalk_knowledge": {"alidocs.dingtalk.com"},
    "public_docs": {"docs.zstack.io", "github.com", "kubernetes.io", "docs.python.org"},
    "vendor_docs": {"docs.nvidia.com", "docs.vllm.ai", "docs.docker.com", "openjdk.org"},
    "jira": {"jira.zstack.io"},
    "bbs": {"bbs.zstack.io"},
    "confluence": {"confluence.zstack.io"},
    "code": {"dev.zstack.io", "gitlab.zstack.io"},
}
INTERNAL_MARKERS = (
    re.compile(r"(?i)\b(?:ZSTAC|TIC|SUG|BUG)-\d+\b"),
    re.compile(r"(?i)\b(?:jira|bbs|confluence|dev|gitlab|devops)\.zstack\.io\b"),
    re.compile(r"(?i)(?:^|[\s`'\"])(?:/mnt/repos|/root/|/Users/)[^\s`'\"]*"),
    re.compile(r"(?i)\bcommit\s*[:@]?\s*[0-9a-f]{7,40}\b"),
    re.compile(r"(?i)\b(?:aios|zstack|premium|zstack-utility|zstack-ui-next)/[^\s`'\"]+"),
    COMMIT_PATTERN,
)
UNSAFE_MARKUP = re.compile(r"(?i)(?:javascript\s*:|data\s*:\s*text/html|<\s*[a-z!/])")
EXTERNAL_IDENTIFIER_PATTERNS = (
    ANY_IPV4_PATTERN,
    IPV6_PATTERN,
    EMAIL_PATTERN,
    UUID_PATTERN,
    MAC_PATTERN,
    HEX_ID_PATTERN,
    DOMAIN_PATTERN,
    LABELED_IDENTIFIER_PATTERN,
)
DESTRUCTIVE_ACTION = re.compile(
    r"(?i)\b(?:rm\s+-rf|delete|drop\s+(?:database|table)|truncate|reboot|shutdown|restart|"
    r"kill\s+-9|format|mkfs|清空|删除|重启|关机)\b"
)


def strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(strings(item))
        return result
    if isinstance(value, dict):
        result = []
        for item in value.values():
            result.extend(strings(item))
        return result
    return []


def validate_source(source: Any, audience: str, *, internal: bool = False) -> list[str]:
    if not isinstance(source, dict) or set(source) - {"type", "title", "url"}:
        return ["source_shape_invalid"]
    if not isinstance(source.get("type"), str) or not isinstance(source.get("title"), str):
        return ["source_required_fields_invalid"]
    source_type = source["type"]
    if internal and source_type not in INTERNAL_SOURCE_TYPES:
        return ["internal_source_type_invalid"]
    if audience == "sales" and source_type not in SALES_SOURCE_TYPES:
        return ["sales_source_type_forbidden"]
    if audience == "customer" and source_type not in CUSTOMER_SOURCE_TYPES:
        return ["customer_source_type_forbidden"]
    url = source.get("url")
    if audience in {"sales", "customer"} and not internal and not isinstance(url, str):
        return ["source_url_required"]
    if url is not None:
        if not isinstance(url, str):
            return ["source_url_invalid"]
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return ["source_url_invalid"]
        if parsed.username or parsed.password:
            return ["source_credentials_forbidden"]
        url_parameters = unquote(unquote("&".join(part for part in (parsed.query, parsed.fragment) if part)))
        if re.search(
            r"(?i)(?:^|&)(?:access[_-]?token|api[_-]?key|token|key|password|passwd|auth|authorization|"
            r"sig|signature|x-amz-credential|x-amz-signature)=",
            url_parameters,
        ):
            return ["source_credentials_forbidden"]
        decoded_url = unquote(url)
        if re.search(
            r"(?i)/(?:access[_-]?token|api[_-]?key|token|password|passwd|auth|authorization)/[^/?#\s]{8,}",
            decoded_url,
        ):
            return ["source_credentials_forbidden"]
        hostname = parsed.hostname.lower()
        approved_hosts = SOURCE_HOSTS.get(source_type)
        if approved_hosts is not None and hostname not in approved_hosts:
            return ["source_host_not_approved"]
        if audience != "internal" and approved_hosts is None and (hostname in INTERNAL_HOSTS or hostname.endswith(".zstack.io")):
            return ["internal_source_url_forbidden"]
        if audience == "customer" and parsed.scheme != "https":
            return ["customer_source_must_use_https"]
        if audience == "customer" and parsed.hostname == "alidocs.dingtalk.com":
            return ["customer_dingtalk_url_forbidden"]
    return []


def validate(answer: Any, authorized_audience: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(answer, dict):
        return ["answer_shape_invalid"]
    if set(answer) != FIELDS:
        errors.append("answer_field_set_mismatch")
    if answer.get("audience") != authorized_audience:
        errors.append("audience_not_authorized")
    if answer.get("status") not in STATUSES:
        errors.append("status_invalid")
    if answer.get("completeness") not in {"complete", "partial", "unknown"}:
        errors.append("completeness_invalid")
    if answer.get("version") is not None and not isinstance(answer.get("version"), str):
        errors.append("version_invalid")
    if not isinstance(answer.get("conclusion"), str):
        errors.append("conclusion_invalid")
    for field in ("actions", "uncertainties", "sources", "internal_sources"):
        if not isinstance(answer.get(field), list):
            errors.append(f"{field}_invalid")
    for field in ("actions", "uncertainties"):
        value = answer.get(field)
        if isinstance(value, list) and any(not isinstance(item, str) for item in value):
            errors.append(f"{field}_item_invalid")

    all_text = "\n".join(strings(answer))
    if secret_rule_names(all_text):
        errors.append("secret_material_forbidden")
    decoded_text = all_text
    for _ in range(4):
        decoded_text = html.unescape(unquote(decoded_text))
    if UNSAFE_MARKUP.search(decoded_text):
        errors.append("unsafe_markup_forbidden")

    if authorized_audience in {"sales", "customer"}:
        if answer.get("internal_sources"):
            errors.append("internal_sources_forbidden")
        external_text = "\n".join(
            strings(answer.get("version"))
            + strings(answer.get("conclusion"))
            + strings(answer.get("actions"))
            + strings(answer.get("uncertainties"))
            + [source.get("title", "") for source in answer.get("sources", []) if isinstance(source, dict)]
        )
        if any(pattern.search(external_text) for pattern in EXTERNAL_IDENTIFIER_PATTERNS):
            errors.append("external_identifier_forbidden")
        if any(DESTRUCTIVE_ACTION.search(item) for item in answer.get("actions", []) if isinstance(item, str)):
            errors.append("destructive_action_forbidden")
        for marker in INTERNAL_MARKERS:
            if marker.search(all_text):
                errors.append("internal_marker_forbidden")

    sources = answer.get("sources", [])
    if isinstance(sources, list):
        for source in sources:
            errors.extend(validate_source(source, authorized_audience))
    internal_sources = answer.get("internal_sources", [])
    if isinstance(internal_sources, list):
        for source in internal_sources:
            errors.extend(validate_source(source, authorized_audience, internal=True))

    if answer.get("status") == "answered" and answer.get("completeness") == "complete" and not sources:
        errors.append("complete_answer_requires_source")

    return sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorized-audience", choices=sorted(AUDIENCES), required=True)
    args = parser.parse_args()
    raw = sys.stdin.read(MAX_ANSWER_CHARS + 1)
    if len(raw) > MAX_ANSWER_CHARS:
        errors = ["answer_too_large"]
    else:
        try:
            errors = validate(json.loads(raw), args.authorized_audience)
        except json.JSONDecodeError:
            errors = ["answer_json_invalid"]
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
