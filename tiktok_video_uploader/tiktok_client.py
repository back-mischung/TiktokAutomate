from __future__ import annotations

import logging
import math
import time
from pathlib import Path
from typing import Any

import requests

from config import require_env, settings
from token_store import TokenBundle, TokenStore
from video_validator import VideoValidator


logger = logging.getLogger(__name__)
MIN_CHUNK_SIZE = 5 * 1024 * 1024
MAX_CHUNK_SIZE = 64 * 1024 * 1024


class TikTokClient:
    def __init__(self, token_store: TokenStore | None = None) -> None:
        require_env(settings.client_key, "TIKTOK_CLIENT_KEY")
        require_env(settings.client_secret, "TIKTOK_CLIENT_SECRET")
        self.token_store = token_store or TokenStore(settings.token_file)
        self.validator = VideoValidator()

    def upload_video_to_inbox(self, video_path: str) -> dict[str, Any]:
        path = self.validator.validate(video_path)
        token = self.get_valid_token()
        video_size = path.stat().st_size
        chunk_size = self._choose_chunk_size(video_size)
        total_chunk_count = self._calculate_total_chunk_count(video_size, chunk_size)
        init_response = self._init_upload(token.access_token, video_size, chunk_size, total_chunk_count)
        upload_url = self._extract_upload_url(init_response)
        logger.info(
            "TikTok Upload initialisiert. video_size=%s chunk_size=%s chunks=%s",
            video_size,
            chunk_size,
            total_chunk_count,
        )
        self._upload_chunks(upload_url, path, video_size, chunk_size, total_chunk_count)
        return init_response

    def get_valid_token(self) -> TokenBundle:
        token = self.token_store.load()
        if token.is_expired:
            logger.info("Access Token ist abgelaufen oder läuft bald ab. Refresh wird ausgeführt.")
            token = self.refresh_access_token(token.refresh_token)
            self.token_store.save(token)
        return token

    def refresh_access_token(self, refresh_token: str) -> TokenBundle:
        response = requests.post(
            settings.token_url,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"},
            data={
                "client_key": settings.client_key,
                "client_secret": settings.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=30,
        )
        if not response.ok:
            raise RuntimeError(f"TikTok Token Refresh fehlgeschlagen: {response.status_code} {response.text}")
        data = response.json()
        if "access_token" not in data:
            raise RuntimeError(f"Unerwartete Refresh-Response: {data}")
        return TokenStore.from_tiktok_response(data)

    def _init_upload(
        self,
        access_token: str,
        video_size: int,
        chunk_size: int,
        total_chunk_count: int,
    ) -> dict[str, Any]:
        payload = {
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": video_size,
                "chunk_size": chunk_size,
                "total_chunk_count": total_chunk_count,
            }
        }
        response = requests.post(
            settings.inbox_upload_init_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json=payload,
            timeout=30,
        )
        if not response.ok:
            self._raise_tiktok_error("Upload-Init fehlgeschlagen", response)
        data = response.json()
        if data.get("error", {}).get("code") not in (None, "ok"):
            raise RuntimeError(f"TikTok Upload-Init Fehler: {data}")
        return data

    def _upload_chunks(
        self,
        upload_url: str,
        path: Path,
        video_size: int,
        chunk_size: int,
        total_chunk_count: int,
    ) -> None:
        with path.open("rb") as file_handle:
            for index in range(total_chunk_count):
                start = index * chunk_size
                file_handle.seek(start)
                bytes_to_read = video_size - start if index == total_chunk_count - 1 else chunk_size
                chunk = file_handle.read(bytes_to_read)
                end = start + len(chunk) - 1
                headers = {
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {start}-{end}/{video_size}",
                }
                logger.info("Uploading chunk %s/%s bytes=%s-%s", index + 1, total_chunk_count, start, end)
                response = requests.put(upload_url, headers=headers, data=chunk, timeout=180)
                if not response.ok:
                    self._raise_tiktok_error(f"Chunk {index + 1}/{total_chunk_count} Upload fehlgeschlagen", response)
                time.sleep(0.2)

    @staticmethod
    def _choose_chunk_size(video_size: int) -> int:
        if video_size <= MAX_CHUNK_SIZE:
            return video_size
        configured = settings.chunk_size_bytes
        if video_size < MIN_CHUNK_SIZE:
            return video_size
        chunk_size = min(max(configured, MIN_CHUNK_SIZE), MAX_CHUNK_SIZE)
        total_chunks = max(1, video_size // chunk_size)
        if total_chunks > 1000:
            chunk_size = math.ceil(video_size / 1000)
            chunk_size = min(max(chunk_size, MIN_CHUNK_SIZE), MAX_CHUNK_SIZE)
        return chunk_size

    @staticmethod
    def _calculate_total_chunk_count(video_size: int, chunk_size: int) -> int:
        return max(1, math.ceil(video_size / chunk_size))

    @staticmethod
    def _extract_upload_url(response_data: dict[str, Any]) -> str:
        data = response_data.get("data", {})
        upload_url = data.get("upload_url")
        if not upload_url:
            raise RuntimeError(f"Keine upload_url in TikTok Response gefunden: {response_data}")
        return str(upload_url)

    @staticmethod
    def _raise_tiktok_error(message: str, response: requests.Response) -> None:
        try:
            body: Any = response.json()
        except ValueError:
            body = response.text
        raise RuntimeError(f"{message}: HTTP {response.status_code} {body}")
