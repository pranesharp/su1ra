#!/usr/bin/env bash
# Su1ra dev launcher (Linux/macOS)
# - cd to the repo (the folder this script lives in)
# - create .venv if missing
# - activate it (install requirements on first run / when missing)
# - run desktop.py
#
# Usage:  ./launcher-linux.sh          (double-click also works if your file
#        manager executes shell scripts in a terminal)

set -euo pipefail

# 1) current directory = where this script lives (repo root)
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 2) make a new venv in the dir if there isn't one
PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "error: python3 not found on PATH" >&2
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "[su1ra] creating venv in $(pwd)/.venv ..."
  "$PY" -m venv .venv
fi

# 3) use that venv
# shellcheck disable=SC1091
source .venv/bin/activate

# first run (or new deps): install requirements
if ! .venv/bin/python -c "import webview, fastapi, uvicorn, httpx, pptx, docx, openpyxl, reportlab, PIL" >/dev/null 2>&1; then
  echo "[su1ra] installing backend requirements ..."
  pip install --upgrade pip >/dev/null
  pip install -r backend/requirements.txt pillow
fi

# frontend must be built for the app to serve the ui
if [ ! -f "frontend/dist/index.html" ]; then
  echo "[su1ra] frontend/dist missing — building it (needs yarn or npm) ..."
  if command -v yarn >/dev/null 2>&1; then
    (cd frontend && yarn && yarn build)
  elif command -v npm >/dev/null 2>&1; then
    (cd frontend && npm install && npm run build)
  else
    echo "error: yarn/npm not found — build frontend/dist manually" >&2
    exit 1
  fi
fi

# 4) run the app (no exec — keep the terminal readable if it crashes)
echo "[su1ra] starting (python: $(command -v python))"
python desktop.py
rc=$?
if [ $rc -ne 0 ]; then
  echo
  echo "[su1ra] exited with code $rc."
  if ! .venv/bin/python -c "import gi" >/dev/null 2>&1 && ! .venv/bin/python -c "import qtpy" >/dev/null 2>&1; then
    echo "pywebview needs GTK or QT python bindings (not a pip package — system packages):"
    echo "  arch:   sudo pacman -S python-gobject gtk3 webkit2gtk-4.1"
    echo "  debian: sudo apt install python3-gi gir1.2-webkit2-4.1 libgtk-3-0"
    echo "  fedora: sudo dnf install python3-gobject gtk3 webkit2gtk4.1"
  fi
fi
exit $rc
