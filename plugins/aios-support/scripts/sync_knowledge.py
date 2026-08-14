#!/usr/bin/env python3
"""Prepare and publish reviewed, sanitized AIOS knowledge snapshots."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from security_common import (
    ANY_IPV4_PATTERN,
    EMAIL_PATTERN,
    IPV6_PATTERN,
    MAC_PATTERN,
    UUID_PATTERN,
    secret_rule_names,
)


NODE_ID = re.compile(r"[A-Za-z0-9_-]{16,64}")
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
MARKDOWN_IMAGE = re.compile(r"!\[[^]]*]\([^)]*\)")
MARKDOWN_LINK = re.compile(r"\[([^]]+)]\([^)]*\)")
URL = re.compile(r"(?i)https?://[^\s)>]+")
HTML_TAG = re.compile(r"<[^>]+>")
CREDENTIAL_LINE = re.compile(
    r"(?i)(?:默认(?:账号|用户|密码)|(?:user(?:name)?|账号|用户名).{0,20}(?:password|passwd|密码)|"
    r"(?:password|passwd|密码|token|secret|authorization)\s*[:=])"
)
PROMPT_MANIPULATION = re.compile(
    r"(?i)(?:ignore (?:all |the )?(?:previous|prior) instructions|reveal (?:the )?system prompt|"
    r"developer message|system message|越权|忽略(?:之前|以上).{0,8}(?:指令|要求))"
)
DANGEROUS_ACTION = re.compile(
    r"(?i)(?:rm\s+-rf|sed\s+-i|kubectl\s+delete|drop\s+table|shutdown\b|reboot\b|"
    r"systemctl\s+(?:stop|restart)|sysctl\s+-w|apply.{0,12}destroy|"
    r"\b(?:chmod|chown|mount|umount|redis-cli)\b|"
    r"(?:删除|删去|去掉|重启|停止|启动|修改|替换|卸载|执行命令))"
)
MAX_DOCUMENT_CHARS = 1_000_000
MAX_CHUNK_CHARS = 3_500
DEFAULT_SOURCES = Path(__file__).resolve().parents[1] / "config" / "knowledge-sources.json"


class KnowledgeError(Exception):
    pass


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KnowledgeError("invalid_json") from exc


def validate_source_config(path: Path) -> list[dict[str, str]]:
    payload = load_json(path)
    if not isinstance(payload, dict) or set(payload) != {"sources"}:
        raise KnowledgeError("invalid_source_config")
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources or len(sources) > 20:
        raise KnowledgeError("invalid_source_config")
    validated: list[dict[str, str]] = []
    seen: set[str] = set()
    for source in sources:
        if not isinstance(source, dict) or set(source) != {"node_id", "url"}:
            raise KnowledgeError("invalid_source_config")
        node_id = source.get("node_id")
        url = source.get("url")
        if not isinstance(node_id, str) or not NODE_ID.fullmatch(node_id):
            raise KnowledgeError("invalid_source_config")
        if not isinstance(url, str):
            raise KnowledgeError("invalid_source_config")
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "alidocs.dingtalk.com"
            or parsed.path != f"/i/nodes/{node_id}"
            or parsed.params
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
            or parsed.port
        ):
            raise KnowledgeError("invalid_source_config")
        if node_id in seen:
            raise KnowledgeError("invalid_source_config")
        seen.add(node_id)
        validated.append({"node_id": node_id, "url": url})
    return validated


def run_dws(dws_bin: Path, *arguments: str) -> dict[str, object]:
    if not dws_bin.is_file() or not os.access(dws_bin, os.X_OK):
        raise KnowledgeError("dws_unavailable")
    try:
        result = subprocess.run(
            [str(dws_bin), *arguments, "--format", "json"],
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise KnowledgeError("dws_failed") from exc
    if result.returncode != 0 or len(result.stdout) > MAX_DOCUMENT_CHARS * 2:
        raise KnowledgeError("dws_failed")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise KnowledgeError("dws_invalid_response") from exc
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise KnowledgeError("dws_invalid_response")
    return payload


def safe_title(value: object) -> str:
    if not isinstance(value, str):
        return "AIOS knowledge"
    title = HTML_TAG.sub("", html.unescape(value)).strip()[:160]
    if not title or secret_rule_names(title) or CREDENTIAL_LINE.search(title):
        return "AIOS knowledge"
    return title


def sanitize_markdown(markdown: str) -> tuple[str, dict[str, int]]:
    text = html.unescape(markdown.replace("\r\n", "\n").replace("\r", "\n"))
    text = MARKDOWN_IMAGE.sub("[image removed]", text)
    text = MARKDOWN_LINK.sub(r"\1", text)
    text = URL.sub("[reference link removed]", text)
    text = HTML_TAG.sub("", text)
    stats = {"credential_lines_removed": 0, "dangerous_lines_removed": 0, "prompt_lines_removed": 0}
    safe_lines: list[str] = []
    for line in text.splitlines():
        if secret_rule_names(line) or CREDENTIAL_LINE.search(line):
            stats["credential_lines_removed"] += 1
            continue
        if PROMPT_MANIPULATION.search(line):
            stats["prompt_lines_removed"] += 1
            continue
        parts = re.split(r"(?<=[；;。.!！？?])\s*", line)
        safe_parts = [part for part in parts if part and not DANGEROUS_ACTION.search(part)]
        if len(safe_parts) != len([part for part in parts if part]):
            stats["dangerous_lines_removed"] += 1
            line = " ".join(safe_parts)
            if not line:
                continue
        line = UUID_PATTERN.sub("[redacted-id]", line)
        line = EMAIL_PATTERN.sub("[redacted-email]", line)
        line = MAC_PATTERN.sub("[redacted-mac]", line)
        line = IPV6_PATTERN.sub("[redacted-ip]", line)
        line = ANY_IPV4_PATTERN.sub("[redacted-ip]", line)
        safe_lines.append(line.rstrip())
    compact: list[str] = []
    empty = 0
    for line in safe_lines:
        if line:
            empty = 0
            compact.append(line)
        else:
            empty += 1
            if empty <= 1:
                compact.append("")
    sanitized = "\n".join(compact).strip() + "\n"
    if not sanitized.strip() or secret_rule_names(sanitized):
        raise KnowledgeError("sanitization_failed")
    return sanitized, stats


def chunk_markdown(markdown: str) -> list[str]:
    paragraphs = re.split(r"\n(?=#{1,4}\s)|\n\n+", markdown)
    chunks: list[str] = []
    current = ""
    for paragraph in (part.strip() for part in paragraphs):
        if not paragraph:
            continue
        if len(paragraph) > MAX_CHUNK_CHARS:
            pieces = [paragraph[index : index + MAX_CHUNK_CHARS] for index in range(0, len(paragraph), MAX_CHUNK_CHARS)]
        else:
            pieces = [paragraph]
        for piece in pieces:
            candidate = piece if not current else f"{current}\n\n{piece}"
            if current and len(candidate) > MAX_CHUNK_CHARS:
                chunks.append(current + "\n")
                current = piece
            else:
                current = candidate
    if current:
        chunks.append(current + "\n")
    if not chunks:
        raise KnowledgeError("sanitization_failed")
    return chunks


def fetch_source(dws_bin: Path, source: dict[str, str]) -> dict[str, object]:
    node_id = source["node_id"]
    info = run_dws(dws_bin, "drive", "info", "--node", node_id)
    result = info.get("result")
    if not isinstance(result, dict):
        raise KnowledgeError("dws_invalid_response")
    if result.get("nodeId") != node_id or result.get("extension") != "adoc":
        raise KnowledgeError("source_type_mismatch")
    document = run_dws(dws_bin, "doc", "read", "--node", node_id)
    markdown = document.get("markdown")
    if not isinstance(markdown, str) or not markdown or len(markdown) > MAX_DOCUMENT_CHARS:
        raise KnowledgeError("dws_invalid_response")
    sanitized, stats = sanitize_markdown(markdown)
    return {
        "node_id": node_id,
        "url": source["url"],
        "title": safe_title(document.get("title") or result.get("name")),
        "updated_at_ms": result.get("updateTime") if isinstance(result.get("updateTime"), int) else None,
        "chunks": chunk_markdown(sanitized),
        "redaction": stats,
    }


def validate_snapshot_id(value: str) -> str:
    if not SAFE_NAME.fullmatch(value):
        raise KnowledgeError("invalid_snapshot_id")
    return value


def prepare(args: argparse.Namespace) -> dict[str, object]:
    sources = validate_source_config(args.sources.resolve())
    snapshot_id = validate_snapshot_id(
        args.snapshot_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    candidate_root = args.candidate_root.resolve()
    candidate = candidate_root / snapshot_id
    if candidate.exists():
        raise KnowledgeError("candidate_exists")
    candidate.mkdir(parents=True, mode=0o700)
    os.chmod(candidate, 0o700)
    manifest_sources: list[dict[str, object]] = []
    chunk_entries: list[dict[str, str]] = []
    for source_index, source in enumerate(sources, start=1):
        fetched = fetch_source(args.dws_bin.resolve(), source)
        source_chunks: list[str] = []
        for chunk_index, content in enumerate(fetched.pop("chunks"), start=1):
            filename = f"source-{source_index:02d}-chunk-{chunk_index:03d}.md"
            rendered = (
                f"# {fetched['title']}\n\n"
                f"来源节点：{fetched['node_id']}\n\n"
                f"{content}"
            )
            path = candidate / filename
            path.write_text(rendered, encoding="utf-8")
            os.chmod(path, 0o600)
            source_chunks.append(filename)
            chunk_entries.append({"file": filename, "sha256": digest(rendered)})
        fetched["chunk_files"] = source_chunks
        manifest_sources.append(fetched)
    manifest = {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "status": "pending_review",
        "prepared_at": utc_now(),
        "sources": manifest_sources,
        "chunks": chunk_entries,
    }
    manifest_path = candidate / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(manifest_path, 0o600)
    return {"status": "pending_review", "candidate": str(candidate), "chunks": len(chunk_entries)}


def validate_candidate(candidate: Path, sources_path: Path) -> dict[str, object]:
    if not candidate.is_dir() or candidate.is_symlink():
        raise KnowledgeError("invalid_candidate")
    manifest = load_json(candidate / "manifest.json")
    if not isinstance(manifest, dict) or manifest.get("status") != "pending_review":
        raise KnowledgeError("invalid_candidate")
    snapshot_id = manifest.get("snapshot_id")
    if not isinstance(snapshot_id, str) or validate_snapshot_id(snapshot_id) != candidate.name:
        raise KnowledgeError("invalid_candidate")
    sources = manifest.get("sources")
    chunks = manifest.get("chunks")
    if not isinstance(sources, list) or not isinstance(chunks, list) or not chunks:
        raise KnowledgeError("invalid_candidate")
    manifest_sources = validate_source_config_from_manifest(sources)
    approved_sources = validate_source_config(sources_path.resolve())
    if manifest_sources != approved_sources:
        raise KnowledgeError("invalid_candidate")
    expected_files = {"manifest.json"}
    for entry in chunks:
        if not isinstance(entry, dict) or set(entry) != {"file", "sha256"}:
            raise KnowledgeError("invalid_candidate")
        filename = entry.get("file")
        checksum = entry.get("sha256")
        if not isinstance(filename, str) or not re.fullmatch(r"source-\d{2}-chunk-\d{3}\.md", filename):
            raise KnowledgeError("invalid_candidate")
        path = candidate / filename
        if not path.is_file() or path.is_symlink():
            raise KnowledgeError("invalid_candidate")
        content = path.read_text(encoding="utf-8")
        if digest(content) != checksum or secret_rule_names(content):
            raise KnowledgeError("candidate_integrity_failed")
        if URL.search(content) or PROMPT_MANIPULATION.search(content) or DANGEROUS_ACTION.search(content):
            raise KnowledgeError("candidate_integrity_failed")
        expected_files.add(filename)
    actual_files = {path.name for path in candidate.iterdir() if path.is_file()}
    if actual_files != expected_files:
        raise KnowledgeError("invalid_candidate")
    return manifest


def validate_source_config_from_manifest(sources: list[object]) -> list[dict[str, str]]:
    validated: list[dict[str, str]] = []
    for source in sources:
        if not isinstance(source, dict):
            raise KnowledgeError("invalid_candidate")
        node_id = source.get("node_id")
        url = source.get("url")
        if not isinstance(node_id, str) or not isinstance(url, str):
            raise KnowledgeError("invalid_candidate")
        parsed = urlparse(url)
        if (
            not NODE_ID.fullmatch(node_id)
            or parsed.scheme != "https"
            or parsed.hostname != "alidocs.dingtalk.com"
            or parsed.path != f"/i/nodes/{node_id}"
            or parsed.params
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
            or parsed.port
        ):
            raise KnowledgeError("invalid_candidate")
        validated.append({"node_id": node_id, "url": url})
    return validated


def publish(args: argparse.Namespace) -> dict[str, object]:
    if not args.confirm_reviewed or not args.reviewed_by or not SAFE_NAME.fullmatch(args.reviewed_by):
        raise KnowledgeError("review_required")
    candidate = args.candidate.resolve()
    manifest = validate_candidate(candidate, args.sources)
    snapshot_id = manifest["snapshot_id"]
    destination = args.destination.resolve()
    releases = destination / "releases"
    release = releases / snapshot_id
    if release.exists():
        raise KnowledgeError("immutable_release_exists")
    destination.mkdir(parents=True, mode=0o700, exist_ok=True)
    releases.mkdir(mode=0o700, exist_ok=True)
    temporary = releases / f".{snapshot_id}.tmp-{os.getpid()}"
    if temporary.exists():
        raise KnowledgeError("publish_conflict")
    shutil.copytree(candidate, temporary, symlinks=False)
    approved = dict(manifest)
    approved.update({"status": "approved", "reviewed_at": utc_now(), "reviewed_by": args.reviewed_by})
    (temporary / "manifest.json").write_text(
        json.dumps(approved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for path in temporary.iterdir():
        os.chmod(path, 0o600)
    os.chmod(temporary, 0o700)
    temporary.rename(release)
    next_link = destination / f".current-{os.getpid()}"
    next_link.symlink_to(Path("releases") / snapshot_id)
    os.replace(next_link, destination / "current")
    return {"status": "approved", "release": str(release), "current": str(destination / "current")}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--sources", type=Path, required=True)
    prepare_parser.add_argument("--candidate-root", type=Path, required=True)
    prepare_parser.add_argument("--snapshot-id")
    prepare_parser.add_argument("--dws-bin", type=Path, default=Path("/usr/local/bin/dws"))
    publish_parser = commands.add_parser("publish")
    publish_parser.add_argument("--candidate", type=Path, required=True)
    publish_parser.add_argument("--destination", type=Path, required=True)
    publish_parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    publish_parser.add_argument("--confirm-reviewed", action="store_true")
    publish_parser.add_argument("--reviewed-by")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        result = prepare(args) if args.command == "prepare" else publish(args)
    except (KnowledgeError, OSError, UnicodeDecodeError) as exc:
        code = str(exc) if isinstance(exc, KnowledgeError) else "knowledge_operation_failed"
        print(json.dumps({"error": code}), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
