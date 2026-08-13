from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PROXY = PLUGIN_ROOT / "scripts" / "zdev_readonly_proxy.mjs"


class ZdevReadonlyProxyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.upstream = self.root / "upstream.py"
        self.upstream.write_text(
            """import json
import sys

tools = [
    {'name': 'gl_list_projects', 'description': 'read', 'inputSchema': {'type': 'object'}},
    {'name': 'jira_search', 'description': 'read', 'inputSchema': {'type': 'object'}},
    {'name': 'confluence_search', 'description': 'read', 'inputSchema': {'type': 'object'}},
    {'name': 'jira_add_comment', 'description': 'write', 'inputSchema': {'type': 'object'}},
]
for line in sys.stdin:
    request = json.loads(line)
    if request.get('method') == 'tools/list':
        result = {'tools': tools}
    elif request.get('method') == 'tools/call':
        result = {'content': [{'type': 'text', 'text': request['params']['name']}], 'isError': False}
    else:
        result = {'protocolVersion': '2025-03-26', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'fake', 'version': '1'}}
    if 'id' in request:
        print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
""",
            encoding="utf-8",
        )
        self.config = self.root / "mcp.json"
        self.config.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "zdev_upstream": {
                            "command": sys.executable,
                            "args": [str(self.upstream)],
                            "env": {},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        self.mirrors = self.root / "mirrors"
        self.mirrors.mkdir()
        self.repository_map = self.root / "repository-map.json"
        self.repository_map.write_text('{"repositories":{}}', encoding="utf-8")
        self.refresh = self.root / "refresh.py"
        self.refresh.write_text("print('{\"status\":\"updated\",\"repositories\":[]}')\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def start_proxy(self) -> subprocess.Popen[str]:
        env = os.environ.copy()
        env.update(
            {
                "ZDEV_MCP_CONFIG": str(self.config),
                "ZDEV_MCP_SERVER": "zdev_upstream",
                "AIOS_REFRESH_SCRIPT": str(self.refresh),
                "AIOS_MIRROR_ROOT": str(self.mirrors),
                "AIOS_REPOSITORY_MAP": str(self.repository_map),
            }
        )
        return subprocess.Popen(
            ["node", str(PROXY)],
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

    def request(self, process: subprocess.Popen[str], request: dict) -> dict:
        assert process.stdin is not None
        assert process.stdout is not None
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        return json.loads(process.stdout.readline())

    def stop_proxy(self, process: subprocess.Popen[str]) -> None:
        process.terminate()
        process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()

    def test_lists_only_approved_read_tools_with_readonly_annotations(self) -> None:
        process = self.start_proxy()
        try:
            response = self.request(process, {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
            tools = response["result"]["tools"]
            self.assertEqual(
                ["aios_refresh_code_mirrors", "confluence_search", "jira_search"],
                sorted(tool["name"] for tool in tools),
            )
            for tool in tools:
                self.assertFalse(tool["annotations"]["destructiveHint"])
                self.assertTrue(tool["annotations"]["idempotentHint"])
                self.assertEqual(tool["name"] != "aios_refresh_code_mirrors", tool["annotations"]["readOnlyHint"])
        finally:
            self.stop_proxy(process)

    def test_denies_unapproved_tool_call_without_forwarding_it(self) -> None:
        process = self.start_proxy()
        try:
            response = self.request(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "jira_add_comment", "arguments": {"body": "unsafe"}},
                },
            )
            self.assertTrue(response["result"]["isError"])
            self.assertEqual("tool_not_allowed", response["result"]["content"][0]["text"])
        finally:
            self.stop_proxy(process)

    def test_denies_remote_gitlab_code_lookup(self) -> None:
        process = self.start_proxy()
        try:
            response = self.request(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {"name": "gl_list_projects", "arguments": {}},
                },
            )
            self.assertTrue(response["result"]["isError"])
            self.assertEqual("tool_not_allowed", response["result"]["content"][0]["text"])
        finally:
            self.stop_proxy(process)

    def test_forwards_approved_tool_call(self) -> None:
        process = self.start_proxy()
        try:
            response = self.request(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "jira_search", "arguments": {"jql": "project = AIOS"}},
                },
            )
            self.assertFalse(response["result"]["isError"])
            self.assertEqual("jira_search", response["result"]["content"][0]["text"])
        finally:
            self.stop_proxy(process)

    def test_runs_only_fixed_mirror_refresh_entrypoint(self) -> None:
        process = self.start_proxy()
        try:
            response = self.request(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "aios_refresh_code_mirrors", "arguments": {}},
                },
            )
            self.assertFalse(response["result"]["isError"])
            self.assertIn('"status":"updated"', response["result"]["content"][0]["text"])
        finally:
            self.stop_proxy(process)


if __name__ == "__main__":
    unittest.main()
