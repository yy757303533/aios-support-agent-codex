#!/usr/bin/env python3
"""Resolve an AIOS product version or development branch to immutable commits."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")
REF_RE = re.compile(r"^[A-Za-z0-9._/-]{1,255}$")


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("json_object_required")
    return value


def git_output(mirror: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", f"--git-dir={mirror}", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def resolve_ref(mirror: Path, ref: str) -> str | None:
    if not REF_RE.fullmatch(ref) or ref.startswith(("-", "/")) or ".." in ref.split("/"):
        return None
    candidates = [ref] if ref.startswith("refs/") else [
        f"refs/heads/{ref}",
        f"refs/remotes/origin/{ref}",
        f"refs/tags/{ref}",
    ]
    for candidate in candidates:
        commit = git_output(mirror, "rev-parse", "--verify", f"{candidate}^{{commit}}")
        if commit:
            return commit
    return None


def verify_commit(mirror: Path, commit: str) -> str | None:
    if not COMMIT_RE.fullmatch(commit):
        return None
    return git_output(mirror, "rev-parse", "--verify", f"{commit}^{{commit}}")


def is_ancestor(mirror: Path, commit: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", f"--git-dir={mirror}", "merge-base", "--is-ancestor", commit, descendant],
        check=False,
        capture_output=True,
        timeout=20,
    )
    return result.returncode == 0


def build_branch_set(repository_map: dict[str, Any], branch: str) -> dict[str, Any]:
    if not isinstance(repository_map.get("repositories"), dict):
        raise ValueError("repository_map_invalid")
    repositories: dict[str, dict[str, str]] = {}
    for name, settings in repository_map["repositories"].items():
        if not isinstance(settings, dict):
            raise ValueError("repository_settings_invalid")
        ref = settings.get("default_ref") if settings.get("branch_policy") == "fixed" else branch
        repositories[name] = {"ref": ref}
    return {
        "type": "branch",
        "description": f"Development branch {branch}",
        "repositories": repositories,
    }


def resolve_context(
    repository_map: dict[str, Any],
    version_set: dict[str, Any],
    mirror_root: Path,
    context_id: str,
) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    missing: list[str] = []
    context_type = version_set.get("type", "moving")

    if not isinstance(repository_map.get("repositories"), dict) or not isinstance(version_set.get("repositories"), dict):
        raise ValueError("context_schema_invalid")

    for name, settings in repository_map["repositories"].items():
        if not isinstance(settings, dict):
            raise ValueError("repository_settings_invalid")
        requested = version_set.get("repositories", {}).get(name)
        mirror_name = settings.get("mirror")
        if not isinstance(mirror_name, str) or Path(mirror_name).name != mirror_name:
            raise ValueError("mirror_name_invalid")
        root = mirror_root.resolve()
        mirror = (root / mirror_name).resolve()
        if requested is not None and not isinstance(requested, dict):
            raise ValueError("version_repository_invalid")
        result: dict[str, Any] = {
            "mirror": mirror_name,
            "ref": requested.get("ref") if requested else None,
            "commit": None,
            "status": "unmapped",
        }

        if not requested:
            missing.append(name)
        elif mirror.parent != root or not mirror.is_dir() or mirror.is_symlink():
            result["status"] = "mirror_missing"
            missing.append(name)
        elif context_type == "release" and not requested.get("commit"):
            result["status"] = "release_commit_unpinned"
            missing.append(name)
        elif requested.get("commit"):
            commit = verify_commit(mirror, requested["commit"])
            ref_commit = resolve_ref(mirror, requested["ref"]) if requested.get("ref") else commit
            if commit and ref_commit and is_ancestor(mirror, commit, ref_commit):
                result.update(commit=commit, status="resolved")
            elif commit:
                result["status"] = "commit_ref_mismatch"
                missing.append(name)
            else:
                result["status"] = "commit_missing"
                missing.append(name)
        elif requested.get("ref"):
            commit = resolve_ref(mirror, requested["ref"])
            if commit:
                result.update(commit=commit, status="resolved")
            else:
                result["status"] = "branch_missing"
                missing.append(name)
        else:
            missing.append(name)

        resolved[name] = result

    return {
        "context_id": context_id,
        "type": context_type,
        "description": version_set.get("description", ""),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "complete": not missing,
        "missing": missing,
        "repositories": resolved,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--version", help="Version-set key, for example 5.5.28")
    selector.add_argument("--branch", help="Development branch applied to versioned repositories")
    parser.add_argument("--mirror-root", type=Path, required=True)
    parser.add_argument("--repository-map", type=Path, required=True)
    parser.add_argument("--version-sets", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        repository_map = load_json(args.repository_map)
        if args.version:
            if not args.version_sets:
                raise ValueError("--version-sets is required with --version")
            version_sets = load_json(args.version_sets).get("version_sets", {})
            if args.version not in version_sets:
                raise ValueError(f"unknown version set: {args.version}")
            version_set = version_sets[args.version]
            context_id = args.version
        else:
            version_set = build_branch_set(repository_map, args.branch)
            context_id = f"branch:{args.branch}"

        context = resolve_context(repository_map, version_set, args.mirror_root, context_id)
        print(json.dumps(context, ensure_ascii=False, indent=2))
        return 0 if context["complete"] else 2
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
        reason = str(error) if isinstance(error, ValueError) else "context_resolution_failed"
        print(json.dumps({"error": reason}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
