#!/usr/bin/env bash
set -euo pipefail

# Monolithic Agent Knowledge Store installer (Interactive & Non-interactive / CI)
# Convention matches Monolith-INC/codex-workflows-plugin:
#   Interactive:     bash <(curl -fsSL https://github.com/Monolith-INC/monolithic-agent-knowledge-store/releases/latest/download/install.sh)
#   Non-interactive: curl -fsSL https://github.com/Monolith-INC/monolithic-agent-knowledge-store/releases/latest/download/install.sh | bash -s -- --dest /abs/path

REPO="Monolith-INC/monolithic-agent-knowledge-store"
DEST=""
TARGET="all-agents"
STORE_ROOT="Project_Knowledge"
LANGUAGE="en"
LOCAL_ONLY="false"
UNINSTALL="false"
VERSION="${MAKS_VERSION:-latest}"
RELEASE_ZIP="${MAKS_RELEASE_ZIP:-}"
PYTHON_BIN="${MAKS_PYTHON:-}"

ALL_SKILLS=(
  setup-project-knowledge
  discover-project-knowledge
  query-project-knowledge
  refresh-project-knowledge
  ingest-docs
  publish-docs
)

usage() {
  cat <<'EOF'
Usage: install.sh [options]

Options:
  --dest <path>         Target project directory (non-interactive when supplied)
  --target <host>       claude | cursor | codex | all-agents (default: all-agents)
  --root <rel-path>     Visible store folder inside project (default: Project_Knowledge)
  --language <lang>     Documentation language for guide & glossary (default: en)
  --local-only          Keep store local via .gitignore instead of Git tracking
  --uninstall           Remove installed plugin copy, host skill links, and MAKS hooks from --dest
  -h, --help            Show this help

Environment variables:
  MAKS_VERSION          Pin release tag (e.g. v0.4.0); defaults to latest
  MAKS_RELEASE_ZIP      Install offline from a local release .zip archive
  MAKS_PYTHON           Explicit Python 3.12+ executable path
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest) DEST="$2"; shift 2 ;;
    --target) TARGET="$2"; shift 2 ;;
    --root) STORE_ROOT="$2"; shift 2 ;;
    --language) LANGUAGE="$2"; shift 2 ;;
    --local-only) LOCAL_ONLY="true"; shift ;;
    --uninstall) UNINSTALL="true"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

find_python312() {
  if [[ -n "$PYTHON_BIN" ]]; then
    echo "$PYTHON_BIN"
    return 0
  fi
  for candidate in python3.12 python3.13 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
        command -v "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

if [[ -z "$DEST" ]]; then
  if [[ -t 0 ]]; then
    read -r -p "Target project directory [${PWD}]: " input_dest
    DEST="${input_dest:-$PWD}"
    read -r -p "Agent host target (claude|cursor|codex|all-agents) [${TARGET}]: " input_target
    TARGET="${input_target:-$TARGET}"
    read -r -p "Visible store directory [${STORE_ROOT}]: " input_root
    STORE_ROOT="${input_root:-$STORE_ROOT}"
    read -r -p "Documentation language [${LANGUAGE}]: " input_lang
    LANGUAGE="${input_lang:-$LANGUAGE}"
  else
    echo "Error: --dest <path> is required in non-interactive / CI mode." >&2
    exit 2
  fi
fi

mkdir -p "$DEST"
DEST="$(cd "$DEST" && pwd)"
INSTALL_DIR="${DEST}/.monolithic-agent-knowledge-store"

wire_targets() {
  case "$TARGET" in
    claude) echo ".claude/skills" ;;
    cursor) echo ".cursor/skills" ;;
    codex) echo ".codex/skills" ;;
    all-agents) echo ".claude/skills .cursor/skills .codex/skills .agents/skills" ;;
    *) echo "Invalid --target: $TARGET" >&2; exit 2 ;;
  esac
}

manage_hooks() {
  local mode="$1"
  local py_exec="$2"
  "$py_exec" - "$mode" "$DEST" "$TARGET" <<'PYEOF'
import json, sys
from pathlib import Path

mode, dest_str, target = sys.argv[1], sys.argv[2], sys.argv[3]
dest = Path(dest_str)
marker = ".monolithic-agent-knowledge-store/bin/maks"

def is_maks_entry(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    if isinstance(entry.get("command"), str) and marker in entry["command"]:
        return True
    hooks = entry.get("hooks")
    if isinstance(hooks, list):
        return any(isinstance(h, dict) and isinstance(h.get("command"), str) and marker in h["command"] for h in hooks)
    return False

def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}

def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    tmp.replace(path)

def update_claude_like(path: Path, include_stop: bool) -> None:
    data = load_json(path)
    hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else {}
    events = {
        "SessionStart": {"matcher": "", "hooks": [{"type": "command", "command": f"{marker} orient"}]},
        "UserPromptSubmit": {"matcher": "", "hooks": [{"type": "command", "command": f"{marker} inject"}]},
        "PreToolUse": {"matcher": "Read|Edit|Write|MultiEdit|Bash|Grep|Glob", "hooks": [{"type": "command", "command": f"{marker} gate"}]},
    }
    if include_stop:
        events["Stop"] = {"matcher": "", "hooks": [{"type": "command", "command": f"{marker} session-end"}]}
    for ev, spec in events.items():
        current = [e for e in (hooks.get(ev) if isinstance(hooks.get(ev), list) else []) if not is_maks_entry(e)]
        if mode == "install":
            current.append(spec)
        if current:
            hooks[ev] = current
        elif ev in hooks:
            del hooks[ev]
    if hooks:
        data["hooks"] = hooks
    elif "hooks" in data:
        del data["hooks"]
    if mode == "install" or path.is_file():
        save_json(path, data)

def update_cursor(path: Path) -> None:
    data = load_json(path)
    hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else {}
    events = {
        "beforeSubmitPrompt": {"command": f"{marker} inject"},
        "beforeShellExecution": {"command": f"{marker} gate --action shell"},
        "stop": {"command": f"{marker} session-end"},
    }
    for ev, spec in events.items():
        current = [e for e in (hooks.get(ev) if isinstance(hooks.get(ev), list) else []) if not is_maks_entry(e)]
        if mode == "install":
            current.append(spec)
        if current:
            hooks[ev] = current
        elif ev in hooks:
            del hooks[ev]
    if mode == "install":
        data.setdefault("version", 1)
    if hooks:
        data["hooks"] = hooks
    elif "hooks" in data:
        del data["hooks"]
    if mode == "install" or path.is_file():
        save_json(path, data)

if target in ("claude", "all-agents"):
    update_claude_like(dest / ".claude" / "settings.local.json", include_stop=True)
if target in ("codex", "all-agents"):
    update_claude_like(dest / ".codex" / "hooks.json", include_stop=False)
if target in ("cursor", "all-agents"):
    update_cursor(dest / ".cursor" / "hooks.json")
PYEOF
}

PY="$(find_python312)" || {
  echo "Error: Python 3.12+ is required. Install Python 3.12+ or set MAKS_PYTHON." >&2
  exit 1
}

if [[ "$UNINSTALL" == "true" ]]; then
  for skill_root in $(wire_targets); do
    for skill in "${ALL_SKILLS[@]}"; do
      rm -rf "${DEST}/${skill_root}/${skill}"
    done
  done
  manage_hooks uninstall "$PY"
  rm -rf "$INSTALL_DIR"
  echo "Uninstalled monolithic-agent-knowledge-store from ${DEST} (project knowledge data preserved)."
  exit 0
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

ZIP_PATH="$RELEASE_ZIP"
if [[ -z "$ZIP_PATH" ]]; then
  ZIP_PATH="${TMP_DIR}/release.zip"
  if [[ "$VERSION" == "latest" ]]; then
    URL="https://github.com/${REPO}/releases/latest/download/monolithic-agent-knowledge-store.zip"
  else
    URL="https://github.com/${REPO}/releases/download/${VERSION}/monolithic-agent-knowledge-store-${VERSION#v}.zip"
  fi
  curl -fsSL "$URL" -o "$ZIP_PATH"
fi

rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
"$PY" - "$ZIP_PATH" "$INSTALL_DIR" <<'PYEOF'
import sys, zipfile
from pathlib import Path
src, dst = Path(sys.argv[1]), Path(sys.argv[2])
with zipfile.ZipFile(src) as zf:
    zf.extractall(dst)
PYEOF

# Create pinned Python 3.12+ launcher so skills & hooks work even when default `python3` is <3.12
mkdir -p "${INSTALL_DIR}/bin"
cat > "${INSTALL_DIR}/bin/maks" <<EOF
#!/usr/bin/env bash
exec "${PY}" "${INSTALL_DIR}/scripts/query.py" "\$@"
EOF
chmod +x "${INSTALL_DIR}/bin/maks"

for skill_root in $(wire_targets); do
  mkdir -p "${DEST}/${skill_root}"
  for skill_dir in "${INSTALL_DIR}"/skills/*; do
    [[ -d "$skill_dir" ]] || continue
    skill_name="$(basename "$skill_dir")"
    rm -rf "${DEST}/${skill_root}/${skill_name}"
    cp -R "$skill_dir" "${DEST}/${skill_root}/${skill_name}"
    if [[ -f "${DEST}/${skill_root}/${skill_name}/SKILL.md" ]]; then
      "$PY" - "${DEST}/${skill_root}/${skill_name}/SKILL.md" <<'PYEOF'
import sys
from pathlib import Path
p = Path(sys.argv[1])
text = p.read_text(encoding="utf-8")
for old in ("python3.12 <plugin-root>/scripts/query.py", "python3.12 scripts/query.py", "<plugin-root>/scripts/query.py"):
    text = text.replace(old, ".monolithic-agent-knowledge-store/bin/maks")
p.write_text(text, encoding="utf-8", newline="\n")
PYEOF
    fi
  done
done

manage_hooks install "$PY"

if [[ -f "${DEST}/.git/HEAD" ]]; then
  EXCLUDE_FILE="${DEST}/.git/info/exclude"
  mkdir -p "$(dirname "$EXCLUDE_FILE")"
  grep -qxF "/.monolithic-agent-knowledge-store/" "$EXCLUDE_FILE" 2>/dev/null || echo "/.monolithic-agent-knowledge-store/" >> "$EXCLUDE_FILE"
fi

SETUP_ARGS=(setup --project "$DEST" --root "$STORE_ROOT" --language "$LANGUAGE")
if [[ "$LOCAL_ONLY" == "true" ]]; then
  SETUP_ARGS+=(--local-only)
fi

"$PY" "${INSTALL_DIR}/scripts/query.py" "${SETUP_ARGS[@]}"
echo "Installed monolithic-agent-knowledge-store into ${DEST} (target=${TARGET})."
echo "  Runtime & launcher: .monolithic-agent-knowledge-store/bin/maks (Python: ${PY})"
echo "  Knowledge store:    ${STORE_ROOT}/ (locator: project-knowledge.json)"
echo "  Host skills & hooks wired for: ${TARGET}. Restart your agent session to reload."
