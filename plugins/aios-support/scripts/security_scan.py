#!/usr/bin/env python3
"""Scan a plugin tree for forbidden artifacts and likely committed secrets."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from security_common import secret_rule_names


SKIP_DIRECTORIES = {".git", "__pycache__", ".pytest_cache"}
FORBIDDEN_SUFFIXES = {".docx", ".pdf", ".xlsx", ".xls", ".csv", ".har", ".pcap", ".dump", ".zip", ".rar", ".pem", ".key"}
def scan(root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for directory, names, files in os.walk(root):
        for name in tuple(names):
            path = Path(directory) / name
            if path.is_symlink():
                relative = str(path.relative_to(root))
                safe_relative = "<redacted-name>" if secret_rule_names(relative) else relative
                findings.append({"file": safe_relative, "rule": "symlink_forbidden"})
                names.remove(name)
        names[:] = [name for name in names if name not in SKIP_DIRECTORIES]
        for filename in files:
            path = Path(directory) / filename
            relative = str(path.relative_to(root))
            filename_rules = secret_rule_names(relative)
            safe_relative = "<redacted-name>" if filename_rules else relative
            if filename_rules:
                findings.append({"file": safe_relative, "rule": "secret_in_filename"})
            if path.is_symlink():
                findings.append({"file": safe_relative, "rule": "symlink_forbidden"})
                continue
            if filename == ".env" or (filename.startswith(".env.") and filename != ".env.example"):
                findings.append({"file": safe_relative, "rule": "environment_file_forbidden"})
                continue
            if path.suffix.lower() in FORBIDDEN_SUFFIXES:
                findings.append({"file": safe_relative, "rule": "artifact_type_forbidden"})
                continue
            try:
                if path.stat().st_size > 2_000_000:
                    findings.append({"file": safe_relative, "rule": "large_unreviewed_file"})
                    continue
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                findings.append({"file": safe_relative, "rule": "unreadable_file"})
                continue
            for rule in secret_rule_names(text):
                findings.append({"file": safe_relative, "rule": rule})
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    findings = scan(args.root.resolve())
    print(json.dumps({"safe": not findings, "findings": findings}, ensure_ascii=False, indent=2))
    return 0 if not findings else 2


if __name__ == "__main__":
    raise SystemExit(main())
