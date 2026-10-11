from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Grahith Rao | Bulk Certificate Generator"
    project_owner: str = "Grahith Rao"
    environment: str = "development"
    debug: bool = False

    # Database
    database_url: str = "sqlite:///./certificates.db"

    # Storage paths
    storage_dir: Path = Path("./storage")
    fonts_dir: Path = Path("./assets/fonts")

    # Batch limits & Worker config
    max_batch_size: int = 1000
    worker_poll_interval: float = 1.0
    worker_batch_size: int = 50

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def certificates_dir(self) -> Path:
        return self.storage_dir / "certificates"

    def ensure_directories(self) -> None:
        """Create necessary runtime directories if they do not exist."""
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.certificates_dir.mkdir(parents=True, exist_ok=True)
        self.fonts_dir.mkdir(parents=True, exist_ok=True)


# Global settings instance
settings = Settings()
