from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, overridable via EMENDATOR_* env vars or a .env file."""

    model_config = SettingsConfigDict(
        env_prefix="EMENDATOR_",
        env_file=".env",
        extra="ignore",
    )

    # Default MVP version profile (see PROJECT.md §6).
    profile: str = "1.21.1"
    host: str = "127.0.0.1"
    port: int = 8008
    # Origins allowed to call the sidecar: the Vite dev server and the bundled
    # Tauri webview (origin differs per platform).
    cors_origins: list[str] = [
        "http://localhost:1420",
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ]


settings = Settings()
