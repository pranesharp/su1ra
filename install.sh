#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
APP_DATA="${XDG_DATA_HOME:-$HOME/.local/share}/su1ra"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

info() { printf '\033[1;32m[su1ra]\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33m[su1ra]\033[0m %s\n' "$1"; }

detect_pkg() {
  if command -v pacman >/dev/null 2>&1; then echo "pacman"
  elif command -v apt-get >/dev/null 2>&1; then echo "apt"
  elif command -v dnf >/dev/null 2>&1; then echo "dnf"
  else echo "none"
  fi
}

webkit_present() {
  pkg-config --exists webkit2gtk-4.1 2>/dev/null && return 0
  ls /usr/lib/girepository-1.0/WebKit2-4.1.typelib >/dev/null 2>&1 && return 0
  ls /usr/lib64/girepository-1.0/WebKit2-4.1.typelib >/dev/null 2>&1 && return 0
  return 1
}

install_system_deps() {
  local pkg
  pkg="$(detect_pkg)"
  local missing=()

  command -v python3 >/dev/null 2>&1 || missing+=("python3")
  command -v git >/dev/null 2>&1 || missing+=("git")
  python3 -c "import venv" 2>/dev/null || missing+=("python3-venv")
  webkit_present || missing+=("webkit2gtk-4.1")

  if [ "${#missing[@]}" -eq 0 ]; then
    info "system dependencies already present"
    return
  fi

  warn "installing missing system packages: ${missing[*]}"
  case "$pkg" in
    pacman)
      sudo pacman -S --needed --noconfirm python python-pip git webkit2gtk-4.1 gtk3
      ;;
    apt)
      sudo apt-get update -qq
      sudo apt-get install -y python3 python3-venv python3-pip python3-gi gir1.2-webkit2-4.1 git
      ;;
    dnf)
      sudo dnf install -y python3 python3-pip python3-gobject git webkit2gtk4.1
      ;;
    *)
      warn "unknown distro — install python3, git and webkit2gtk-4.1 manually, then re-run"
      exit 1
      ;;
  esac
}

setup_venv() {
  cd "$INSTALL_DIR"
  if [ ! -d .venv ]; then
    info "creating python environment"
    python3 -m venv --system-site-packages .venv
  fi
  info "syncing pinned dependencies"
  .venv/bin/pip install -q -r backend/requirements.txt
}

write_launcher() {
  mkdir -p "$BIN_DIR"
  cat > "$BIN_DIR/su1ra" <<EOF
#!/usr/bin/env bash
SU1RA_DIR="$INSTALL_DIR"
case "\${1:-}" in
  update)
    cd "\$SU1RA_DIR"
    git pull --ff-only
    .venv/bin/pip install -q -r backend/requirements.txt
    echo "su1ra updated."
    ;;
  *)
    cd "\$SU1RA_DIR"
    exec .venv/bin/python desktop.py
    ;;
esac
EOF
  chmod +x "$BIN_DIR/su1ra"
}

write_desktop_entry() {
  mkdir -p "$DESKTOP_DIR"
  cat > "$DESKTOP_DIR/su1ra.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Su1ra
Comment=Chat with your local Ollama models
Exec="$BIN_DIR/su1ra"
Path=$INSTALL_DIR
Icon=$INSTALL_DIR/su1ra.svg
Terminal=false
Categories=Network;Utility;
StartupWMClass=Su1ra
EOF
}

main() {
  if [ ! -d "$INSTALL_DIR/.git" ]; then
    warn "not a git checkout — updates need git; continuing with local install anyway"
  fi
  install_system_deps
  setup_venv
  write_launcher
  write_desktop_entry
  info "installed."
  info "  launch:   su1ra   (or 'Su1ra' in your app menu)"
  info "  update:   su1ra update"
  info "  chats:    $APP_DATA"
}

main "$@"
