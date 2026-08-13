from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN_ROOT / "scripts" / "configure_runtime.py"


class RuntimeConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = self.root / ".mcp.json"
        token_name = "GITLAB_" + "TOKEN"
        self.config.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "zdev": {
                            "type": "stdio",
                            "command": "node",
                            "args": ["/srv/zdev/dist/index.js"],
                            "env": {token_name: "runtime-value-not-for-output"},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        self.config.chmod(0o600)
        self.proxy = PLUGIN_ROOT / "scripts" / "zdev_readonly_proxy.mjs"
        self.refresh = PLUGIN_ROOT / "scripts" / "refresh_mirrors.py"
        self.search = PLUGIN_ROOT / "scripts" / "search_local_code.py"
        self.repository_map = PLUGIN_ROOT / "config" / "repository-map.json"
        self.version_sets = self.root / "version-sets.json"
        self.version_sets.write_text('{"version_sets":{"5.5.30":{}}}', encoding="utf-8")
        self.mirror_root = self.root / "mirrors"
        self.mirror_root.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_configure(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "mcp",
                "--config",
                str(self.config),
                "--proxy",
                str(self.proxy),
                "--refresh-script",
                str(self.refresh),
                "--search-script",
                str(self.search),
                "--mirror-root",
                str(self.mirror_root),
                "--repository-map",
                str(self.repository_map),
                "--version-sets",
                str(self.version_sets),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_replaces_raw_zdev_with_disabled_upstream_and_readonly_proxy(self) -> None:
        result = self.run_configure()

        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(self.config.read_text(encoding="utf-8"))
        servers = payload["mcpServers"]
        self.assertNotIn("zdev", servers)
        self.assertFalse(servers["zdev_upstream"]["enabled"])
        self.assertEqual("runtime-value-not-for-output", next(iter(servers["zdev_upstream"]["env"].values())))
        self.assertEqual(
            {
                "type": "stdio",
                "command": "node",
                "args": [str(self.proxy.resolve())],
                "env": {
                    "ZDEV_MCP_CONFIG": str(self.config.resolve()),
                    "ZDEV_MCP_SERVER": "zdev_upstream",
                    "AIOS_REFRESH_SCRIPT": str(self.refresh.resolve()),
                    "AIOS_LOCAL_SEARCH_SCRIPT": str(self.search.resolve()),
                    "AIOS_MIRROR_ROOT": str(self.mirror_root.resolve()),
                    "AIOS_REPOSITORY_MAP": str(self.repository_map.resolve()),
                    "AIOS_VERSION_SETS_FILE": str(self.version_sets.resolve()),
                },
                "enabled": True,
                "default_tools_approval_mode": "never",
            },
            servers["zdev_readonly"],
        )
        self.assertEqual(0o600, self.config.stat().st_mode & 0o777)
        self.assertNotIn("runtime-value", result.stdout + result.stderr)

    def test_migration_is_idempotent(self) -> None:
        first = self.run_configure()
        self.assertEqual(0, first.returncode, first.stderr)
        first_content = self.config.read_text(encoding="utf-8")

        second = self.run_configure()

        self.assertEqual(0, second.returncode, second.stderr)
        self.assertEqual(first_content, self.config.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
