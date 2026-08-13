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

workspace_root=$(cd "$repo_root/.." && pwd)
workspace_mcp="$workspace_root/.mcp.json"
mirror_root="$workspace_root/mirrors"
plugin_root="$repo_root/plugins/aios-support"
version_sets=${AIOS_VERSION_SETS_FILE:-/etc/aios-support/version-sets.json}
if [[ -f "$workspace_mcp" && -d "$mirror_root" && -f "$version_sets" ]]; then
  python3 "$plugin_root/scripts/configure_runtime.py" mcp \
    --config "$workspace_mcp" \
    --proxy "$plugin_root/scripts/zdev_readonly_proxy.mjs" \
    --refresh-script "$plugin_root/scripts/refresh_mirrors.py" \
    --search-script "$plugin_root/scripts/search_local_code.py" \
    --mirror-root "$mirror_root" \
    --repository-map "$plugin_root/config/repository-map.json" \
    --version-sets "$version_sets"
  if codex mcp get zdev_readonly --json >/dev/null 2>&1; then
    codex mcp remove zdev_readonly
  fi
  codex mcp add zdev_readonly \
    --env "ZDEV_MCP_CONFIG=$workspace_mcp" \
    --env ZDEV_MCP_SERVER=zdev_upstream \
    --env "AIOS_REFRESH_SCRIPT=$plugin_root/scripts/refresh_mirrors.py" \
    --env "AIOS_LOCAL_SEARCH_SCRIPT=$plugin_root/scripts/search_local_code.py" \
    --env "AIOS_MIRROR_ROOT=$mirror_root" \
    --env "AIOS_REPOSITORY_MAP=$plugin_root/config/repository-map.json" \
    --env "AIOS_VERSION_SETS_FILE=$version_sets" \
    --env "AIOS_DEFAULT_VERSION=${AIOS_DEFAULT_VERSION:-5.5.30}" \
    -- node "$plugin_root/scripts/zdev_readonly_proxy.mjs"
fi

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
