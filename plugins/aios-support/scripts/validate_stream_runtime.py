#!/usr/bin/env python3
"""Fail closed before the Stream service opens a connection."""

from __future__ import annotations

import os
from pathlib import Path

from robot_gateway import GatewayError, load_policy, select_version
from stream_gateway import TEMPLATE_ID, load_credentials


def validate() -> None:
    if os.environ.get("AIOS_CARD_TEMPLATE_ID") != TEMPLATE_ID:
        raise GatewayError("template_id_invalid")
    max_seconds = int(os.environ.get("AIOS_STREAM_MAX_SECONDS", "1200"))
    if not 120 <= max_seconds <= 1800:
        raise GatewayError("max_runtime_invalid")
    policy = load_policy(Path(os.environ["AIOS_GATEWAY_POLICY"]))
    versions = Path(os.environ["AIOS_VERSION_SETS_FILE"])
    select_version("", policy["default_version"], versions)
    load_credentials(Path(os.environ["AIOS_DINGTALK_CREDENTIALS"]))
    codex = Path(os.environ["AIOS_CODEX_BIN"])
    if not codex.is_file() or not os.access(codex, os.X_OK):
        raise GatewayError("runtime_invalid")


def main() -> int:
    try:
        validate()
    except (GatewayError, KeyError, OSError):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
