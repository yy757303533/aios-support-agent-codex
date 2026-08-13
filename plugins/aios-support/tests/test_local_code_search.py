from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from search_local_code import relevant_path, search, search_scopes  # noqa: E402


class LocalCodeSearchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.mirrors = self.root / "mirrors"
        self.mirrors.mkdir()
        self.repository_map = self.root / "repository-map.json"
        repositories = {}
        version_repositories = {}
        for name in ("aios", "premium"):
            work = self.root / f"{name}-work"
            work.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=work, check=True)
            subprocess.run(["git", "symbolic-ref", "HEAD", "refs/heads/master"], cwd=work, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=work, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=work, check=True)
            target = work / ("server" if name == "aios" else "plugin-premium/ai-service")
            target.mkdir(parents=True)
            (target / "gpu.py").write_text("dGPU initialization requires GuestTools\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=work, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=work, check=True)
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=work, text=True).strip()
            mirror_name = f"{name}.git"
            subprocess.run(["git", "clone", "-q", "--bare", str(work), str(self.mirrors / mirror_name)], check=True)
            repositories[name] = {"mirror": mirror_name, "default_ref": "master", "branch_policy": "fixed"}
            version_repositories[name] = {"ref": "master", "commit": commit}
        self.repository_map.write_text(json.dumps({"repositories": repositories}), encoding="utf-8")
        self.version_sets = self.root / "version-sets.json"
        self.version_sets.write_text(
            json.dumps({"version_sets": {"5.5.30": {"type": "release", "repositories": version_repositories}}}),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_searches_aios_entire_repo_and_dynamic_ai_prefix(self) -> None:
        result = search(
            self.mirrors,
            self.repository_map,
            self.version_sets,
            "5.5.30",
            ["dGPU", "GuestTools"],
            None,
            20,
        )
        self.assertTrue(result["complete"])
        self.assertEqual({"aios", "premium"}, {match["repository"] for match in result["matches"]})
        self.assertEqual(["<entire-repository>"], result["scanned"][0]["scopes"])
        self.assertIn(":(glob,icase)**/ai*/**", result["scanned"][1]["scopes"])

    def test_rejects_unknown_version(self) -> None:
        with self.assertRaisesRegex(ValueError, "version_unknown"):
            search(self.mirrors, self.repository_map, self.version_sets, "5.5.29", ["dGPU"], None, 20)

    def test_gpu_and_guesttools_scopes_are_topic_driven(self) -> None:
        scopes = search_scopes("premium", ["dGPU", "性能优化工具"])
        self.assertIn(":(glob,icase)**/*gpu*/**", scopes)
        self.assertIn(":(glob,icase)**/*guesttool*/**", scopes)

    def test_busy_first_repository_does_not_starve_later_repositories(self) -> None:
        result = search(
            self.mirrors,
            self.repository_map,
            self.version_sets,
            "5.5.30",
            ["dGPU"],
            None,
            2,
        )
        self.assertEqual(["aios", "premium"], [match["repository"] for match in result["matches"]])

    def test_filters_generic_terms_and_generated_paths(self) -> None:
        result = search(self.mirrors, self.repository_map, self.version_sets, "5.5.30", ["version", "dGPU"], None, 10)
        self.assertEqual(["dGPU"], result["terms"])
        self.assertFalse(relevant_path("packages/app/@mf-types/generated.d.ts"))
        self.assertFalse(relevant_path("packages/app/public/i18n/zh-CN.json"))
        self.assertTrue(relevant_path("packages/app/ai-store/gpu.ts"))


if __name__ == "__main__":
    unittest.main()
