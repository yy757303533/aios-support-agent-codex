#!/usr/bin/env python3
"""Run bounded, read-only queries against one resolved repository commit."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


MAX_OUTPUT_CHARS = 80_000
MAX_INPUT_CHARS = 4096
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def repository_mirror(repository_map: Path, mirror_root: Path, repository: str) -> Path:
    config = load_json(repository_map)
    if not isinstance(config, dict) or not isinstance(config.get("repositories"), dict):
        raise ValueError("repository_map_invalid")
    repositories = config["repositories"]
    if repository not in repositories:
        raise ValueError("repository_unknown")
    settings = repositories[repository]
    if not isinstance(settings, dict):
        raise ValueError("repository_settings_invalid")
    mirror_name = settings.get("mirror")
    if not isinstance(mirror_name, str) or Path(mirror_name).name != mirror_name:
        raise ValueError("mirror_name_invalid")
    root = mirror_root.resolve()
    mirror = (root / mirror_name).resolve()
    if mirror.parent != root or not mirror.is_dir() or mirror.is_symlink():
        raise ValueError("mirror_missing")
    return mirror


def context_commit(
    context_file: Path,
    repository_map: Path,
    mirror_root: Path,
    repository: str,
    version_sets_file: Path | None,
) -> tuple[str, str]:
    context = load_json(context_file)
    repository_config = load_json(repository_map)
    configured = repository_config.get("repositories") if isinstance(repository_config, dict) else None
    if not isinstance(context, dict) or context.get("complete") is not True or not isinstance(configured, dict):
        raise ValueError("code_context_incomplete")
    context_id = context.get("context_id")
    repositories = context.get("repositories")
    context_type = context.get("type")
    if (
        not isinstance(context_id, str)
        or context_type not in {"branch", "release", "moving"}
        or not isinstance(repositories, dict)
        or set(repositories) != set(configured)
        or context.get("missing") != []
    ):
        raise ValueError("code_context_invalid")
    expected_version = None
    if context_type in {"release", "moving"}:
        if version_sets_file is None:
            raise ValueError("version_sets_required")
        version_sets = load_json(version_sets_file)
        configured_versions = version_sets.get("version_sets") if isinstance(version_sets, dict) else None
        expected_version = configured_versions.get(context_id) if isinstance(configured_versions, dict) else None
        if not isinstance(expected_version, dict) or expected_version.get("type") != context_type:
            raise ValueError("version_context_untrusted")
        if not isinstance(expected_version.get("repositories"), dict):
            raise ValueError("version_context_untrusted")

    for name, settings in configured.items():
        entry = repositories.get(name)
        if not isinstance(settings, dict) or not isinstance(entry, dict):
            raise ValueError("code_context_invalid")
        mirror_name = settings.get("mirror")
        if entry.get("mirror") != mirror_name or entry.get("status") != "resolved":
            raise ValueError("code_context_invalid")
        ref = entry.get("ref")
        commit = entry.get("commit")
        if not isinstance(ref, str) or not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
            raise ValueError("code_context_invalid")
        mirror = repository_mirror(repository_map, mirror_root, name)
        if context_type in {"release", "moving"}:
            expected = expected_version["repositories"].get(name)
            if not isinstance(expected, dict) or expected.get("ref") != ref:
                raise ValueError("version_context_untrusted")
            if context_type == "release" and expected.get("commit") != commit:
                raise ValueError("version_context_untrusted")
            if context_type == "moving":
                ref_result = run_git(mirror, ["rev-parse", "--verify", f"refs/heads/{ref}^{{commit}}"])
                if ref_result[0] or ref_result[1].strip() != commit:
                    raise ValueError("version_context_stale")
        else:
            expected_ref = settings.get("default_ref") if settings.get("branch_policy") == "fixed" else context_id.removeprefix("branch:")
            if not context_id.startswith("branch:") or ref != expected_ref:
                raise ValueError("branch_context_invalid")
            ref_result = run_git(mirror, ["rev-parse", "--verify", f"refs/heads/{ref}^{{commit}}"])
            if ref_result[0] or ref_result[1].strip() != commit:
                raise ValueError("branch_context_stale")
    entry = repositories.get(repository)
    commit = entry.get("commit")
    return context_id, commit


def run_git(mirror: Path, args: list[str]) -> tuple[int, str]:
    result = subprocess.run(
        ["git", f"--git-dir={mirror}", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode, result.stdout[:MAX_OUTPUT_CHARS]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mirror-root", type=Path, required=True)
    parser.add_argument("--repository-map", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--context-file", type=Path, required=True)
    parser.add_argument("--version-sets", type=Path)
    subparsers = parser.add_subparsers(dest="mode", required=True)

    grep_parser = subparsers.add_parser("grep")
    grep_parser.add_argument("--pattern", required=True)
    grep_parser.add_argument("--path")

    show_parser = subparsers.add_parser("show")
    show_parser.add_argument("--path", required=True)

    log_parser = subparsers.add_parser("log")
    log_parser.add_argument("--path")
    log_parser.add_argument("--limit", type=int, default=20)

    diff_parser = subparsers.add_parser("diff")
    diff_parser.add_argument("--other-context-file", type=Path, required=True)
    diff_parser.add_argument("--path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        mirror = repository_mirror(args.repository_map, args.mirror_root, args.repository)
        context_id, commit = context_commit(
            args.context_file, args.repository_map, args.mirror_root, args.repository, args.version_sets
        )
        for value in (getattr(args, "pattern", None), getattr(args, "path", None)):
            if value is not None and len(value) > MAX_INPUT_CHARS:
                raise ValueError("query_input_too_large")
        verify_code, _ = run_git(mirror, ["cat-file", "-e", f"{commit}^{{commit}}"])
        if verify_code:
            raise ValueError("commit_missing")

        if args.mode == "grep":
            command = ["grep", "-n", "-I", "-e", args.pattern, commit]
            if args.path:
                command.extend(["--", args.path])
        elif args.mode == "show":
            command = ["show", f"{commit}:{args.path}"]
        elif args.mode == "log":
            limit = min(max(args.limit, 1), 100)
            command = ["log", f"-{limit}", "--format=%H%x09%aI%x09%s", commit]
            if args.path:
                command.extend(["--", args.path])
        else:
            other_context_id, other_commit = context_commit(
                args.other_context_file, args.repository_map, args.mirror_root, args.repository, args.version_sets
            )
            other_code, _ = run_git(mirror, ["cat-file", "-e", f"{other_commit}^{{commit}}"])
            if other_code:
                raise ValueError("other_commit_missing")
            command = ["diff", "--stat", f"{commit}..{other_commit}"]
            if args.path:
                command.extend(["--", args.path])

        code, output = run_git(mirror, command)
        payload = {
            "repository": args.repository,
            "context_id": context_id,
            "commit": commit,
            "mode": args.mode,
            "exit_code": code,
            "output": output,
            "truncated": len(output) >= MAX_OUTPUT_CHARS,
        }
        if args.mode == "diff":
            payload["other_context_id"] = other_context_id
            payload["other_commit"] = other_commit
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if code in (0, 1) and args.mode == "grep" else code
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
        reason = str(error) if isinstance(error, ValueError) else "query_failed"
        print(json.dumps({"error": reason}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
