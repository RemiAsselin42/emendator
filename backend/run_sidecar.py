"""Entry point for the bundled sidecar binary.

PyInstaller freezes this into ``emendator-backend`` (see scripts/build-sidecar.sh
and CONTRIBUTING); the Tauri shell spawns that binary on startup so users never
launch the backend by hand. Running it directly (``uv run python run_sidecar.py``)
is equivalent.

``emendator-backend mcp`` runs the stdio MCP server instead of the HTTP API, so
one frozen binary serves both the Tauri shell and external AI clients (see
docs/mcp.md).
"""

import sys

import uvicorn

from app.config import settings
from app.main import app


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "mcp":
        from app.mcp import main as mcp_main

        mcp_main()
        return
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
