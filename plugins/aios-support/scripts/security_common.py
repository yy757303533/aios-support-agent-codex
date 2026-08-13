"""Shared redaction primitives. Functions never return matched secret values."""

from __future__ import annotations

import re


SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    "authorization_value": re.compile(
        r"(?i)\bAuthorization\s*[:=]\s*[\"']?(?:Basic|Bearer)\s+[A-Za-z0-9+/._=-]{12,}"
    ),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\b(?:ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "credential_assignment": re.compile(
        r"(?i)(?<![A-Za-z0-9])(?:[A-Za-z0-9]+[_-])*[A-Za-z0-9]*"
        r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret(?:[_-]?key)?|password|passwd|"
        r"client[_-]?secret|license[_-]?key)\s*[:=]\s*[\"']?[^\s\"']{12,}"
    ),
    "credential_url_parameter": re.compile(
        r"(?i)(?:[?&#]|%3[fF]|%26)(?:access[_-]?token|api[_-]?key|token|password|passwd|auth|authorization)"
        r"(?:=|%3[dD])[^&#\s]{8,}"
    ),
    "credential_url_userinfo": re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/@:]+:[^\s/@]{8,}@"),
    "authorization_token": re.compile(r"(?i)\bAuthorization\s*[:=]\s*[\"']?Token\s+[A-Za-z0-9+/._=-]{12,}"),
    "signed_url_credential": re.compile(
        r"(?i)(?:[?&#]|%3[fF]|%26)(?:sig|signature|x-amz-credential|x-amz-signature)(?:=|%3[dD])[^&#\s]{8,}"
    ),
}

IPV4_PATTERN = re.compile(
    r"(?<![\d.])(?:10(?:\.\d{1,3}){3}|127(?:\.\d{1,3}){3}|169\.254(?:\.\d{1,3}){2}|"
    r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}|192\.168(?:\.\d{1,3}){2})(?![\d.])"
)
ANY_IPV4_PATTERN = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
IPV6_PATTERN = re.compile(
    r"(?i)(?<![0-9a-f:])(?:"
    r"(?:[0-9a-f]{1,4}:){7}[0-9a-f]{1,4}|"
    r"(?:[0-9a-f]{1,4}:){1,7}:|"
    r"(?:[0-9a-f]{1,4}:){1,6}:[0-9a-f]{1,4}|"
    r"(?:[0-9a-f]{1,4}:){1,4}(?::[0-9a-f]{1,4}){1,3}|"
    r"(?:[0-9a-f]{1,4}:){1,3}(?::[0-9a-f]{1,4}){1,4}|"
    r"(?:[0-9a-f]{1,4}:){1,2}(?::[0-9a-f]{1,4}){1,5}|"
    r"[0-9a-f]{1,4}:(?:(?::[0-9a-f]{1,4}){1,6})|"
    r":(?:(?::[0-9a-f]{1,4}){1,7}|:)"
    r")(?![0-9a-f:])"
)
UUID_PATTERN = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
HEX_ID_PATTERN = re.compile(r"\b[0-9a-fA-F]{32}\b")
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
MAC_PATTERN = re.compile(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b")
COMMIT_PATTERN = re.compile(r"\b[0-9a-f]{40}\b")
DOMAIN_PATTERN = re.compile(
    r"(?<![@\w.-])(?:[A-Za-z0-9-]+\.)+(?:com|cn|net|org|io|local|internal|cloud|tech|xyz|top)(?![\w.-])"
)
URL_HOST_PATTERN = re.compile(r"(?i)\bhttps?://[^\s/?#]+")
LABELED_IDENTIFIER_PATTERN = re.compile(
    r"(?i)\b(?:customer|tenant|project|host(?:name)?|node|serial|sn|license)\s*[:=]?\s*"
    r"[A-Za-z0-9][A-Za-z0-9._-]{2,}"
)


def secret_rule_names(text: str) -> list[str]:
    return [name for name, pattern in SECRET_PATTERNS.items() if pattern.search(text)]
