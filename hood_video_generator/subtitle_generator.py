from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from moviepy.editor import AudioFileClip

from config import settings


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SubtitleSegment:
    index: int
    start: float
    end: float
    text: str


class SubtitleGenerator:
    def generate_srt(
        self,
        text: str,
        audio_path: Path,
        output_path: Path,
        start_offset: float = 0.0,
        alignment_path: Path | None = None,
        tempo_factor: float = 1.0,
    ) -> Path:
        if alignment_path and alignment_path.exists():
            segments = self._segments_from_alignment(alignment_path, start_offset, tempo_factor)
            logger.info("Using exact ElevenLabs timestamps from %s", alignment_path)
        else:
            duration = self._get_audio_duration(audio_path)
            chunks = self._chunk_text(text)
            segments = self._time_segments(chunks, duration, start_offset)
            logger.warning("Keine ElevenLabs-Zeitstempel gefunden; nutze geschaetztes Untertitel-Timing.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(self._to_srt(segments), encoding="utf-8")
        json_path = output_path.with_suffix(".json")
        json_path.write_text(
            json.dumps([asdict(segment) for segment in segments], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Subtitles saved to %s and %s", output_path, json_path)
        return output_path

    @staticmethod
    def _segments_from_alignment(
        alignment_path: Path,
        start_offset: float,
        tempo_factor: float,
    ) -> list[SubtitleSegment]:
        data = json.loads(alignment_path.read_text(encoding="utf-8"))
        characters = data.get("characters", [])
        starts = data.get("character_start_times_seconds", [])
        ends = data.get("character_end_times_seconds", [])
        if not characters or not (len(characters) == len(starts) == len(ends)):
            raise RuntimeError(f"Ungueltige ElevenLabs-Zeitstempel: {alignment_path}")

        speed = max(0.01, tempo_factor)
        words: list[tuple[str, float, float]] = []
        current_chars: list[str] = []
        current_start: float | None = None
        current_end = 0.0
        for character, start, end in zip(characters, starts, ends):
            if str(character).isspace():
                if current_chars and current_start is not None:
                    words.append(("".join(current_chars), current_start, current_end))
                current_chars = []
                current_start = None
                continue
            if current_start is None:
                current_start = float(start)
            current_chars.append(str(character))
            current_end = float(end)
        if current_chars and current_start is not None:
            words.append(("".join(current_chars), current_start, current_end))

        return [
            SubtitleSegment(
                index=index,
                start=start_offset + start / speed,
                end=start_offset + end / speed,
                text=word,
            )
            for index, (word, start, end) in enumerate(words, start=1)
        ]

    @staticmethod
    def _get_audio_duration(audio_path: Path) -> float:
        with AudioFileClip(str(audio_path)) as clip:
            return float(clip.duration)

    @staticmethod
    def _chunk_text(text: str, min_words: int | None = None, max_words: int | None = None) -> list[str]:
        min_words = settings.subtitle_min_words if min_words is None else min_words
        max_words = settings.subtitle_max_words if max_words is None else max_words
        words = re.findall(r"\S+", text.replace("\n", " "))
        if max_words <= 1:
            return words or [text.strip()]
        chunks: list[str] = []
        current: list[str] = []
        for word in words:
            current.append(word)
            sentence_end = bool(re.search(r"[.!?…]$", word))
            if len(current) >= max_words or (len(current) >= min_words and sentence_end):
                chunks.append(" ".join(current))
                current = []
        if current:
            chunks.append(" ".join(current))
        return chunks or [text.strip()]

    @staticmethod
    def _time_segments(chunks: list[str], duration: float, start_offset: float = 0.0) -> list[SubtitleSegment]:
        weights = [subtitle_weight(chunk) for chunk in chunks]
        total_weight = sum(weights) or 1.0
        cursor = start_offset
        end_time = start_offset + duration
        segments: list[SubtitleSegment] = []
        for index, (chunk, weight) in enumerate(zip(chunks, weights), start=1):
            share = weight / total_weight
            segment_duration = duration * share
            end = min(end_time, cursor + segment_duration)
            segments.append(SubtitleSegment(index=index, start=cursor, end=end, text=chunk))
            cursor = end
        if segments:
            segments[-1] = SubtitleSegment(
                index=segments[-1].index,
                start=segments[-1].start,
                end=end_time,
                text=segments[-1].text,
            )
        return segments

    @staticmethod
    def _to_srt(segments: list[SubtitleSegment]) -> str:
        blocks = []
        for segment in segments:
            blocks.append(
                f"{segment.index}\n"
                f"{format_srt_time(segment.start)} --> {format_srt_time(segment.end)}\n"
                f"{segment.text}\n"
            )
        return "\n".join(blocks)


def format_srt_time(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, ms = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def subtitle_weight(text: str) -> float:
    cleaned = re.sub(r"\s+", "", text)
    letters = max(1, len(cleaned))
    punctuation_pause = 0.0
    if re.search(r"[.!?…]$", text):
        punctuation_pause = 4.0
    elif re.search(r"[,;:]$", text):
        punctuation_pause = 2.0
    return float(letters + punctuation_pause)
