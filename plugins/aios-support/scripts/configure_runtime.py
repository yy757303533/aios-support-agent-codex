#!/usr/bin/env python3
"""Configure repeatable, fail-closed runtime files for the AIOS robot."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path


class ConfigError(Exception):
    pass


def load_config(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise ConfigError("config_invalid")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError("config_invalid") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("mcpServers"), dict):
        raise ConfigError("config_invalid")
    return payload


def atomic_write(path: Path, payload: dict) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=".mcp-", suffix=".tmp", dir=path.parent)
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


def configure_mcp(
    config_path: Path,
    proxy_path: Path,
    refresh_script: Path,
    mirror_root: Path,
    repository_map: Path,
) -> None:
    config_path = config_path.resolve()
    proxy_path = proxy_path.resolve()
    refresh_script = refresh_script.resolve()
    mirror_root = mirror_root.resolve()
    repository_map = repository_map.resolve()
    if (
        not proxy_path.is_file()
        or proxy_path.is_symlink()
        or not refresh_script.is_file()
        or refresh_script.is_symlink()
        or not mirror_root.is_dir()
        or mirror_root.is_symlink()
        or not repository_map.is_file()
        or repository_map.is_symlink()
    ):
        raise ConfigError("proxy_invalid")
    payload = load_config(config_path)
    servers = payload["mcpServers"]
    if "zdev_upstream" not in servers:
        upstream = servers.pop("zdev", None)
        if not isinstance(upstream, dict):
            raise ConfigError("zdev_missing")
        servers["zdev_upstream"] = upstream
    upstream = servers["zdev_upstream"]
    if not isinstance(upstream, dict) or not isinstance(upstream.get("command"), str):
        raise ConfigError("zdev_invalid")
    upstream["enabled"] = False
    servers.pop("zdev", None)
    servers["zdev_readonly"] = {
        "type": "stdio",
        "command": "node",
        "args": [str(proxy_path)],
        "env": {
            "ZDEV_MCP_CONFIG": str(config_path),
            "ZDEV_MCP_SERVER": "zdev_upstream",
            "AIOS_REFRESH_SCRIPT": str(refresh_script),
            "AIOS_MIRROR_ROOT": str(mirror_root),
            "AIOS_REPOSITORY_MAP": str(repository_map),
        },
        "enabled": True,
        "default_tools_approval_mode": "never",
    }
    atomic_write(config_path, payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    mcp = commands.add_parser("mcp")
    mcp.add_argument("--config", type=Path, required=True)
    mcp.add_argument("--proxy", type=Path, required=True)
    mcp.add_argument("--refresh-script", type=Path, required=True)
    mcp.add_argument("--mirror-root", type=Path, required=True)
    mcp.add_argument("--repository-map", type=Path, required=True)
    args = parser.parse_args()
    try:
        configure_mcp(args.config, args.proxy, args.refresh_script, args.mirror_root, args.repository_map)
    except (ConfigError, OSError):
        print('{"status":"failed"}')
        return 2
    print('{"status":"configured"}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
