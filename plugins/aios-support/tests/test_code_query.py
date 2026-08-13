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
                json.dumps({"repositories": {"zstack": {"mirror": "zstack.git", "branch_policy": "versioned"}}}), encoding="utf-8"
            )
            context = root / "context.json"
            context.write_text(json.dumps({
                "context_id": "branch:main",
                "type": "branch",
                "complete": True,
                "missing": [],
                "repositories": {"zstack": {"mirror": "zstack.git", "ref": "main", "status": "resolved", "commit": commit}},
            }), encoding="utf-8")

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
                    "--context-file",
                    str(context),
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

    def test_rejects_non_commit_revision_before_git_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mirrors = root / "mirrors"
            mirror = mirrors / "zstack.git"
            mirror.mkdir(parents=True)
            repository_map = root / "repository-map.json"
            repository_map.write_text(
                json.dumps({"repositories": {"zstack": {"mirror": "zstack.git", "branch_policy": "versioned"}}}), encoding="utf-8"
            )
            context = root / "context.json"
            context.write_text(json.dumps({
                "context_id": "invalid",
                "type": "branch",
                "complete": True,
                "missing": [],
                "repositories": {"zstack": {"mirror": "zstack.git", "ref": "main", "status": "resolved", "commit": "HEAD"}},
            }), encoding="utf-8")
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
                    "--context-file",
                    str(context),
                    "grep",
                    "--pattern",
                    "ModelService",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("code_context_invalid", result.stderr)

    def test_rejects_repository_map_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mirrors = root / "mirrors"
            mirrors.mkdir()
            repository_map = root / "repository-map.json"
            repository_map.write_text(
                json.dumps({"repositories": {"zstack": {"mirror": "../outside.git"}}}), encoding="utf-8"
            )
            context = root / "context.json"
            context.write_text(json.dumps({
                "context_id": "escape",
                "complete": True,
                "repositories": {"zstack": {"status": "resolved", "commit": "a" * 40}},
            }), encoding="utf-8")
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
                    "--context-file",
                    str(context),
                    "grep",
                    "--pattern",
                    "ModelService",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertIn("mirror_name_invalid", result.stderr)

    def test_rejects_forged_branch_context_with_non_tip_commit(self) -> None:
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
            (working / "service.py").write_text("old\n", encoding="utf-8")
            subprocess.run(["git", "add", "service.py"], cwd=working, check=True)
            subprocess.run(["git", "commit", "-m", "old"], cwd=working, check=True, capture_output=True)
            old_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=working, check=True, capture_output=True, text=True
            ).stdout.strip()
            (working / "service.py").write_text("new\n", encoding="utf-8")
            subprocess.run(["git", "commit", "-am", "new"], cwd=working, check=True, capture_output=True)
            subprocess.run(
                ["git", "clone", "--mirror", str(working), str(mirrors / "zstack.git")],
                check=True,
                capture_output=True,
            )
            repository_map = root / "repository-map.json"
            repository_map.write_text(json.dumps({
                "repositories": {"zstack": {"mirror": "zstack.git", "branch_policy": "versioned"}}
            }), encoding="utf-8")
            context = root / "forged.json"
            context.write_text(json.dumps({
                "context_id": "branch:main",
                "type": "branch",
                "complete": True,
                "missing": [],
                "repositories": {"zstack": {
                    "mirror": "zstack.git", "ref": "main", "status": "resolved", "commit": old_commit
                }},
            }), encoding="utf-8")

            result = subprocess.run([
                sys.executable, str(SCRIPT),
                "--mirror-root", str(mirrors),
                "--repository-map", str(repository_map),
                "--repository", "zstack",
                "--context-file", str(context),
                "show", "--path", "service.py",
            ], check=False, capture_output=True, text=True)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("branch_context_stale", result.stderr)


if __name__ == "__main__":
    unittest.main()
