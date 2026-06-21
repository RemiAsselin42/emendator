from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, overridable via EMENDATOR_* env vars or a .env file."""

    model_config = SettingsConfigDict(
        env_prefix="EMENDATOR_",
        env_file=".env",
        extra="ignore",
    )

    # Fallback target when a folder carries no version constraints (see §6).
    # Auto-detection (app.profile.detect_version) is the normal path.
    default_version: str = "1.21.1"
    host: str = "127.0.0.1"
    port: int = 8008
    # Online metadata enrichment (Modrinth/CurseForge). Best-effort and off the
    # critical path: a failure or being offline never breaks a scan. Disable to
    # stay fully offline. The CurseForge API key unlocks update checks (its
    # offline manifest enrichment needs no key).
    enrich_online: bool = True
    curseforge_api_key: str | None = None
    # Where enrichment responses are cached; defaults to ~/.emendator/cache.
    cache_dir: str | None = None
    # Origins allowed to call the sidecar: the Vite dev server and the bundled
    # Tauri webview (origin differs per platform).
    cors_origins: list[str] = [
        "http://localhost:1420",
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ]


settings = Settings()
