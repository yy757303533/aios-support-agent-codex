#!/usr/bin/env python3
"""Freeze approved release refs from five bare mirrors to immutable commits."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path


SAFE_VALUE = re.compile(r"[A-Za-z0-9._-]{1,128}")
SAFE_REF = re.compile(r"[A-Za-z0-9._/-]{1,255}")


class FreezeError(Exception):
    pass


def load_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FreezeError("input_invalid") from exc
    if not isinstance(value, dict):
        raise FreezeError("input_invalid")
    return value


def resolve_ref(mirror: Path, ref: str) -> str:
    if not SAFE_REF.fullmatch(ref) or ref.startswith(("-", "/")) or ".." in ref.split("/"):
        raise FreezeError("ref_invalid")
    candidates = [f"refs/heads/{ref}", f"refs/remotes/origin/{ref}", f"refs/tags/{ref}"]
    for candidate in candidates:
        try:
            result = subprocess.run(
                ["git", f"--git-dir={mirror}", "rev-parse", "--verify", f"{candidate}^{{commit}}"],
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise FreezeError("git_failed") from exc
        commit = result.stdout.strip()
        if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", commit):
            return commit
    raise FreezeError("ref_unresolved")


def atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".version-sets-", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def freeze(repository_map_path: Path, mirror_root: Path, release_refs_path: Path, approved_by: str) -> dict:
    repository_map = load_object(repository_map_path)
    release_refs = load_object(release_refs_path)
    repositories = repository_map.get("repositories")
    refs = release_refs.get("refs")
    version = release_refs.get("version")
    if (
        not isinstance(repositories, dict)
        or not isinstance(refs, dict)
        or set(refs) != set(repositories)
        or not isinstance(version, str)
        or not SAFE_VALUE.fullmatch(version)
        or not SAFE_VALUE.fullmatch(approved_by)
    ):
        raise FreezeError("input_invalid")
    root = mirror_root.resolve()
    frozen = {}
    for name, settings in repositories.items():
        if not isinstance(settings, dict) or not isinstance(settings.get("mirror"), str):
            raise FreezeError("repository_invalid")
        mirror = (root / settings["mirror"]).resolve()
        ref = refs.get(name)
        if mirror.parent != root or not mirror.is_dir() or mirror.is_symlink() or not isinstance(ref, str):
            raise FreezeError("repository_invalid")
        frozen[name] = {"ref": ref, "commit": resolve_ref(mirror, ref)}
    captured_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    return {
        "version_sets": {
            version: {
                "type": "release",
                "description": f"Manually frozen AIOS support baseline for {version}.",
                "provenance": {
                    "method": "manual_ref_snapshot",
                    "captured_at": captured_at,
                    "approved_by": approved_by,
                },
                "repositories": frozen,
            }
        }
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-map", type=Path, required=True)
    parser.add_argument("--mirror-root", type=Path, required=True)
    parser.add_argument("--release-refs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--approved-by", required=True)
    args = parser.parse_args()
    try:
        payload = freeze(args.repository_map, args.mirror_root, args.release_refs, args.approved_by)
        atomic_write(args.output.resolve(), payload)
    except (FreezeError, OSError):
        print('{"status":"failed"}')
        return 2
    print('{"status":"frozen"}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
