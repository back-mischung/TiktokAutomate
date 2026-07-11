from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class TokenBundle:
    access_token: str
    refresh_token: str
    expires_at: int
    refresh_expires_at: int | None = None
    open_id: str | None = None
    scope: str | None = None
    token_type: str = "Bearer"

    @property
    def is_expired(self) -> bool:
        return int(time.time()) >= self.expires_at - 120


class TokenStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> TokenBundle:
        if not self.path.exists():
            raise RuntimeError("Kein tokens.json gefunden. Bitte zuerst `python main.py auth` ausführen.")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return TokenBundle(**data)

    def save(self, token: TokenBundle) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(token), ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def from_tiktok_response(data: dict[str, Any]) -> TokenBundle:
        now = int(time.time())
        expires_in = int(data.get("expires_in", 0))
        refresh_expires_in = data.get("refresh_expires_in")
        return TokenBundle(
            access_token=str(data["access_token"]),
            refresh_token=str(data["refresh_token"]),
            expires_at=now + expires_in,
            refresh_expires_at=now + int(refresh_expires_in) if refresh_expires_in is not None else None,
            open_id=data.get("open_id"),
            scope=data.get("scope"),
            token_type=data.get("token_type", "Bearer"),
        )

