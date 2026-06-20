# Emendator backend

Local FastAPI sidecar. Drives jar parsing (Phase 1) and the Docker runner (Phase 2).
Runs on the loopback interface only; the Tauri shell spawns it.

## Develop

```bash
uv sync                                              # create .venv + install deps
uv run uvicorn app.main:app --reload --port 8008     # dev server
uv run pytest                                         # tests
uv run ruff check . && uv run ruff format --check .   # lint + format
uv run pyright                                        # type check
```

## Configuration

Env vars are prefixed `EMENDATOR_` (or set in a local `.env`). See `app/config.py`.

| Var                      | Default     | Meaning                          |
| ------------------------ | ----------- | -------------------------------- |
| `EMENDATOR_PROFILE`      | `1.21.1`    | Active version profile           |
| `EMENDATOR_HOST`         | `127.0.0.1` | Bind address (keep on loopback)  |
| `EMENDATOR_PORT`         | `8008`      | Port the front connects to       |
| `EMENDATOR_CORS_ORIGINS` | dev + tauri | Allowed webview origins (JSON)   |
