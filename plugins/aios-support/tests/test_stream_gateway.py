from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN_ROOT / "scripts"
import sys
sys.path.insert(0, str(SCRIPTS))

from robot_gateway import GatewayError
from stream_gateway import (
    CardClient,
    GatewayService,
    IncomingMessage,
    ProcessGroupRunner,
    RedactingFilter,
    StateStore,
    load_credentials,
    parse_message,
    resolve_version,
)
from validate_stream_runtime import validate


def sdk_message(**overrides):
    values = {
        "message_type": "text",
        "text": SimpleNamespace(content="  dGPU 状态异常  "),
        "rich_text_content": None,
        "message_id": "m-1",
        "conversation_id": "c-1",
        "conversation_type": "2",
        "sender_staff_id": "u-1",
        "sender_corp_id": "corp-1",
        "robot_code": "robot-1",
        "is_in_at_list": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def incoming(msg_id="m-1", session="u-1"):
    return IncomingMessage(msg_id, "c-1", "1", session, "corp", "robot", "问题", True, sdk_message())


class MessageSemanticsTest(unittest.TestCase):
    def test_group_requires_at_and_preserves_identity(self):
        self.assertIsNone(parse_message(sdk_message(is_in_at_list=False)))
        parsed = parse_message(sdk_message())
        self.assertEqual("dGPU 状态异常", parsed.text)
        self.assertEqual("m-1", parsed.msg_id)
        self.assertEqual("group:c-1:u-1", parsed.session_key)
        self.assertEqual(("corp-1", "robot-1"), (parsed.sender_corp_id, parsed.robot_code))

    def test_direct_message_accepts_text_without_at(self):
        parsed = parse_message(sdk_message(conversation_type="1", is_in_at_list=False))
        self.assertEqual("dm:u-1", parsed.session_key)

    def test_rich_text_uses_only_text_fragments(self):
        parsed = parse_message(sdk_message(
            message_type="richText", text=None,
            rich_text_content=SimpleNamespace(rich_text_list=[{"text": "vLLM"}, {"downloadCode": "x"}, {"text": "日志"}]),
        ))
        self.assertEqual("vLLM  日志", parsed.text)

    def test_unsupported_or_incomplete_messages_are_ignored(self):
        self.assertIsNone(parse_message(sdk_message(message_type="picture")))
        self.assertIsNone(parse_message(sdk_message(message_id="")))
        self.assertIsNone(parse_message(sdk_message(conversation_type="3")))


class StateStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self.temp.name) / "state.db", ttl_seconds=60, max_turns=2, max_chars=20)

    def tearDown(self):
        self.temp.cleanup()

    def test_message_id_is_claimed_once_across_store_instances(self):
        self.assertTrue(self.store.claim("same-id", "dm:u"))
        second = StateStore(self.store.path)
        self.assertFalse(second.claim("same-id", "dm:u"))

    def test_history_is_bounded_and_expires(self):
        self.store.add_turn("dm:u", "q1", "a1", "5.5.28")
        self.store.add_turn("dm:u", "q2", "a2", "5.5.30")
        self.store.add_turn("dm:u", "q3", "a3", "5.5.30")
        self.assertEqual(["q2", "q3"], [turn["question"] for turn in self.store.history("dm:u")])
        self.assertEqual([], self.store.history("dm:u", now=time.time() + 61))

    def test_history_character_budget_keeps_latest_turn(self):
        self.store.max_chars = 5
        self.store.add_turn("dm:u", "old", "answer", "5.5.28")
        self.store.add_turn("dm:u", "new", "answer", "5.5.30")
        self.assertEqual(["new"], [turn["question"] for turn in self.store.history("dm:u")])

    def test_followup_inherits_version_but_explicit_version_wins(self):
        versions = Path(self.temp.name) / "versions.json"
        versions.write_text(json.dumps({"version_sets": {"5.5.28": {}, "5.5.30": {}}}), encoding="utf-8")
        self.assertEqual("5.5.28", resolve_version("继续看这个问题", "5.5.30", "5.5.28", versions))
        self.assertEqual("5.5.30", resolve_version("AIOS 5.5.30 怎么处理", "5.5.30", "5.5.28", versions))

    def test_upgrade_question_uses_target_version(self):
        versions = Path(self.temp.name) / "upgrade-versions.json"
        versions.write_text(
            json.dumps({"version_sets": {"5.5.22": {}, "5.5.30": {}}}), encoding="utf-8"
        )
        self.assertEqual(
            "5.5.30",
            resolve_version("AIOS 5.5.22 升级 5.5.30 后指标变化", "5.5.30", None, versions),
        )


class FakeCards:
    def __init__(self):
        self.events = []
        self.counter = 0

    async def create(self, item):
        self.counter += 1
        self.events.append((item.msg_id, "create"))
        return self, f"card-{self.counter}"

    async def stage(self, handle, query, stage):
        self.events.append((handle[1], stage))

    async def finish(self, handle, query, content):
        self.events.append((handle[1], "FINISHED", content))

    async def fail(self, handle, query, content="failed"):
        self.events.append((handle[1], "FAILED"))


class FakeRunner:
    def __init__(self, gate=None, tracker=None, delay=0.02):
        self.gate = gate
        self.tracker = tracker
        self.delay = delay

    async def run(self, policy, prompt, code_lookup):
        session = prompt.split("Sanitized question:\n", 1)[1].splitlines()[0]
        if self.tracker is not None:
            self.tracker["active"] += 1
            self.tracker["peak"] = max(self.tracker["peak"], self.tracker["active"])
            self.tracker.setdefault("started", []).append(session)
        if self.gate:
            await self.gate.wait()
        await asyncio.sleep(self.delay)
        if self.tracker is not None:
            self.tracker["active"] -= 1
        return "结论"

    async def close(self):
        pass


class FailingRunner(FakeRunner):
    async def run(self, policy, prompt, code_lookup):
        raise GatewayError("test_failure")


class UnexpectedRunner(FakeRunner):
    async def run(self, policy, prompt, code_lookup):
        raise AssertionError("model must not run for /new")


class CapturingRunner(FakeRunner):
    def __init__(self):
        super().__init__()
        self.prompts = []

    async def run(self, policy, prompt, code_lookup):
        self.prompts.append((prompt, code_lookup))
        return "对比结论"


class SchedulerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.versions = self.root / "versions.json"
        self.versions.write_text(json.dumps({"version_sets": {"5.5.30": {}}}), encoding="utf-8")
        self.policy = {
            "default_version": "5.5.30", "audience": "internal",
            "timeout_seconds": 1, "workspace": str(self.root), "model": "fake",
        }

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_duplicate_never_creates_second_card_or_runs_model(self):
        cards, runner = FakeCards(), FakeRunner()
        service = GatewayService(StateStore(self.root / "s.db"), self.policy, self.versions, cards, runner, 1, 2)
        service.start()
        self.assertEqual("accepted", service.submit(incoming()))
        self.assertEqual("duplicate", service.submit(incoming()))
        await service.join()
        await service.close()
        self.assertEqual(1, len([event for event in cards.events if event[1] == "create"]))

    async def test_bounded_queue_rejects_excess_immediately(self):
        replies = []
        service = GatewayService(StateStore(self.root / "q.db"), self.policy, self.versions, FakeCards(), FakeRunner(), 1, 1)
        async def reply_busy(item):
            replies.append(item.msg_id)
        service.busy_reply = reply_busy
        service.start()
        self.assertEqual("accepted", service.submit(incoming("m1")))
        self.assertEqual("busy", service.submit(incoming("m2")))
        await service.busy_queue.join()
        await service.close()
        self.assertEqual(["m2"], replies)

    async def test_same_session_serializes_while_other_session_runs_in_parallel(self):
        tracker = {"active": 0, "peak": 0}
        service = GatewayService(StateStore(self.root / "p.db"), self.policy, self.versions, FakeCards(), FakeRunner(tracker=tracker), 3, 6)
        service.start()
        service.submit(incoming("m1", "same"))
        service.submit(incoming("m2", "same"))
        service.submit(incoming("m3", "other"))
        await service.join()
        await service.close()
        self.assertEqual(2, tracker["peak"])

    async def test_card_shows_all_stages_and_finishes(self):
        cards = FakeCards()
        service = GatewayService(StateStore(self.root / "c.db"), self.policy, self.versions, cards, FakeRunner(), 1, 2)
        service.start()
        service.submit(incoming())
        await service.join()
        await service.close()
        stages = " ".join(str(event[1]) for event in cards.events)
        self.assertIn("解析版本与问题", stages)
        self.assertIn("检索 AIOS 5.5.30", stages)
        self.assertIn("生成结论", stages)
        self.assertIn("FINISHED", stages)

    async def test_soft_timeout_keeps_work_running_and_finishes_later(self):
        cards = FakeCards()
        self.policy["timeout_seconds"] = 0.01
        service = GatewayService(
            StateStore(self.root / "background.db"), self.policy, self.versions,
            cards, FakeRunner(delay=0.04), 1, 2,
        )
        service.start()
        service.submit(incoming())
        await service.join()
        await service.close()
        stages = [event[1] for event in cards.events]
        self.assertIn("问题较复杂，已转后台查询，完成后自动返回", stages)
        self.assertIn("FINISHED", stages)

    async def test_finished_answer_has_version_header_without_source_appendix(self):
        class AnswerRunner(FakeRunner):
            async def run(self, policy, prompt, code_lookup):
                return "结论\n\n信息来源：本地五仓快照\n\n依据\n- 源码：premium/X.java"

        cards = FakeCards()
        service = GatewayService(
            StateStore(self.root / "format.db"), self.policy, self.versions,
            cards, AnswerRunner(), 1, 2,
        )
        service.start()
        service.submit(incoming())
        await service.join()
        await service.close()
        content = next(event[2] for event in cards.events if event[1] == "FINISHED")
        self.assertTrue(content.startswith("分析版本：AIOS 5.5.30（当前最新发布版）"))
        self.assertNotIn("信息来源", content)
        self.assertNotIn("依据", content)

    async def test_runner_failure_marks_card_failed(self):
        cards = FakeCards()
        service = GatewayService(StateStore(self.root / "f.db"), self.policy, self.versions, cards, FailingRunner(), 1, 2)
        service.start()
        service.submit(incoming())
        await service.join()
        await service.close()
        self.assertIn("FAILED", [event[1] for event in cards.events])

    async def test_new_command_clears_history_without_running_model(self):
        cards = FakeCards()
        store = StateStore(self.root / "new.db")
        store.add_turn("dm:u-1", "旧问题", "旧答案", "5.5.22")
        service = GatewayService(store, self.policy, self.versions, cards, UnexpectedRunner(), 1, 2)
        service.start()
        item = incoming()
        item = IncomingMessage(
            item.msg_id, item.conversation_id, item.conversation_type, item.sender_staff_id,
            item.sender_corp_id, item.robot_code, "/new", item.mentioned, item.sdk_message,
        )
        service.submit(item)
        await service.join()
        await service.close()
        self.assertEqual([], store.history(item.session_key))
        content = next(event[2] for event in cards.events if event[1] == "FINISHED")
        self.assertIn("已开始新的 AIOS 支持会话", content)

    async def test_upgrade_comparison_collects_both_version_snapshots(self):
        self.versions.write_text(
            json.dumps({"version_sets": {"5.5.22": {}, "5.5.30": {}}}), encoding="utf-8"
        )
        cards, runner = FakeCards(), CapturingRunner()
        service = GatewayService(StateStore(self.root / "upgrade.db"), self.policy, self.versions, cards, runner, 1, 2)
        service.start()
        base = incoming()
        item = IncomingMessage(
            base.msg_id, base.conversation_id, base.conversation_type, base.sender_staff_id,
            base.sender_corp_id, base.robot_code,
            "AIOS 5.5.22 升级 5.5.30 后 metrics 有什么变化", base.mentioned, base.sdk_message,
        )
        with mock.patch(
            "stream_gateway.collect_code_evidence",
            side_effect=lambda policy, version, version_sets, question: f"evidence-{version}",
        ) as collect:
            service.submit(item)
            await service.join()
        await service.close()
        self.assertEqual(["5.5.22", "5.5.30"], [call.args[1] for call in collect.call_args_list])
        self.assertTrue(runner.prompts[0][1])
        self.assertIn("evidence-5.5.22", runner.prompts[0][0])
        self.assertIn("evidence-5.5.30", runner.prompts[0][0])


class ProcessGroupTest(unittest.IsolatedAsyncioTestCase):
    async def test_success_reads_final_answer_with_bounded_pipes(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "codex"
            fake.write_text(
                "#!/usr/bin/env python3\nimport pathlib,sys\n"
                "args=sys.argv\nout=pathlib.Path(args[args.index('-o')+1])\n"
                "sys.stdin.read()\nout.write_text('answer')\nprint('ok')\n",
                encoding="utf-8",
            )
            fake.chmod(0o700)
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            answer = await ProcessGroupRunner(fake, 2).run(
                {"model": "fake", "workspace": str(workspace)}, "q", True
            )
            self.assertEqual("answer", answer)

    async def test_codex_uses_configured_workspace_as_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            fake = root / "codex"
            fake.write_text(
                "#!/usr/bin/env python3\nimport json,pathlib,sys\n"
                "args=sys.argv\nout=pathlib.Path(args[args.index('-o')+1])\n"
                "out.write_text(args[args.index('-C')+1])\nsys.stdin.read()\n",
                encoding="utf-8",
            )
            fake.chmod(0o700)
            answer = await ProcessGroupRunner(fake, 2).run(
                {"model": "fake", "workspace": str(workspace)}, "q", False
            )
            self.assertEqual(str(workspace), answer)

    async def test_oversized_output_is_rejected_and_process_reaped(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "codex"
            fake.write_text("#!/usr/bin/env python3\nprint('x'*10000)\n", encoding="utf-8")
            fake.chmod(0o700)
            with self.assertRaisesRegex(GatewayError, "output_too_large"):
                await ProcessGroupRunner(fake, 2, output_limit=100).run(
                    {"model": "fake", "workspace": directory}, "q", False
                )
    async def test_timeout_kills_descendant_process_group(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child_pid = root / "child.pid"
            fake = root / "codex"
            fake.write_text(
                "#!/usr/bin/env python3\nimport pathlib,subprocess,sys,time\n"
                "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
                "pathlib.Path(sys.stdin.read()).write_text(str(p.pid))\ntime.sleep(60)\n",
                encoding="utf-8",
            )
            fake.chmod(0o700)
            runner = ProcessGroupRunner(fake, timeout_seconds=1)
            with self.assertRaisesRegex(GatewayError, "query_timeout"):
                await runner.run({"model": "fake", "workspace": directory}, str(child_pid), False)
            pid = int(child_pid.read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    async def test_cancel_kills_descendant_process_group(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child_pid = root / "child.pid"
            fake = root / "codex"
            fake.write_text(
                "#!/usr/bin/env python3\nimport pathlib,subprocess,sys,time\n"
                "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
                "pathlib.Path(sys.stdin.read()).write_text(str(p.pid))\ntime.sleep(60)\n",
                encoding="utf-8",
            )
            fake.chmod(0o700)
            runner = ProcessGroupRunner(fake, timeout_seconds=60)
            task = asyncio.create_task(runner.run(
                {"model": "fake", "workspace": directory}, str(child_pid), False
            ))
            for _ in range(100):
                if child_pid.exists():
                    break
                await asyncio.sleep(0.01)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            pid = int(child_pid.read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)


class SecurityBoundaryTest(unittest.TestCase):
    def test_credentials_require_service_owner_and_0600(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            path.write_text(json.dumps({"appKey": "key", "appSecret": "value"}), encoding="utf-8")
            path.chmod(0o644)
            with self.assertRaisesRegex(GatewayError, "permissions"):
                load_credentials(path)
            path.chmod(0o600)
            self.assertEqual(("key", "value"), load_credentials(path))

    def test_invalid_credentials_never_expose_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            path.write_text("not-json", encoding="utf-8")
            path.chmod(0o600)
            with self.assertRaisesRegex(GatewayError, "credentials_invalid") as caught:
                load_credentials(path)
            self.assertNotIn("not-json", str(caught.exception))

    def test_log_filter_redacts_sensitive_values(self):
        record = logging.LogRecord("test", logging.ERROR, "", 0, "appSecret=do-not-log", (), None)
        RedactingFilter().filter(record)
        self.assertNotIn("do-not-log", record.getMessage())

        ticket_record = logging.LogRecord(
            "test", logging.INFO, "", 0, "endpoint={'ticket': 'short-lived-value'}", (), None
        )
        RedactingFilter().filter(ticket_record)
        self.assertNotIn("short-lived-value", ticket_record.getMessage())

    def test_card_variables_match_published_template(self):
        data = CardClient.data("问题", "排队中", "结论")
        self.assertEqual({"lastMessage", "config", "query", "preparations", "charts", "content"}, set(data))


class OfficialCardAdapterTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_stage_finish_and_fail_use_ai_card_apis(self):
        calls = []

        class FakeReplier:
            def __init__(self, client, message):
                calls.append(("init", client, message))

            async def async_start(self, template, data, support_forward):
                calls.append(("start", template, data, support_forward))
                return "card-id"

            async def async_put_card_data(self, card_id, data):
                calls.append(("stage", card_id, data))

            async def async_streaming(self, card_id, key, value, append, finished, failed):
                calls.append(("stream", card_id, key, value, append, finished, failed))

            async def async_finish(self, card_id, data):
                calls.append(("finish", card_id, data))

            async def async_fail(self, card_id, data):
                calls.append(("fail", card_id, data))

        fake_module = SimpleNamespace(AICardReplier=FakeReplier)
        with mock.patch.dict(sys.modules, {"dingtalk_stream": fake_module}):
            cards = CardClient("client")
            handle = await cards.create(incoming())
            await cards.stage(handle, "问题", "检索")
            await cards.finish(handle, "问题", "结论")
            await cards.fail(handle, "问题")
        self.assertEqual(
            ["init", "start", "stream", "stage", "stream", "finish", "stream", "fail", "stream"],
            [call[0] for call in calls],
        )
        self.assertFalse(calls[1][3])
        self.assertIn("已接收", calls[1][2]["content"])
        self.assertEqual("content", calls[2][2])
        self.assertIn("已接收", calls[2][3])
        self.assertEqual("结论", calls[5][2]["content"])
        self.assertEqual("结论", calls[6][3])
        self.assertTrue(calls[6][5])

    async def test_empty_card_id_fails_before_model_work(self):
        class EmptyReplier:
            def __init__(self, client, message):
                pass

            async def async_start(self, template, data, support_forward):
                return ""

        with mock.patch.dict(sys.modules, {"dingtalk_stream": SimpleNamespace(AICardReplier=EmptyReplier)}):
            with self.assertRaisesRegex(GatewayError, "card_create_failed"):
                await CardClient("client").create(incoming())


class RuntimeValidationTest(unittest.TestCase):

    def test_startup_validator_checks_policy_version_credentials_template_and_codex(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            policy = root / "policy.json"
            policy.write_text(json.dumps({
                "schema_version": 1, "audience": "internal", "tenant_id": None,
                "workspace": str(workspace), "model": "gpt-5.6-sol", "timeout_seconds": 130,
                "default_version": "5.5.30",
            }), encoding="utf-8")
            versions = root / "versions.json"
            versions.write_text(json.dumps({"version_sets": {"5.5.30": {}}}), encoding="utf-8")
            credentials = root / "credentials.json"
            credentials.write_text(json.dumps({"appKey": "key", "appSecret": "secret-value"}), encoding="utf-8")
            credentials.chmod(0o600)
            codex = root / "codex"
            codex.write_text("#!/bin/sh\n", encoding="utf-8")
            codex.chmod(0o700)
            environment = {
                "AIOS_GATEWAY_POLICY": str(policy), "AIOS_VERSION_SETS_FILE": str(versions),
                "AIOS_DINGTALK_CREDENTIALS": str(credentials),
                "AIOS_CARD_TEMPLATE_ID": "513ff894-423b-4178-9ea6-ed17600b809f.schema",
                "AIOS_CODEX_BIN": str(codex),
            }
            with mock.patch.dict(os.environ, environment, clear=False):
                validate()

    def test_startup_validator_rejects_wrong_template(self):
        with mock.patch.dict(os.environ, {"AIOS_CARD_TEMPLATE_ID": "wrong"}, clear=False), \
             mock.patch("validate_stream_runtime.load_policy", return_value={"default_version": "5.5.30"}), \
             mock.patch("validate_stream_runtime.select_version"), \
             mock.patch("validate_stream_runtime.load_credentials"):
            with self.assertRaisesRegex(GatewayError, "template_id_invalid"):
                validate()


if __name__ == "__main__":
    unittest.main()
