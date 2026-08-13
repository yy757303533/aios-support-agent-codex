from __future__ import annotations

import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_ROOT = PLUGIN_ROOT / "skills" / "aios-support-knowledge"
LOG_MAP = KNOWLEDGE_ROOT / "references" / "logs-and-code-map.md"


class LogKnowledgeMapTest(unittest.TestCase):
    def setUp(self) -> None:
        self.text = LOG_MAP.read_text(encoding="utf-8")

    def test_maps_required_log_sources_to_code_owners(self) -> None:
        required = {
            "/var/log/ai/startup.log": "aios/devops",
            "/var/log/ai/app.log": "aios/inference",
            "/var/log/ai/access.log": "aios/inference",
            "management-server.log": "premium/plugin-premium/ai",
            "zstack-kvmagent.log": "zstack-utility",
            "/var/log/ai-model-center-agent/": "aios/agent",
            "/var/log/zstack/zstack-dfs/zdfs.log": "aios/dfs",
            "aios_mount_daemon.log": "aios/devops",
        }
        for log_source, code_owner in required.items():
            with self.subTest(log_source=log_source):
                row = next(line for line in self.text.splitlines() if log_source in line)
                self.assertIn(code_owner, row)

    def test_requires_versioned_code_evidence_and_unknown_fallback(self) -> None:
        for phrase in ("CodeContext", "logger 调用点", "直接调用方", "unknown", "源码未命中"):
            self.assertIn(phrase, self.text)

    def test_event_analysis_routes_to_log_map(self) -> None:
        event_skill = (PLUGIN_ROOT / "skills" / "event-analysis" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("logs-and-code-map.md", event_skill)
        self.assertIn("startup.log", event_skill.split("---", 2)[1])


if __name__ == "__main__":
    unittest.main()
