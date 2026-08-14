#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
plugin_root="$repo_root/plugins/aios-support"
creator_root="${CODEX_PLUGIN_CREATOR_ROOT:-$HOME/.codex/skills/.system/plugin-creator}"
skill_creator_root="${CODEX_SKILL_CREATOR_ROOT:-$HOME/.codex/skills/.system/skill-creator}"
python_bin="${PYTHON_BIN:-python3}"

"$python_bin" "$creator_root/scripts/validate_plugin.py" "$plugin_root"

while IFS= read -r skill_dir; do
  "$python_bin" "$skill_creator_root/scripts/quick_validate.py" "$skill_dir"
done < <(find "$plugin_root/skills" -mindepth 1 -maxdepth 1 -type d | sort)

"$python_bin" -m unittest discover -s "$plugin_root/tests" -p 'test_*.py' -v

"$python_bin" -m json.tool "$repo_root/.agents/plugins/marketplace.json" >/dev/null
"$python_bin" "$plugin_root/scripts/validate_mcp_config.py" "$plugin_root/.mcp.json"
if [[ -n "${AIOS_VERSION_SETS_FILE:-}" ]]; then
  "$python_bin" "$plugin_root/scripts/validate_version_sets.py" \
    --repository-map "$plugin_root/config/repository-map.json" \
    --version-sets "$AIOS_VERSION_SETS_FILE"
fi
"$python_bin" "$plugin_root/scripts/security_scan.py" "$repo_root"
"$python_bin" -m json.tool "$plugin_root/config/repository-map.json" >/dev/null

echo "AIOS Support plugin validation passed."
