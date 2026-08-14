from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
GATEWAY = PLUGIN_ROOT / "scripts" / "robot_gateway.py"
class RobotGatewayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.marker = self.root / "called"
        self.fake_codex = self.root / "codex"
        self.fake_codex.write_text(
            """#!/usr/bin/env python3
import os
import pathlib
import sys

pathlib.Path(os.environ['FAKE_CODEX_MARKER']).touch()
pathlib.Path(os.environ['FAKE_CODEX_ARGS']).write_text('\\n'.join(sys.argv), encoding='utf-8')
pathlib.Path(os.environ['FAKE_CODEX_MODE']).write_text(os.environ['AIOS_ZDEV_MODE'], encoding='utf-8')
pathlib.Path(os.environ['FAKE_CODEX_PROMPT']).write_text(sys.stdin.read(), encoding='utf-8')
output = pathlib.Path(sys.argv[sys.argv.index('-o') + 1])
output.write_text(os.environ['FAKE_CODEX_ANSWER'], encoding='utf-8')
sys.exit(int(os.environ.get('FAKE_CODEX_EXIT', '0')))
""",
            encoding="utf-8",
        )
        self.fake_codex.chmod(0o700)
        self.policy = self.root / "policy.json"
        self.args_file = self.root / "args"
        self.mode_file = self.root / "mode"
        self.prompt_file = self.root / "prompt"
        self.search_script = self.root / "search.py"
        self.search_script.write_text(
            "import json\nprint(json.dumps({'version':'5.5.30','complete':True,'matches':[{'repository':'aios','path':'devops/run.sh','line':339,'text':'dGPU profile'}],'evidence_files':[{'repository':'aios','path':'devops/run.sh','line_start':331,'line_end':347,'content':'339: dGPU profile'}]}))\n",
            encoding="utf-8",
        )
        self.mirror_root = self.root / "mirrors"
        self.mirror_root.mkdir()
        self.repository_map = self.root / "repository-map.json"
        self.repository_map.write_text('{"repositories":{}}', encoding="utf-8")
        self.version_sets = self.root / "version-sets.json"
        self.version_sets.write_text(
            json.dumps({"version_sets": {"5.5.28": {}, "5.5.30": {}}}),
            encoding="utf-8",
        )
        self.policy.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "audience": "internal",
                    "tenant_id": None,
                    "workspace": str(PLUGIN_ROOT),
                    "model": "test-model",
                    "timeout_seconds": 30,
                    "default_version": "5.5.30",
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_gateway(self, question: str, answer: str, exit_code: int = 0) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            {
                "AIOS_GATEWAY_POLICY": str(self.policy),
                "AIOS_CODEX_BIN": str(self.fake_codex),
                "AIOS_VERSION_SETS_FILE": str(self.version_sets),
                "FAKE_CODEX_MARKER": str(self.marker),
                "FAKE_CODEX_ARGS": str(self.args_file),
                "FAKE_CODEX_MODE": str(self.mode_file),
                "FAKE_CODEX_PROMPT": str(self.prompt_file),
                "FAKE_CODEX_ANSWER": answer,
                "FAKE_CODEX_EXIT": str(exit_code),
                "AIOS_LOCAL_SEARCH_SCRIPT": str(self.search_script),
                "AIOS_CODE_MIRROR_ROOT": str(self.mirror_root),
                "AIOS_REPOSITORY_MAP": str(self.repository_map),
            }
        )
        return subprocess.run(
            [sys.executable, str(GATEWAY), question],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

    def test_returns_plain_internal_answer(self) -> None:
        result = self.run_gateway("AIOS 目标版本支持什么？", "该能力在目标版本中可用。")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(self.marker.exists())
        self.assertEqual("该能力在目标版本中可用。\n", result.stdout)

    def test_rejects_secret_input_without_invoking_codex(self) -> None:
        secret_name = "api_" + "key"
        result = self.run_gateway(f"{secret_name}=" + ("x" * 24), "不应调用")

        self.assertEqual(0, result.returncode)
        self.assertFalse(self.marker.exists())
        self.assertEqual("请求包含不能安全处理的信息，请去除凭据或客户标识后重试。\n", result.stdout)

    def test_redacts_log_identifiers_and_still_invokes_codex(self) -> None:
        result = self.run_gateway("host mn-prod-01 failed at 192.0.2.10", "日志定位结果")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(self.marker.exists())
        self.assertEqual("日志定位结果\n", result.stdout)

    def test_model_failure_reports_runtime_error_not_security_downgrade(self) -> None:
        result = self.run_gateway("正常问题", "", exit_code=1)

        self.assertEqual(0, result.returncode)
        self.assertTrue(self.marker.exists())
        self.assertEqual("模型服务暂时不可用，请稍后重试。\n", result.stdout)

    def test_plain_text_does_not_require_answer_contract(self) -> None:
        result = self.run_gateway("正常问题", "直接回答，不要求 JSON。")

        self.assertEqual(0, result.returncode)
        self.assertEqual("直接回答，不要求 JSON。\n", result.stdout)

    def test_domain_support_question_uses_precomputed_local_evidence(self) -> None:
        result = self.run_gateway("AIOS 5.5.30 的 dGPU 为什么未初始化？", "本地结论")

        self.assertEqual(0, result.returncode)
        self.assertEqual("evidence", self.mode_file.read_text(encoding="utf-8"))

    def test_model_download_question_uses_precomputed_local_evidence(self) -> None:
        questions = (
            "AIOS 5.5.30 的模型下载逻辑在哪里？",
            "AIOS 5.5.30 的下载任务暂停后如何清理？",
            "AIOS 5.5.30 的模型中心如何下载模型？",
        )
        for question in questions:
            with self.subTest(question=question):
                result = self.run_gateway(question, "本地结论")

                self.assertEqual(0, result.returncode)
                self.assertEqual("evidence", self.mode_file.read_text(encoding="utf-8"))
                self.assertIn("devops/run.sh", self.prompt_file.read_text(encoding="utf-8"))

    def test_explicit_jira_question_keeps_zdev_available(self) -> None:
        result = self.run_gateway("请查询 Jira AIOS-123", "Jira 结论")

        self.assertEqual(0, result.returncode)
        self.assertEqual("support", self.mode_file.read_text(encoding="utf-8"))

    def test_gitlab_keyword_does_not_enable_remote_code_lookup(self) -> None:
        result = self.run_gateway("去 GitLab 搜索这段代码", "本地代码结论")

        self.assertEqual(0, result.returncode)
        self.assertEqual("support", self.mode_file.read_text(encoding="utf-8"))

    def test_explicit_code_sync_request_enables_controlled_refresh_tool(self) -> None:
        result = self.run_gateway("请同步本地五仓代码", "已更新")

        self.assertEqual(0, result.returncode)
        self.assertEqual("sync", self.mode_file.read_text(encoding="utf-8"))

    def test_missing_aios_version_uses_latest_snapshot(self) -> None:
        result = self.run_gateway("dGPU 为什么未初始化？GuestTools 是 5.5.0", "使用最新版本")

        self.assertEqual(0, result.returncode)
        self.assertTrue(self.marker.exists())

    def test_unknown_explicit_aios_version_does_not_fallback(self) -> None:
        result = self.run_gateway("AIOS 5.5.29 的行为是什么？", "不应调用")

        self.assertEqual(0, result.returncode)
        self.assertFalse(self.marker.exists())
        self.assertEqual("未配置 AIOS 5.5.29 的本地五仓快照，请先同步并冻结该版本。\n", result.stdout)

    def test_codex_always_runs_from_configured_workspace(self) -> None:
        self.run_gateway("请查源码调用链", "源码结论")
        source_arguments = self.args_file.read_text(encoding="utf-8").splitlines()
        self.assertIn("--ignore-rules", source_arguments)
        self.assertEqual(str(PLUGIN_ROOT), source_arguments[source_arguments.index("-C") + 1])
        source_prompt = self.prompt_file.read_text(encoding="utf-8")
        self.assertIn("devops/run.sh", source_prompt)
        self.assertIn("Do not call tools or inspect the filesystem", source_prompt)
        self.assertEqual("evidence", self.mode_file.read_text(encoding="utf-8"))

        self.run_gateway("dGPU 为什么未初始化", "知识结论")
        knowledge_arguments = self.args_file.read_text(encoding="utf-8").splitlines()
        self.assertEqual(str(PLUGIN_ROOT), knowledge_arguments[knowledge_arguments.index("-C") + 1])


if __name__ == "__main__":
    unittest.main()
