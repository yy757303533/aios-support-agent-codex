from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN_ROOT / "scripts" / "refresh_mirrors.py"


class RefreshMirrorsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.mirrors = self.root / "mirrors"
        self.mirrors.mkdir()
        subprocess.run(["git", "init", "--bare", str(self.remote)], check=True, capture_output=True)
        work = self.root / "work"
        subprocess.run(["git", "clone", str(self.remote), str(work)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(work), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(work), "config", "user.name", "Test"], check=True)
        (work / "file.txt").write_text("one", encoding="utf-8")
        subprocess.run(["git", "-C", str(work), "add", "file.txt"], check=True)
        subprocess.run(["git", "-C", str(work), "commit", "-m", "one"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(work), "push", "origin", "HEAD:master"], check=True, capture_output=True)
        self.mirror = self.mirrors / "aios.git"
        subprocess.run(["git", "clone", "--mirror", str(self.remote), str(self.mirror)], check=True, capture_output=True)
        (work / "file.txt").write_text("two", encoding="utf-8")
        subprocess.run(["git", "-C", str(work), "commit", "-am", "two"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(work), "push", "origin", "HEAD:master"], check=True, capture_output=True)
        self.expected = subprocess.run(
            ["git", "-C", str(work), "rev-parse", "HEAD"], text=True, capture_output=True, check=True
        ).stdout.strip()
        self.map = self.root / "map.json"
        self.map.write_text(
            json.dumps(
                {
                    "repositories": {
                        "aios": {"mirror": "aios.git", "default_ref": "master", "branch_policy": "fixed"}
                    }
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_fetches_only_registered_bare_mirror_without_checkout_or_push(self) -> None:
        before = subprocess.run(
            ["git", f"--git-dir={self.mirror}", "rev-parse", "master"], text=True, capture_output=True, check=True
        ).stdout.strip()
        self.assertNotEqual(self.expected, before)

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--mirror-root",
                str(self.mirrors),
                "--repository-map",
                str(self.map),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        after = subprocess.run(
            ["git", f"--git-dir={self.mirror}", "rev-parse", "master"], text=True, capture_output=True, check=True
        ).stdout.strip()
        self.assertEqual(self.expected, after)
        self.assertFalse((self.mirrors / "aios").exists())

    def test_rejects_map_path_escape_before_git(self) -> None:
        self.map.write_text(json.dumps({"repositories": {"aios": {"mirror": "../remote.git"}}}), encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--mirror-root",
                str(self.mirrors),
                "--repository-map",
                str(self.map),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(2, result.returncode)
        self.assertNotIn(str(self.remote), result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
