from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    client_key: str
    client_secret: str
    redirect_uri: str
    scopes: str
    token_file: Path
    chunk_size_bytes: int
    authorize_url: str = "https://www.tiktok.com/v2/auth/authorize/"
    token_url: str = "https://open.tiktokapis.com/v2/oauth/token/"
    inbox_upload_init_url: str = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"


def get_settings() -> Settings:
    token_file = Path(os.getenv("TIKTOK_TOKEN_FILE", "tokens.json"))
    if not token_file.is_absolute():
        token_file = ROOT_DIR / token_file
    chunk_size_mb = int(os.getenv("TIKTOK_CHUNK_SIZE_MB", "10"))
    return Settings(
        client_key=os.getenv("TIKTOK_CLIENT_KEY", ""),
        client_secret=os.getenv("TIKTOK_CLIENT_SECRET", ""),
        redirect_uri=os.getenv("TIKTOK_REDIRECT_URI", ""),
        scopes=os.getenv("TIKTOK_SCOPES", "video.upload"),
        token_file=token_file,
        chunk_size_bytes=chunk_size_mb * 1024 * 1024,
    )


settings = get_settings()


def configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def require_env(value: str, name: str) -> str:
    if not value:
        raise RuntimeError(f"{name} fehlt. Bitte in .env eintragen.")
    return value
