from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class UsageEvent:
    service: str
    endpoint: str
    model: str
    description: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    characters: int = 0
    estimated_credits: int = 0
    estimated_usd: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class UsageTracker:
    def __init__(
        self,
        output_path: Path,
        text_input_usd_per_1m: float,
        text_output_usd_per_1m: float,
        image_estimated_usd_per_image: float,
    ) -> None:
        self.output_path = output_path
        self.text_input_usd_per_1m = text_input_usd_per_1m
        self.text_output_usd_per_1m = text_output_usd_per_1m
        self.image_estimated_usd_per_image = image_estimated_usd_per_image
        self.events: list[UsageEvent] = []

    def add_openai_response(self, response: Any, model: str, description: str) -> None:
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", input_tokens + output_tokens) or 0)
        estimated_usd = (
            input_tokens * self.text_input_usd_per_1m / 1_000_000
            + output_tokens * self.text_output_usd_per_1m / 1_000_000
        )
        self.events.append(
            UsageEvent(
                service="openai",
                endpoint="responses.create",
                model=model,
                description=description,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                estimated_usd=estimated_usd,
            )
        )

    def add_openai_image(self, model: str, description: str, metadata: dict[str, Any]) -> None:
        self.events.append(
            UsageEvent(
                service="openai",
                endpoint="images.generate",
                model=model,
                description=description,
                estimated_usd=self.image_estimated_usd_per_image,
                metadata=metadata,
            )
        )

    def add_elevenlabs_tts(self, model: str, description: str, text: str) -> None:
        characters = len(text)
        self.events.append(
            UsageEvent(
                service="elevenlabs",
                endpoint="text-to-speech",
                model=model,
                description=description,
                characters=characters,
                estimated_credits=characters,
                metadata={"note": "ElevenLabs credits are approximately character-based for TTS."},
            )
        )

    def save(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        totals = {
            "openai_estimated_usd": round(sum(event.estimated_usd for event in self.events if event.service == "openai"), 6),
            "elevenlabs_estimated_credits": sum(event.estimated_credits for event in self.events if event.service == "elevenlabs"),
            "openai_response_requests": sum(1 for event in self.events if event.endpoint == "responses.create"),
            "openai_image_requests": sum(1 for event in self.events if event.endpoint == "images.generate"),
            "elevenlabs_tts_requests": sum(1 for event in self.events if event.service == "elevenlabs"),
        }
        payload = {
            "created_at": int(time.time()),
            "totals": totals,
            "events": [asdict(event) for event in self.events],
        }
        self.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
