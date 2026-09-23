#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

(cd frontend && yarn build)
(cd backend && ../.venv/bin/python -c "import main" )
.venv/bin/pyinstaller packaging/su1ra.spec --noconfirm --distpath packaging/dist --workpath packaging/build
tar -czf packaging/Su1ra-linux-x64.tar.gz -C packaging/dist Su1ra
echo "bundle: packaging/Su1ra-linux-x64.tar.gz"
