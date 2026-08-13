#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
marketplace_name=aios-support-marketplace

if ! command -v codex >/dev/null 2>&1; then
  echo "codex is not installed or not on PATH" >&2
  exit 1
fi

bash "$repo_root/scripts/test-plugin.sh"

if ! codex plugin marketplace list 2>/dev/null | grep -Fq "$repo_root"; then
  codex plugin marketplace add "$repo_root"
fi

codex plugin add "aios-support@$marketplace_name"

echo "AIOS Support installed. Open a new Codex task before testing."
