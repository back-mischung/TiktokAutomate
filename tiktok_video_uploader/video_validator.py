from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path


logger = logging.getLogger(__name__)


class VideoValidator:
    def validate(self, video_path: str | Path) -> Path:
        path = Path(video_path).expanduser().resolve()
        if not path.exists():
            raise RuntimeError(f"Videodatei existiert nicht: {path}")
        if path.suffix.lower() != ".mp4":
            raise RuntimeError("TikTok Upload erwartet eine .mp4-Datei.")
        if path.stat().st_size <= 0:
            raise RuntimeError("Videodatei ist leer.")
        self._warn_if_codec_unusual(path)
        return path

    def _warn_if_codec_unusual(self, path: Path) -> None:
        if shutil.which("ffprobe") is None:
            logger.warning("ffprobe ist nicht installiert. Codec-Prüfung wird übersprungen.")
            return
        command = [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=30)
            data = json.loads(result.stdout)
        except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
            logger.warning("ffprobe konnte das Video nicht prüfen: %s", exc)
            return
        streams = data.get("streams", [])
        video_codecs = [stream.get("codec_name") for stream in streams if stream.get("codec_type") == "video"]
        audio_codecs = [stream.get("codec_name") for stream in streams if stream.get("codec_type") == "audio"]
        if "h264" not in video_codecs:
            logger.warning("Video ist möglicherweise nicht H.264. Gefunden: %s", video_codecs or "kein Videostream")
        if audio_codecs and "aac" not in audio_codecs:
            logger.warning("Audio ist möglicherweise nicht AAC. Gefunden: %s", audio_codecs)

