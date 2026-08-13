#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
plugin_root="$repo_root/plugins/aios-support"
creator_root="${CODEX_PLUGIN_CREATOR_ROOT:-$HOME/.codex/skills/.system/plugin-creator}"
skill_creator_root="${CODEX_SKILL_CREATOR_ROOT:-$HOME/.codex/skills/.system/skill-creator}"

python3 "$creator_root/scripts/validate_plugin.py" "$plugin_root"

while IFS= read -r skill_dir; do
  python3 "$skill_creator_root/scripts/quick_validate.py" "$skill_dir"
done < <(find "$plugin_root/skills" -mindepth 1 -maxdepth 1 -type d | sort)

python3 -m unittest discover -s "$plugin_root/tests" -p 'test_*.py' -v

python3 -m json.tool "$repo_root/.agents/plugins/marketplace.json" >/dev/null
python3 -m json.tool "$plugin_root/.mcp.json" >/dev/null
python3 -m json.tool "$plugin_root/config/repository-map.json" >/dev/null

echo "AIOS Support plugin validation passed."
