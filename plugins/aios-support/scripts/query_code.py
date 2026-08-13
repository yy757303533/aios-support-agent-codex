#!/usr/bin/env python3
"""Run bounded, read-only queries against one resolved repository commit."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


MAX_OUTPUT_CHARS = 80_000


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def repository_mirror(repository_map: Path, mirror_root: Path, repository: str) -> Path:
    repositories = load_json(repository_map).get("repositories", {})
    if repository not in repositories:
        raise ValueError(f"unknown repository: {repository}")
    mirror = mirror_root / repositories[repository]["mirror"]
    if not mirror.is_dir():
        raise ValueError(f"mirror does not exist: {mirror}")
    return mirror


def run_git(mirror: Path, args: list[str]) -> tuple[int, str, str]:
    result = subprocess.run(
        ["git", f"--git-dir={mirror}", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode, result.stdout[:MAX_OUTPUT_CHARS], result.stderr[:4000]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mirror-root", type=Path, required=True)
    parser.add_argument("--repository-map", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
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
    diff_parser.add_argument("--other-commit", required=True)
    diff_parser.add_argument("--path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        mirror = repository_mirror(args.repository_map, args.mirror_root, args.repository)
        verify_code, _, _ = run_git(mirror, ["cat-file", "-e", f"{args.commit}^{{commit}}"])
        if verify_code:
            raise ValueError(f"commit is not available in {args.repository}: {args.commit}")

        if args.mode == "grep":
            command = ["grep", "-n", "-I", "-e", args.pattern, args.commit]
            if args.path:
                command.extend(["--", args.path])
        elif args.mode == "show":
            command = ["show", f"{args.commit}:{args.path}"]
        elif args.mode == "log":
            limit = min(max(args.limit, 1), 100)
            command = ["log", f"-{limit}", "--format=%H%x09%aI%x09%s", args.commit]
            if args.path:
                command.extend(["--", args.path])
        else:
            other_code, _, _ = run_git(mirror, ["cat-file", "-e", f"{args.other_commit}^{{commit}}"])
            if other_code:
                raise ValueError(f"other commit is not available: {args.other_commit}")
            command = ["diff", "--stat", f"{args.commit}..{args.other_commit}"]
            if args.path:
                command.extend(["--", args.path])

        code, output, error = run_git(mirror, command)
        payload = {
            "repository": args.repository,
            "commit": args.commit,
            "mode": args.mode,
            "exit_code": code,
            "output": output,
            "truncated": len(output) >= MAX_OUTPUT_CHARS,
        }
        if error:
            payload["stderr"] = error
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if code in (0, 1) and args.mode == "grep" else code
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
