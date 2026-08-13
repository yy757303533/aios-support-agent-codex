#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
marketplace_name=aios-support-marketplace

if ! command -v codex >/dev/null 2>&1; then
  echo "codex is not installed or not on PATH" >&2
  exit 1
fi

bash "$repo_root/scripts/test-plugin.sh"

if codex plugin list --json | python3 -c '
import json, sys
items = json.load(sys.stdin).get("installed", [])
raise SystemExit(0 if any(item.get("pluginId") == "aios-support@aios-support-marketplace" for item in items) else 1)
'; then
  codex plugin remove "aios-support@$marketplace_name"
fi

if codex plugin marketplace list 2>/dev/null | awk 'NR > 1 {print $1}' | grep -Fxq "$marketplace_name"; then
  codex plugin marketplace remove "$marketplace_name"
fi

codex plugin marketplace add "$repo_root"
codex plugin add "aios-support@$marketplace_name"

expected_version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["version"])' \
  "$repo_root/plugins/aios-support/.codex-plugin/plugin.json")
installed_version=$(codex plugin list --json | python3 -c '
import json, sys
items = json.load(sys.stdin).get("installed", [])
matches = [item for item in items if item.get("pluginId") == "aios-support@aios-support-marketplace"]
print(matches[0].get("version", "") if len(matches) == 1 else "")
')
if [[ "$installed_version" != "$expected_version" ]]; then
  echo "installed plugin version mismatch" >&2
  exit 1
fi

echo "AIOS Support $installed_version installed. Open a new Codex task before testing."
