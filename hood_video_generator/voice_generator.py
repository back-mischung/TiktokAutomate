from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

import requests

from config import require_env, settings
from usage_tracker import UsageTracker


logger = logging.getLogger(__name__)


class VoiceGenerator:
    def __init__(
        self,
        stability: float = 0.45,
        similarity_boost: float = 0.75,
        style: float = 0.2,
        speed: float | None = None,
        use_speaker_boost: bool = True,
        usage_tracker: UsageTracker | None = None,
    ) -> None:
        self.api_key = require_env(settings.elevenlabs_api_key, "ELEVENLABS_API_KEY")
        self.voice_id = require_env(settings.elevenlabs_voice_id, "ELEVENLABS_VOICE_ID")
        self.usage_tracker = usage_tracker
        self.voice_settings = {
            "stability": stability,
            "similarity_boost": similarity_boost,
            "style": style,
            "speed": 1.0 if speed is None else speed,
            "use_speaker_boost": use_speaker_boost,
        }

    def generate_voiceover(self, text: str, output_path: Path, alignment_path: Path | None = None) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        endpoint = "with-timestamps" if alignment_path else ""
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/{endpoint}".rstrip("/")
        headers = {
            "xi-api-key": self.api_key,
            "Accept": "application/json" if alignment_path else "audio/mpeg",
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "model_id": settings.elevenlabs_model_id,
            "voice_settings": self.voice_settings,
        }
        if self.usage_tracker:
            self.usage_tracker.add_elevenlabs_tts(settings.elevenlabs_model_id, output_path.stem, text)
        logger.info("Generating ElevenLabs voiceover with model %s", settings.elevenlabs_model_id)
        response = requests.post(url, headers=headers, json=payload, timeout=180)
        if response.status_code == 401:
            raise RuntimeError("ElevenLabs API-Key ist ungültig oder fehlt.")
        if response.status_code == 404:
            raise RuntimeError("ElevenLabs Voice-ID wurde nicht gefunden.")
        if response.status_code in {402, 429}:
            raise RuntimeError("ElevenLabs Credits/Limit reichen nicht aus oder Rate-Limit erreicht.")
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(f"ElevenLabs Fehler: {response.text[:500]}") from exc
        if alignment_path:
            data = response.json()
            audio_base64 = data.get("audio_base64")
            alignment = data.get("normalized_alignment") or data.get("alignment")
            if not audio_base64 or not alignment:
                raise RuntimeError("ElevenLabs hat Audio oder Zeitstempel nicht geliefert.")
            output_path.write_bytes(base64.b64decode(audio_base64))
            alignment_path.parent.mkdir(parents=True, exist_ok=True)
            alignment_path.write_text(json.dumps(alignment, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            output_path.write_bytes(response.content)
        logger.info("Voiceover saved to %s", output_path)
        return output_path
