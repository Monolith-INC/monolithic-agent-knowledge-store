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

usage() {
  cat <<'EOF'
Usage: install.sh [options]

Options:
  --dest <path>         Target project directory (non-interactive when supplied)
  --target <host>       claude | cursor | codex | all-agents (default: all-agents)
  --root <rel-path>     Visible store folder inside project (default: Project_Knowledge)
  --language <lang>     Documentation language for guide & glossary (default: en)
  --local-only          Keep store local via .gitignore instead of Git tracking
  --uninstall           Remove installed plugin copy and host skill links from --dest
  -h, --help            Show this help

Environment variables:
  MAKS_VERSION          Pin release tag (e.g. v0.2.0); defaults to latest
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

if [[ "$UNINSTALL" == "true" ]]; then
  for skill_root in $(wire_targets); do
    for skill in setup-project-knowledge discover-project-knowledge query-project-knowledge refresh-project-knowledge; do
      rm -rf "${DEST}/${skill_root}/${skill}"
    done
  done
  rm -rf "$INSTALL_DIR"
  echo "Uninstalled monolithic-agent-knowledge-store from ${DEST} (project knowledge data preserved)."
  exit 0
fi

PY="$(find_python312)" || {
  echo "Error: Python 3.12+ is required. Install Python 3.12+ or set MAKS_PYTHON." >&2
  exit 1
}

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

for skill_root in $(wire_targets); do
  mkdir -p "${DEST}/${skill_root}"
  for skill_dir in "${INSTALL_DIR}"/skills/*; do
    [[ -d "$skill_dir" ]] || continue
    skill_name="$(basename "$skill_dir")"
    rm -rf "${DEST}/${skill_root}/${skill_name}"
    cp -R "$skill_dir" "${DEST}/${skill_root}/${skill_name}"
  done
done

SETUP_ARGS=(setup --project "$DEST" --root "$STORE_ROOT" --language "$LANGUAGE")
if [[ "$LOCAL_ONLY" == "true" ]]; then
  SETUP_ARGS+=(--local-only)
fi

"$PY" "${INSTALL_DIR}/scripts/query.py" "${SETUP_ARGS[@]}"
echo "Installed monolithic-agent-knowledge-store into ${DEST} (target=${TARGET}). Restart your agent session to reload skills."
