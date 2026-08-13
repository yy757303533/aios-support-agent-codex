#!/usr/bin/env python3
"""Validate version-set structure without accessing Git repositories."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def validate(repository_map: dict, version_sets: dict) -> list[str]:
    errors: list[str] = []
    repository_names = set(repository_map.get("repositories", {}))
    if not repository_names:
        return ["repository map has no repositories"]

    for version, settings in version_sets.get("version_sets", {}).items():
        context_type = settings.get("type")
        if context_type not in {"release", "moving"}:
            errors.append(f"{version}: type must be release or moving")
        repositories = settings.get("repositories", {})
        for missing in sorted(repository_names - set(repositories)):
            errors.append(f"{version}: missing repository {missing}")
        for extra in sorted(set(repositories) - repository_names):
            errors.append(f"{version}: unknown repository {extra}")
        for name, repository in repositories.items():
            if not repository.get("ref"):
                errors.append(f"{version}/{name}: ref is required")
            if context_type == "release" and not repository.get("commit"):
                errors.append(f"{version}/{name}: release commit must be pinned")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-map", type=Path, required=True)
    parser.add_argument("--version-sets", type=Path, required=True)
    args = parser.parse_args()
    repository_map = json.loads(args.repository_map.read_text(encoding="utf-8"))
    version_sets = json.loads(args.version_sets.read_text(encoding="utf-8"))
    errors = validate(repository_map, version_sets)
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
