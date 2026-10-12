import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    storage_dir: Path
    admin_token: str


def load_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("DATABASE_URL", "sqlite:///./signage.db"),
        storage_dir=Path(os.environ.get("STORAGE_DIR", "./storage")),
        admin_token=os.environ.get("ADMIN_TOKEN", ""),
    )


settings = load_settings()
