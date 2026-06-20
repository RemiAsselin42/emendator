"""Entry point for the bundled sidecar binary.

PyInstaller freezes this into ``emendator-backend`` (see scripts/build-sidecar.sh
and CONTRIBUTING); the Tauri shell spawns that binary on startup so users never
launch the backend by hand. Running it directly (``uv run python run_sidecar.py``)
is equivalent.
"""

import uvicorn

from app.config import settings
from app.main import app


def main() -> None:
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
