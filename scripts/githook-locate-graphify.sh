# shellcheck shell=sh
# Locate Graphify CLI for git hooks (Git Bash). Sets GIT_HOOK_GRAPHIFY or leaves empty.

GIT_HOOK_GRAPHIFY=""

_hook_root() {
  if [ -n "${GITHOOK_ROOT:-}" ]; then
    printf '%s' "$GITHOOK_ROOT"
    return
  fi
  cd "$(dirname "$0")/.." 2>/dev/null && pwd
}

ROOT="$(_hook_root)"

_to_unix() {
  printf '%s' "$1" | sed 's|\\|/|g'
}

try_bin() {
  candidate=$1
  if [ -n "$candidate" ] && [ -f "$candidate" ]; then
    GIT_HOOK_GRAPHIFY="$candidate"
    return 0
  fi
  return 1
}

try_bin "$(_to_unix "$ROOT")/.hyperpower/tools/bin/graphify.exe" || true
try_bin "$ROOT/.hyperpower/tools/bin/graphify.exe" || true
try_bin "$ROOT/.hyperpower/tools/bin/graphify" || true

if [ -z "$GIT_HOOK_GRAPHIFY" ] && command -v graphify >/dev/null 2>&1; then
  GIT_HOOK_GRAPHIFY=$(command -v graphify)
fi

export GIT_HOOK_GRAPHIFY
