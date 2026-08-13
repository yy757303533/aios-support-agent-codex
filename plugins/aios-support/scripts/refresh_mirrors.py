#!/usr/bin/env python3
"""Fetch only registered AIOS bare mirrors; never checkout, commit, or push."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


class RefreshError(Exception):
    pass


def load_repositories(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RefreshError("map_invalid") from exc
    repositories = payload.get("repositories") if isinstance(payload, dict) else None
    if not isinstance(repositories, dict) or not repositories:
        raise RefreshError("map_invalid")
    return repositories


def refresh(mirror_root: Path, repository_map: Path) -> list[str]:
    root = mirror_root.resolve()
    repositories = load_repositories(repository_map)
    mirrors: list[tuple[str, Path]] = []
    for name, settings in repositories.items():
        mirror_name = settings.get("mirror") if isinstance(settings, dict) else None
        if not isinstance(name, str) or not isinstance(mirror_name, str) or Path(mirror_name).name != mirror_name:
            raise RefreshError("map_invalid")
        mirror = (root / mirror_name).resolve()
        if mirror.parent != root or not mirror.is_dir() or mirror.is_symlink():
            raise RefreshError("mirror_invalid")
        bare = subprocess.run(
            ["git", f"--git-dir={mirror}", "rev-parse", "--is-bare-repository"],
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        if bare.returncode != 0 or bare.stdout.strip() != "true":
            raise RefreshError("mirror_invalid")
        mirrors.append((name, mirror))
    updated: list[str] = []
    for name, mirror in mirrors:
        result = subprocess.run(
            ["git", f"--git-dir={mirror}", "fetch", "--prune", "origin"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=300,
            check=False,
        )
        if result.returncode != 0:
            raise RefreshError("fetch_failed")
        updated.append(name)
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mirror-root", type=Path, required=True)
    parser.add_argument("--repository-map", type=Path, required=True)
    args = parser.parse_args()
    try:
        updated = refresh(args.mirror_root, args.repository_map)
    except (OSError, RefreshError, subprocess.TimeoutExpired):
        print('{"status":"failed"}')
        return 2
    print(json.dumps({"status": "updated", "repositories": updated}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
