from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from sanitize_query import sanitize  # noqa: E402
from security_scan import scan  # noqa: E402
from validate_answer import validate as validate_answer  # noqa: E402
from validate_mcp_config import validate as validate_mcp  # noqa: E402


class McpPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = json.loads((PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8"))

    def test_checked_in_config_is_exact_read_only_policy(self) -> None:
        self.assertEqual([], validate_mcp(self.config))

    def test_rejects_write_tool_in_enabled_list(self) -> None:
        config = copy.deepcopy(self.config)
        config["mcpServers"]["zstack-bbs-support"]["enabled_tools"].append("bbs_create_thread")
        self.assertIn("zstack-bbs-support:enabled_tools_mismatch", validate_mcp(config))

    def test_rejects_static_authorization(self) -> None:
        config = copy.deepcopy(self.config)
        config["mcpServers"]["zstack-bbs-support"]["http_headers"]["Authorization"] = "invalid"
        self.assertIn("zstack-bbs-support:static_authorization_forbidden", validate_mcp(config))

    def test_rejects_unknown_server_and_url_drift(self) -> None:
        config = copy.deepcopy(self.config)
        config["mcpServers"]["unexpected"] = {}
        config["mcpServers"]["tavily_hikari"]["url"] = "https://example.invalid/mcp"
        errors = validate_mcp(config)
        self.assertIn("mcp_server_set_mismatch", errors)
        self.assertIn("tavily_hikari:url_mismatch", errors)

    def test_accepts_explicitly_disabled_unavailable_connectors(self) -> None:
        config = copy.deepcopy(self.config)
        config["mcpServers"]["zstack-bbs-support"]["enabled"] = False
        config["mcpServers"]["zstack_atlassian_shared"]["enabled"] = False
        self.assertEqual([], validate_mcp(config))

    def test_rejects_non_boolean_enabled_value(self) -> None:
        config = copy.deepcopy(self.config)
        config["mcpServers"]["zstack-bbs-support"]["enabled"] = "false"
        self.assertIn("zstack-bbs-support:enabled_invalid", validate_mcp(config))

    def test_rejects_hostile_config_types_without_crashing(self) -> None:
        self.assertEqual(["mcp_config_shape_invalid"], validate_mcp([]))
        config = copy.deepcopy(self.config)
        config["mcpServers"]["zstack-bbs-support"]["enabled_tools"] = [{}]
        self.assertIn("zstack-bbs-support:enabled_tools_invalid", validate_mcp(config))


class QuerySanitizationTest(unittest.TestCase):
    def test_redacts_identifiers_before_connector_search(self) -> None:
        result = sanitize(
            "host 172.20.19.213 and 8.8.8.8 customer.example.com user@example.com "
            "550e8400-e29b-41d4-a716-446655440000 0123456789abcdef0123456789abcdef failed ModelService"
        )
        self.assertTrue(result["safe"])
        self.assertNotIn("172.20.19.213", result["sanitized"])
        self.assertNotIn("user@example.com", result["sanitized"])
        self.assertNotIn("customer.example.com", result["sanitized"])
        self.assertNotIn("8.8.8.8", result["sanitized"])
        self.assertIn("ModelService", result["sanitized"])
        self.assertIn("org.zstack.ai.ModelService", sanitize("org.zstack.ai.ModelService failed")["sanitized"])
        self.assertEqual(2, result["redactions"]["ip_address"])

    def test_rejects_credential_material_without_echoing_it(self) -> None:
        credential = "Authorization: " + "Bearer " + ("x" * 32)
        result = sanitize(credential)
        self.assertEqual({"safe": False, "error": "credential_material_detected"}, result)
        self.assertNotIn("x" * 32, json.dumps(result))

    def test_redacts_ipv6_url_and_labeled_identifiers(self) -> None:
        original = "tenant acme-corp host mn-prod-01 at fe80::1 see https://service.unknown/path"
        result = sanitize(original)
        self.assertTrue(result["safe"])
        for value in ("acme-corp", "mn-prod-01", "fe80::1", "service.unknown"):
            self.assertNotIn(value, result["sanitized"])

    def test_rejects_unquoted_and_url_credentials(self) -> None:
        for value in (
            "api_key=" + "lowercase-secret-123456",
            "OPENAI_API_KEY=" + ("x" * 24),
            "TAVILY_HIKARI_TOKEN=" + ("x" * 24),
            "DB_PASSWORD=" + ("P" * 24),
            "SECRET_KEY=" + ("x" * 24),
            "mySecret=" + ("x" * 24),
            "dbPassword=" + ("x" * 24),
            "https://user:" + ("P" * 16) + "@example.com/path",
            "https://example.com/?access_token=" + ("x" * 16),
        ):
            self.assertFalse(sanitize(value)["safe"])


class AnswerGateTest(unittest.TestCase):
    def answer(self, audience: str = "sales") -> dict:
        return {
            "status": "answered",
            "audience": audience,
            "version": "5.5.28",
            "conclusion": "该功能在目标版本中可用。",
            "actions": [],
            "uncertainties": [],
            "completeness": "complete",
            "sources": [
                {
                    "type": "dingtalk_knowledge",
                    "title": "AIOS 产品资料",
                    "url": "https://alidocs.dingtalk.com/i/nodes/example",
                }
            ],
            "internal_sources": [],
        }

    def test_accepts_sales_answer_with_approved_source(self) -> None:
        self.assertEqual([], validate_answer(self.answer(), "sales"))

    def test_rejects_prompt_requested_audience_escalation(self) -> None:
        answer = self.answer("internal")
        self.assertIn("audience_not_authorized", validate_answer(answer, "sales"))

    def test_rejects_internal_details_in_sales_answer(self) -> None:
        answer = self.answer()
        answer["conclusion"] = "参考 ZSTAC-12345 和 172.20.19.213，commit " + ("a" * 40)
        errors = validate_answer(answer, "sales")
        self.assertIn("internal_marker_forbidden", errors)
        self.assertIn("external_identifier_forbidden", errors)

    def test_rejects_internal_sources_in_sales_answer(self) -> None:
        answer = self.answer()
        answer["internal_sources"] = [{"type": "jira", "title": "ZSTAC-12345"}]
        self.assertIn("internal_sources_forbidden", validate_answer(answer, "sales"))

    def test_rejects_internal_git_host_and_relative_code_path(self) -> None:
        answer = self.answer()
        answer["conclusion"] = "详情见 https://dev.zstack.io/project 和 zstack/plugin/ai/source.java"
        errors = validate_answer(answer, "sales")
        self.assertIn("internal_marker_forbidden", errors)

    def test_rejects_unexpected_debug_field(self) -> None:
        answer = self.answer()
        answer["raw_mcp_payload"] = {"debug": "value"}
        self.assertIn("answer_field_set_mismatch", validate_answer(answer, "sales"))

    def test_rejects_nested_payload_in_actions(self) -> None:
        answer = self.answer()
        answer["actions"] = [{"raw": "provider payload"}]
        self.assertIn("actions_item_invalid", validate_answer(answer, "sales"))

    def test_rejects_unsafe_markup(self) -> None:
        for payload in (
            "<script>alert(1)</script>",
            "<img src=x onerror=alert(1)>",
            "<svg onload=alert(1)>",
            "data:text/html,unsafe",
            "&lt;img src=x onerror=alert(1)&gt;",
            "&#60;svg onload=alert(1)&#62;",
            "%3Cimg%20src=x%20onerror=alert(1)%3E",
            "java%73cript:alert(1)",
            "%25253Cimg%252520src=x%252520onerror=alert(1)%25253E",
        ):
            answer = self.answer()
            answer["conclusion"] = payload
            self.assertIn("unsafe_markup_forbidden", validate_answer(answer, "sales"))

    def test_rejects_source_url_credentials(self) -> None:
        answer = self.answer()
        answer["sources"][0]["url"] = "https://alidocs.dingtalk.com/doc?token=secret"
        self.assertIn("source_credentials_forbidden", validate_answer(answer, "sales"))

    def test_rejects_arbitrary_internal_source_payload(self) -> None:
        answer = self.answer("internal")
        answer["internal_sources"] = [{"type": "raw_provider", "title": "payload", "debug": "value"}]
        errors = validate_answer(answer, "internal")
        self.assertIn("source_shape_invalid", errors)

    def test_internal_answer_still_rejects_secrets(self) -> None:
        answer = self.answer("internal")
        answer["sources"] = [{"type": "jira", "title": "Issue", "url": "http://jira.zstack.io/browse/KEY-1"}]
        answer["conclusion"] = "Authorization: " + "Basic " + ("Y" * 32)
        self.assertIn("secret_material_forbidden", validate_answer(answer, "internal"))

    def test_customer_answer_rejects_dingtalk_source(self) -> None:
        answer = self.answer("customer")
        self.assertIn("customer_source_type_forbidden", validate_answer(answer, "customer"))

    def test_rejects_unapproved_source_host_and_empty_complete_answer(self) -> None:
        answer = self.answer("customer")
        answer["sources"] = [{"type": "official_product", "title": "docs", "url": "https://attacker.example/phishing"}]
        self.assertIn("source_host_not_approved", validate_answer(answer, "customer"))
        answer["sources"] = []
        self.assertIn("complete_answer_requires_source", validate_answer(answer, "customer"))
        answer["sources"] = [{"type": "official_product", "title": "unverifiable"}]
        self.assertIn("source_url_required", validate_answer(answer, "customer"))

    def test_accepts_approved_public_zstack_hosts(self) -> None:
        for host in ("www.zstack.io", "docs.zstack.io"):
            answer = self.answer("customer")
            answer["sources"] = [{"type": "official_product", "title": "docs", "url": f"https://{host}/help"}]
            self.assertEqual([], validate_answer(answer, "customer"))

    def test_rejects_external_identifiers_and_dangerous_actions(self) -> None:
        values = (
            "fe80::1",
            "user@example.com",
            "550e8400-e29b-71d4-a716-446655440000",
            "customer acme-corp",
            "serial SN123456789012",
        )
        for value in values:
            answer = self.answer()
            answer["conclusion"] = value
            self.assertIn("external_identifier_forbidden", validate_answer(answer, "sales"))
        answer = self.answer()
        answer["actions"] = ["restart the database service"]
        self.assertIn("destructive_action_forbidden", validate_answer(answer, "sales"))

    def test_rejects_encoded_and_path_credentials(self) -> None:
        for url in (
            "https://alidocs.dingtalk.com/doc?access%5ftoken=" + ("x" * 16),
            "https://alidocs.dingtalk.com/access_token/" + ("x" * 16),
            "https://alidocs.dingtalk.com/doc?sig=" + ("x" * 16),
            "https://alidocs.dingtalk.com/doc?X-Amz-Credential=" + ("x" * 16),
        ):
            answer = self.answer()
            answer["sources"][0]["url"] = url
            self.assertIn("source_credentials_forbidden", validate_answer(answer, "sales"))


class RepositorySecurityScanTest(unittest.TestCase):
    def test_checked_in_plugin_tree_is_clean(self) -> None:
        self.assertEqual([], scan(PLUGIN_ROOT))

    def test_secret_fixture_is_rejected_without_value_in_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            secret = "-----BEGIN " + "PRIVATE KEY-----\n" + ("z" * 64)
            (root / "fixture.txt").write_text(secret, encoding="utf-8")
            findings = scan(root)
            self.assertEqual([{"file": "fixture.txt", "rule": "private_key"}], findings)
            self.assertNotIn("z" * 64, json.dumps(findings))

    def test_symlink_is_rejected_without_reading_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target.txt"
            target.write_text("public", encoding="utf-8")
            link = root / "linked.txt"
            link.symlink_to(target)
            self.assertIn({"file": "linked.txt", "rule": "symlink_forbidden"}, scan(root))

    def test_directory_symlink_and_common_secrets_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "real").mkdir()
            (root / "linked").symlink_to(root / "real", target_is_directory=True)
            (root / "config.txt").write_text("password=" + ("UPPERCASE" * 4), encoding="utf-8")
            findings = scan(root)
            self.assertIn({"file": "linked", "rule": "symlink_forbidden"}, findings)
            self.assertIn({"file": "config.txt", "rule": "credential_assignment"}, findings)

    def test_secret_filename_is_not_echoed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            secret_name = "AKIA" + "1234567890ABCDEF" + ".txt"
            (root / secret_name).write_text("public", encoding="utf-8")
            findings = scan(root)
            self.assertNotIn(secret_name, json.dumps(findings))
            self.assertIn({"file": "<redacted-name>", "rule": "secret_in_filename"}, findings)


if __name__ == "__main__":
    unittest.main()
