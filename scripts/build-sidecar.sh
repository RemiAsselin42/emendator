#!/usr/bin/env bash
# Build the FastAPI backend into a standalone binary and place it where Tauri's
# externalBin expects it: src-tauri/binaries/emendator-backend-<target-triple>[.exe].
# Run before `pnpm tauri build`. Requires uv, PyInstaller (dev dep) and rustc.
set -euo pipefail

cd "$(dirname "$0")/.."

triple="$(rustc -vV | sed -n 's/host: //p')"
ext=""
case "$triple" in
  *windows*) ext=".exe" ;;
esac

echo "Building sidecar for $triple ..."
(
  cd backend
  uv run pyinstaller --onefile --name emendator-backend \
    --collect-submodules uvicorn --collect-submodules app --noconfirm run_sidecar.py
)

mkdir -p src-tauri/binaries
cp "backend/dist/emendator-backend${ext}" "src-tauri/binaries/emendator-backend-${triple}${ext}"
echo "Placed src-tauri/binaries/emendator-backend-${triple}${ext}"
