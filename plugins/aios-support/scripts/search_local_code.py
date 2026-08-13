#!/usr/bin/env python3
"""Search immutable AIOS release commits in bounded local code scopes."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from resolve_code_context import load_json, resolve_context


MAX_TERMS = 8
MAX_TERM_CHARS = 128
MAX_RESULTS = 200
AI_SCOPE = ":(glob,icase)**/ai*/**"
GPU_SCOPES = [":(glob,icase)**/*gpu*/**"]
GUEST_TOOLS_SCOPES = [":(glob,icase)**/*guesttool*/**"]


def parse_string_list(raw: str, field: str) -> list[str]:
    value = json.loads(raw)
    if not isinstance(value, list) or not value or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field}_invalid")
    return value


def search_scopes(repository: str, terms: list[str]) -> list[str]:
    if repository == "aios":
        return []
    scopes = [AI_SCOPE]
    joined = " ".join(terms).lower()
    if any(token in joined for token in ("gpu", "dgpu", "pci", "显卡")):
        scopes.extend(GPU_SCOPES)
    if any(token in joined for token in ("guesttool", "guest tool", "性能优化工具")):
        scopes.extend(GUEST_TOOLS_SCOPES)
    return list(dict.fromkeys(scopes))


def repository_mirror(mirror_root: Path, mirror_name: str) -> Path:
    root = mirror_root.resolve()
    mirror = (root / mirror_name).resolve()
    if mirror.parent != root or not mirror.is_dir() or mirror.is_symlink():
        raise ValueError("mirror_missing")
    return mirror


def git_grep(mirror: Path, commit: str, terms: list[str], scopes: list[str]) -> list[str]:
    command = ["git", f"--git-dir={mirror}", "grep", "-n", "-I", "-i", "-F"]
    for term in terms:
        command.extend(["-e", term])
    command.append(commit)
    if scopes:
        command.extend(["--", *scopes])
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=20)
    if result.returncode not in (0, 1):
        raise ValueError("git_grep_failed")
    return result.stdout.splitlines()


def search(
    mirror_root: Path,
    repository_map_path: Path,
    version_sets_path: Path,
    version: str,
    terms: list[str],
    repositories: list[str] | None,
    max_results: int,
) -> dict:
    if len(terms) > MAX_TERMS or any(not term.strip() or len(term) > MAX_TERM_CHARS or "\n" in term for term in terms):
        raise ValueError("terms_invalid")
    repository_map = load_json(repository_map_path)
    configured = repository_map.get("repositories")
    version_sets = load_json(version_sets_path).get("version_sets")
    if not isinstance(configured, dict) or not isinstance(version_sets, dict):
        raise ValueError("configuration_invalid")
    version_set = version_sets.get(version)
    if not isinstance(version_set, dict):
        raise ValueError("version_unknown")
    selected = repositories or list(configured)
    if not selected or len(selected) != len(set(selected)) or any(name not in configured for name in selected):
        raise ValueError("repositories_invalid")
    context = resolve_context(repository_map, version_set, mirror_root, version)
    if context.get("complete") is not True:
        raise ValueError("code_context_incomplete")

    limit = min(max(max_results, 1), MAX_RESULTS)
    matches: list[dict[str, str | int]] = []
    scanned: list[dict[str, object]] = []
    truncated = False
    repository_limit = max(1, limit // len(selected))
    overflow: list[dict[str, str | int]] = []
    for repository in selected:
        entry = context["repositories"][repository]
        mirror = repository_mirror(mirror_root, entry["mirror"])
        scopes = search_scopes(repository, terms)
        scanned.append({"repository": repository, "commit": entry["commit"], "scopes": scopes or ["<entire-repository>"]})
        repository_matches: list[dict[str, str | int]] = []
        for line in git_grep(mirror, entry["commit"], terms, scopes):
            revision_prefix = f"{entry['commit']}:"
            if line.startswith(revision_prefix):
                line = line[len(revision_prefix):]
            path, separator, remainder = line.partition(":")
            line_number, separator2, text = remainder.partition(":")
            if not separator or not separator2 or not line_number.isdigit():
                continue
            repository_matches.append(
                {"repository": repository, "path": path, "line": int(line_number), "text": text[:500]}
            )
        matches.extend(repository_matches[:repository_limit])
        overflow.extend(repository_matches[repository_limit:])
        truncated = truncated or len(repository_matches) > repository_limit
    remaining = limit - len(matches)
    if remaining > 0:
        matches.extend(overflow[:remaining])
        truncated = truncated or len(overflow) > remaining
    return {
        "version": version,
        "complete": True,
        "terms": terms,
        "scanned": scanned,
        "matches": matches,
        "truncated": truncated,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mirror-root", type=Path, required=True)
    parser.add_argument("--repository-map", type=Path, required=True)
    parser.add_argument("--version-sets", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--terms-json", required=True)
    parser.add_argument("--repositories-json")
    parser.add_argument("--max-results", type=int, default=80)
    args = parser.parse_args()
    try:
        terms = parse_string_list(args.terms_json, "terms")
        repositories = parse_string_list(args.repositories_json, "repositories") if args.repositories_json else None
        payload = search(
            args.mirror_root,
            args.repository_map,
            args.version_sets,
            args.version,
            terms,
            repositories,
            args.max_results,
        )
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
        reason = str(error) if isinstance(error, ValueError) else "local_code_search_failed"
        print(json.dumps({"error": reason}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
