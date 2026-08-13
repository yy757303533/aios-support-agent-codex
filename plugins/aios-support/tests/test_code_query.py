from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN_ROOT / "scripts" / "query_code.py"


class CodeQueryTest(unittest.TestCase):
    def test_grep_reads_requested_commit_from_bare_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            working = root / "working"
            mirrors = root / "mirrors"
            working.mkdir()
            mirrors.mkdir()
            subprocess.run(["git", "init"], cwd=working, check=True, capture_output=True)
            subprocess.run(["git", "checkout", "-b", "main"], cwd=working, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=working, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=working, check=True)
            (working / "service.py").write_text("class ModelService:\n    pass\n", encoding="utf-8")
            subprocess.run(["git", "add", "service.py"], cwd=working, check=True)
            subprocess.run(["git", "commit", "-m", "fixture"], cwd=working, check=True, capture_output=True)
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=working, check=True, capture_output=True, text=True
            ).stdout.strip()
            subprocess.run(
                ["git", "clone", "--mirror", str(working), str(mirrors / "zstack.git")],
                check=True,
                capture_output=True,
            )
            repository_map = root / "repository-map.json"
            repository_map.write_text(
                json.dumps({"repositories": {"zstack": {"mirror": "zstack.git"}}}), encoding="utf-8"
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--mirror-root",
                    str(mirrors),
                    "--repository-map",
                    str(repository_map),
                    "--repository",
                    "zstack",
                    "--commit",
                    commit,
                    "grep",
                    "--pattern",
                    "ModelService",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(result.stdout)
            self.assertIn("service.py", payload["output"])
            self.assertEqual(commit, payload["commit"])


if __name__ == "__main__":
    unittest.main()
