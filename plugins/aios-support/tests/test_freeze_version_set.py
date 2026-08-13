from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN_ROOT / "scripts" / "freeze_version_set.py"
REPOSITORY_MAP = PLUGIN_ROOT / "config" / "repository-map.json"


class FreezeVersionSetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.mirrors = self.root / "mirrors"
        self.mirrors.mkdir()
        self.refs: dict[str, str] = {}
        repository_map = json.loads(REPOSITORY_MAP.read_text(encoding="utf-8"))
        for name, settings in repository_map["repositories"].items():
            mirror = self.mirrors / settings["mirror"]
            subprocess.run(["git", "init", "--bare", str(mirror)], check=True, capture_output=True)
            work = self.root / f"work-{name}"
            subprocess.run(["git", "clone", str(mirror), str(work)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(work), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(work), "config", "user.name", "Test"], check=True)
            (work / "file.txt").write_text(name, encoding="utf-8")
            subprocess.run(["git", "-C", str(work), "add", "file.txt"], check=True)
            subprocess.run(["git", "-C", str(work), "commit", "-m", "fixture"], check=True, capture_output=True)
            ref = "master" if name == "aios" else "feature-5.5.28-aios"
            subprocess.run(["git", "-C", str(work), "branch", "-M", ref], check=True)
            subprocess.run(["git", "-C", str(work), "push", "origin", ref], check=True, capture_output=True)
            self.refs[name] = ref
        self.refs_path = self.root / "refs.json"
        self.refs_path.write_text(json.dumps({"version": "5.5.28", "refs": self.refs}), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_freezes_all_repository_refs_to_full_commits_with_provenance(self) -> None:
        output = self.root / "version-sets.json"
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--repository-map",
                str(REPOSITORY_MAP),
                "--mirror-root",
                str(self.mirrors),
                "--release-refs",
                str(self.refs_path),
                "--output",
                str(output),
                "--approved-by",
                "release-owner",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(output.read_text(encoding="utf-8"))
        release = payload["version_sets"]["5.5.28"]
        self.assertEqual("release", release["type"])
        self.assertEqual("manual_ref_snapshot", release["provenance"]["method"])
        self.assertEqual("release-owner", release["provenance"]["approved_by"])
        self.assertEqual(set(self.refs), set(release["repositories"]))
        for repository in release["repositories"].values():
            self.assertRegex(repository["commit"], r"^[0-9a-f]{40}$")

    def test_missing_ref_fails_without_overwriting_existing_output(self) -> None:
        refs = json.loads(self.refs_path.read_text(encoding="utf-8"))
        refs["refs"]["premium"] = "missing-branch"
        self.refs_path.write_text(json.dumps(refs), encoding="utf-8")
        output = self.root / "version-sets.json"
        output.write_text("preserve", encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--repository-map",
                str(REPOSITORY_MAP),
                "--mirror-root",
                str(self.mirrors),
                "--release-refs",
                str(self.refs_path),
                "--output",
                str(output),
                "--approved-by",
                "release-owner",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(2, result.returncode)
        self.assertEqual("preserve", output.read_text(encoding="utf-8"))
        self.assertNotIn("missing-branch", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
