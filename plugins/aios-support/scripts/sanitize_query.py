#!/usr/bin/env python3
"""Remove common identifiers from a connector query read from standard input."""

from __future__ import annotations

import json
import sys

from security_common import (
    ANY_IPV4_PATTERN,
    DOMAIN_PATTERN,
    EMAIL_PATTERN,
    HEX_ID_PATTERN,
    IPV6_PATTERN,
    LABELED_IDENTIFIER_PATTERN,
    MAC_PATTERN,
    UUID_PATTERN,
    URL_HOST_PATTERN,
    secret_rule_names,
)


MAX_QUERY_CHARS = 32_000
REDACTIONS = (
    (EMAIL_PATTERN, "<email>", "email"),
    (UUID_PATTERN, "<uuid>", "uuid"),
    (MAC_PATTERN, "<mac>", "mac"),
    (ANY_IPV4_PATTERN, "<ip>", "ip_address"),
    (IPV6_PATTERN, "<ip>", "ip_address_v6"),
    (HEX_ID_PATTERN, "<id>", "opaque_id"),
    (LABELED_IDENTIFIER_PATTERN, "<identifier>", "labeled_identifier"),
    (DOMAIN_PATTERN, "<domain>", "domain"),
    (URL_HOST_PATTERN, "https://<domain>", "url_host"),
)


def sanitize(text: str) -> dict:
    if len(text) > MAX_QUERY_CHARS:
        return {"safe": False, "error": "query_too_large"}
    if secret_rule_names(text):
        return {"safe": False, "error": "credential_material_detected"}

    sanitized = text
    counts: dict[str, int] = {}
    for pattern, replacement, label in REDACTIONS:
        sanitized, count = pattern.subn(replacement, sanitized)
        if count:
            counts[label] = count
    return {"safe": True, "sanitized": sanitized.strip(), "redactions": counts}


def main() -> int:
    result = sanitize(sys.stdin.read(MAX_QUERY_CHARS + 1))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["safe"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
