# shellcheck shell=sh
# Locate Node for git hooks (Git Bash / sh). Sets GIT_HOOK_NODE or leaves empty.
# Sourced from .githooks/*, always safe to source (no exit).

GIT_HOOK_NODE=""

_hook_root() {
  if [ -n "${GITHOOK_ROOT:-}" ]; then
    printf '%s' "$GITHOOK_ROOT"
    return
  fi
  if [ -n "${ROOT:-}" ]; then
    printf '%s' "$ROOT"
    return
  fi
  cd "$(dirname "$0")/.." 2>/dev/null && pwd
}

ROOT="$(_hook_root)"
MAJOR="24"
if [ -f "$ROOT/.node-version" ]; then
  MAJOR=$(tr -d '\r\n' < "$ROOT/.node-version" | sed 's/[^0-9].*//')
fi

_to_unix_path() {
  printf '%s' "$1" | sed 's|\\|/|g'
}

_try_node() {
  candidate=$1
  if [ -n "$candidate" ] && [ -f "$candidate" ]; then
    GIT_HOOK_NODE="$candidate"
    return 0
  fi
  return 1
}

# fnm on Windows (Git Bash: APPDATA or USERPROFILE)
if [ -n "${APPDATA:-}" ]; then
  base="$(_to_unix_path "$APPDATA")/fnm/node-versions"
  if [ -d "$base" ]; then
    for candidate in "$base/v${MAJOR}."*/installation/node.exe; do
      if _try_node "$candidate"; then break; fi
    done
  fi
fi

if [ -z "$GIT_HOOK_NODE" ] && [ -n "${USERPROFILE:-}" ]; then
  base="$(_to_unix_path "$USERPROFILE")/AppData/Roaming/fnm/node-versions"
  if [ -d "$base" ]; then
    for candidate in "$base/v${MAJOR}."*/installation/node.exe; do
      if _try_node "$candidate"; then break; fi
    done
  fi
fi

# fnm multishells (Cursor / IDE injects these)
if [ -z "$GIT_HOOK_NODE" ] && [ -n "${LOCALAPPDATA:-}" ]; then
  ms="$(_to_unix_path "$LOCALAPPDATA")/fnm/multishells"
  if [ -d "$ms" ]; then
    for dir in "$ms"/*; do
      if [ -x "$dir/node.exe" ] 2>/dev/null || [ -f "$dir/node.exe" ]; then
        _try_node "$dir/node.exe" && break
      fi
    done
  fi
fi

# PATH (login profiles; a non-login Git hook usually misses this)
if [ -z "$GIT_HOOK_NODE" ] && command -v node >/dev/null 2>&1; then
  GIT_HOOK_NODE=$(command -v node)
fi

export GIT_HOOK_NODE
