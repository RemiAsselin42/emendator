#!/usr/bin/env bash
# Package the MCP server as a one-click Desktop Extension (.mcpb).
#
# Prereqs: the frozen sidecar (scripts/build-sidecar.sh) and the mcpb CLI
# (npm i -g @anthropic-ai/mcpb). Produces dist/emendator.mcpb — drag it into
# Claude Desktop's Settings > Extensions to install.
set -euo pipefail
cd "$(dirname "$0")/.."

SIDECAR="backend/dist/emendator-backend.exe"
if [[ ! -f "$SIDECAR" ]]; then
  echo "Sidecar binary not found ($SIDECAR) — run scripts/build-sidecar.sh first." >&2
  exit 1
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/server" dist
cp mcpb/manifest.json "$STAGE/manifest.json"
cp "$SIDECAR" "$STAGE/server/"

npx --yes @anthropic-ai/mcpb pack "$STAGE" dist/emendator.mcpb
echo "dist/emendator.mcpb ready — install via Claude Desktop > Settings > Extensions."
