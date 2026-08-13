from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from resolve_code_context import build_branch_set, resolve_context  # noqa: E402
from validate_version_sets import validate  # noqa: E402


def run(*args: str, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


class VersionResolverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.mirror_root = self.root / "mirrors"
        self.mirror_root.mkdir()
        self.repository_map = {
            "repositories": {
                "aios": {
                    "mirror": "aios.git",
                    "default_ref": "master",
                    "branch_policy": "fixed",
                },
                "zstack": {
                    "mirror": "zstack.git",
                    "branch_policy": "versioned",
                },
            }
        }
        self.aios_commit = self.create_mirror("aios", "master", "aios.txt")
        self.zstack_commit = self.create_mirror("zstack", "feature-5.5.28-aios", "zstack.txt")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create_mirror(self, name: str, branch: str, filename: str) -> str:
        working = self.root / f"{name}-working"
        working.mkdir()
        run("git", "init", cwd=working)
        run("git", "checkout", "-b", branch, cwd=working)
        run("git", "config", "user.name", "Test", cwd=working)
        run("git", "config", "user.email", "test@example.com", cwd=working)
        (working / filename).write_text("ModelService\n", encoding="utf-8")
        run("git", "add", filename, cwd=working)
        run("git", "commit", "-m", "fixture", cwd=working)
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=working, check=True, capture_output=True, text=True
        ).stdout.strip()
        run("git", "clone", "--mirror", str(working), str(self.mirror_root / f"{name}.git"), cwd=self.root)
        return commit

    def test_development_branch_resolves_each_repository_without_checkout(self) -> None:
        version_set = build_branch_set(self.repository_map, "feature-5.5.28-aios")
        context = resolve_context(self.repository_map, version_set, self.mirror_root, "branch:test")

        self.assertTrue(context["complete"])
        self.assertEqual(self.aios_commit, context["repositories"]["aios"]["commit"])
        self.assertEqual(self.zstack_commit, context["repositories"]["zstack"]["commit"])

    def test_missing_branch_is_reported_without_master_fallback(self) -> None:
        version_set = build_branch_set(self.repository_map, "feature-does-not-exist")
        context = resolve_context(self.repository_map, version_set, self.mirror_root, "branch:missing")

        self.assertFalse(context["complete"])
        self.assertEqual("branch_missing", context["repositories"]["zstack"]["status"])
        self.assertIsNone(context["repositories"]["zstack"]["commit"])

    def test_release_requires_pinned_commits(self) -> None:
        version_set = {
            "type": "release",
            "repositories": {
                "aios": {"ref": "master", "commit": self.aios_commit},
                "zstack": {"ref": "feature-5.5.28-aios", "commit": None},
            },
        }
        context = resolve_context(self.repository_map, version_set, self.mirror_root, "5.5.28")

        self.assertFalse(context["complete"])
        self.assertEqual("release_commit_unpinned", context["repositories"]["zstack"]["status"])

    def test_schema_validator_rejects_unpinned_release(self) -> None:
        version_sets = {
            "version_sets": {
                "5.5.28": {
                    "type": "release",
                    "repositories": {
                        "aios": {"ref": "master", "commit": self.aios_commit},
                        "zstack": {"ref": "feature-5.5.28-aios", "commit": None},
                    },
                }
            }
        }
        errors = validate(self.repository_map, version_sets)

        self.assertIn("5.5.28/zstack: release commit must be pinned", errors)

    def test_release_commit_must_match_declared_ref(self) -> None:
        version_set = {
            "type": "release",
            "repositories": {
                "aios": {"ref": "missing-release-ref", "commit": self.aios_commit},
                "zstack": {"ref": "feature-5.5.28-aios", "commit": self.zstack_commit},
            },
        }
        context = resolve_context(self.repository_map, version_set, self.mirror_root, "5.5.28")

        self.assertFalse(context["complete"])
        self.assertEqual("commit_ref_mismatch", context["repositories"]["aios"]["status"])

    def test_release_commit_remains_valid_when_branch_advances(self) -> None:
        working = self.root / "zstack-working"
        (working / "later.txt").write_text("later\n", encoding="utf-8")
        run("git", "add", "later.txt", cwd=working)
        run("git", "commit", "-m", "later", cwd=working)
        mirror = self.mirror_root / "zstack.git"
        run("git", "fetch", str(working), "feature-5.5.28-aios:feature-5.5.28-aios", cwd=mirror)
        version_set = {
            "type": "release",
            "repositories": {
                "aios": {"ref": "master", "commit": self.aios_commit},
                "zstack": {"ref": "feature-5.5.28-aios", "commit": self.zstack_commit},
            },
        }

        context = resolve_context(self.repository_map, version_set, self.mirror_root, "5.5.28")

        self.assertTrue(context["complete"])
        self.assertEqual(self.zstack_commit, context["repositories"]["zstack"]["commit"])


if __name__ == "__main__":
    unittest.main()
