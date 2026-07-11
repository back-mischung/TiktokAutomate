from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from moviepy.editor import AudioFileClip

from config import settings


logger = logging.getLogger(__name__)


EMPHASIS_WORDS = {
    "plötzlich",
    "ploetzlich",
    "bruder",
    "digga",
    "polizei",
    "nachricht",
    "anruf",
    "tür",
    "tuer",
    "schatten",
    "kennzeichen",
    "weg",
    "offen",
    "falsch",
    "leer",
    "stimme",
    "rannte",
}

EMPHASIS_PHRASES = {"stand da", "sah mich an"}


@dataclass(frozen=True)
class WordTimestamp:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class SubtitleSegment:
    index: int
    start: float
    end: float
    text: str
    words: list[str]
    is_emphasis: bool = False
    emphasis_word: str = ""
    scene_index: int = 0


class SubtitleGenerator:
    def generate_srt(
        self,
        text: str,
        audio_path: Path,
        output_path: Path,
        start_offset: float = 0.0,
        alignment_path: Path | None = None,
        tempo_factor: float = 1.0,
        subtitle_groups_path: Path | None = None,
        image_prompts_path: Path | None = None,
    ) -> Path:
        if alignment_path and alignment_path.exists():
            words = self._words_from_alignment(alignment_path, start_offset, tempo_factor)
            logger.info("Using exact ElevenLabs timestamps from %s", alignment_path)
        else:
            duration = self._get_audio_duration(audio_path)
            words = self._fallback_words(text, duration, start_offset)
            logger.warning("Keine ElevenLabs-Zeitstempel gefunden; nutze geschaetztes Untertitel-Gruppen-Timing.")

        scene_starts = self._scene_starts_from_prompts(words, image_prompts_path)
        if settings.subtitle_mode == "word_by_word":
            segments = self._word_by_word_segments(words, scene_starts)
        else:
            grouped = settings.subtitle_mode in {"grouped", "grouped_emphasis"}
            segments = self.build_subtitle_groups_from_word_timestamps(
                words,
                scene_starts=scene_starts,
                with_emphasis=settings.subtitle_mode == "grouped_emphasis",
                grouped=grouped,
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(self._to_srt(segments), encoding="utf-8")
        json_path = output_path.with_suffix(".json")
        serialized = [asdict(segment) for segment in segments]
        json_path.write_text(json.dumps(serialized, ensure_ascii=False, indent=2), encoding="utf-8")
        if subtitle_groups_path:
            subtitle_groups_path.write_text(
                json.dumps(
                    [
                        {
                            "group_index": segment.index,
                            "text": segment.text,
                            "words": segment.words,
                            "start_time": segment.start,
                            "end_time": segment.end,
                            "is_emphasis": segment.is_emphasis,
                            "emphasis_word": segment.emphasis_word,
                            "scene_index": segment.scene_index,
                        }
                        for segment in segments
                    ],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        logger.info("Subtitles saved to %s and %s", output_path, json_path)
        return output_path

    def build_subtitle_groups_from_word_timestamps(
        self,
        words: list[WordTimestamp],
        scene_starts: list[float],
        with_emphasis: bool,
        grouped: bool = True,
    ) -> list[SubtitleSegment]:
        if not grouped:
            return self._word_by_word_segments(words, scene_starts)
        segments: list[SubtitleSegment] = []
        current: list[WordTimestamp] = []
        last_emphasis_time = -99.0
        index = 1
        skip_next = False
        for word_index, word in enumerate(words):
            if skip_next:
                skip_next = False
                continue
            normalized = normalize_word(word.text)
            is_emphasis_word = with_emphasis and self.detect_emphasis_words(words, word_index)
            if is_emphasis_word and word.start - last_emphasis_time >= 2.8:
                if current:
                    segment = self._segment_from_words(index, current, scene_starts)
                    segments.append(segment)
                    index += 1
                    current = []
                emphasis_text = self._emphasis_text(words, word_index)
                segment_words = [word]
                if " " in emphasis_text and word_index + 1 < len(words):
                    segment_words = [word, words[word_index + 1]]
                    skip_next = True
                segments.append(
                    self._segment_from_words(
                        index,
                        segment_words,
                        scene_starts,
                        is_emphasis=True,
                        emphasis_word=emphasis_text,
                    )
                )
                index += 1
                last_emphasis_time = word.start
                continue

            current.append(word)
            if self._should_close_group(current, next_word=words[word_index + 1] if word_index + 1 < len(words) else None):
                segment = self._segment_from_words(index, current, scene_starts)
                segments.append(segment)
                index += 1
                current = []
        if current:
            segments.append(self._segment_from_words(index, current, scene_starts))
        return self.split_subtitles_at_scene_changes(segments, scene_starts)

    @staticmethod
    def detect_emphasis_words(words: list[WordTimestamp], index: int) -> bool:
        word = normalize_word(words[index].text)
        if word in EMPHASIS_WORDS:
            return True
        if index + 1 < len(words):
            phrase = f"{word} {normalize_word(words[index + 1].text)}"
            return phrase in EMPHASIS_PHRASES
        return False

    @staticmethod
    def split_subtitles_at_scene_changes(segments: list[SubtitleSegment], scene_starts: list[float]) -> list[SubtitleSegment]:
        adjusted: list[SubtitleSegment] = []
        index = 1
        for segment in segments:
            split_points = [point for point in scene_starts[1:] if segment.start < point < segment.end]
            if not split_points or len(segment.words) <= 1:
                adjusted.append(reindex_segment(segment, index))
                index += 1
                continue
            midpoint = split_points[0]
            words_left = [word for word in segment.words[: max(1, len(segment.words) // 2)]]
            words_right = [word for word in segment.words[len(words_left):]]
            adjusted.append(
                SubtitleSegment(
                    index=index,
                    start=segment.start,
                    end=midpoint,
                    text=" ".join(words_left),
                    words=words_left,
                    is_emphasis=segment.is_emphasis,
                    emphasis_word=segment.emphasis_word,
                    scene_index=scene_index_for_time(segment.start, scene_starts),
                )
            )
            index += 1
            if words_right:
                adjusted.append(
                    SubtitleSegment(
                        index=index,
                        start=midpoint,
                        end=segment.end,
                        text=" ".join(words_right),
                        words=words_right,
                        scene_index=scene_index_for_time(midpoint, scene_starts),
                    )
                )
                index += 1
        return adjusted

    @staticmethod
    def _should_close_group(current: list[WordTimestamp], next_word: WordTimestamp | None) -> bool:
        if not current:
            return False
        max_words = settings.subtitle_max_words if settings.subtitle_max_words >= 2 else 4
        duration = current[-1].end - current[0].start
        word_count = len(current)
        sentence_break = bool(re.search(r"[.!?,;:]$", current[-1].text))
        pause_break = bool(next_word and next_word.start - current[-1].end > 0.22)
        if word_count >= max_words:
            return True
        if duration >= 1.35 and word_count >= 2:
            return True
        if sentence_break and word_count >= 2:
            return True
        if pause_break and word_count >= 2:
            return True
        return False

    @staticmethod
    def _segment_from_words(
        index: int,
        words: list[WordTimestamp],
        scene_starts: list[float],
        is_emphasis: bool = False,
        emphasis_word: str = "",
    ) -> SubtitleSegment:
        start = words[0].start
        end = max(words[-1].end, start + 0.25)
        if end - start > 1.6:
            end = start + 1.6
        word_texts = [word.text for word in words]
        return SubtitleSegment(
            index=index,
            start=start,
            end=end,
            text=" ".join(word_texts),
            words=word_texts,
            is_emphasis=is_emphasis,
            emphasis_word=emphasis_word,
            scene_index=scene_index_for_time(start, scene_starts),
        )

    @staticmethod
    def _emphasis_text(words: list[WordTimestamp], index: int) -> str:
        word = normalize_word(words[index].text)
        if index + 1 < len(words):
            phrase = f"{word} {normalize_word(words[index + 1].text)}"
            if phrase in EMPHASIS_PHRASES:
                return f"{words[index].text} {words[index + 1].text}"
        return words[index].text

    @staticmethod
    def _word_by_word_segments(words: list[WordTimestamp], scene_starts: list[float]) -> list[SubtitleSegment]:
        return [
            SubtitleSegment(
                index=index,
                start=word.start,
                end=max(word.end, word.start + 0.2),
                text=word.text,
                words=[word.text],
                scene_index=scene_index_for_time(word.start, scene_starts),
            )
            for index, word in enumerate(words, start=1)
        ]

    @staticmethod
    def _words_from_alignment(
        alignment_path: Path,
        start_offset: float,
        tempo_factor: float,
    ) -> list[WordTimestamp]:
        data = json.loads(alignment_path.read_text(encoding="utf-8"))
        characters = data.get("characters", [])
        starts = data.get("character_start_times_seconds", [])
        ends = data.get("character_end_times_seconds", [])
        if not characters or not (len(characters) == len(starts) == len(ends)):
            raise RuntimeError(f"Ungueltige ElevenLabs-Zeitstempel: {alignment_path}")

        speed = max(0.01, tempo_factor)
        words: list[WordTimestamp] = []
        current_chars: list[str] = []
        current_start: float | None = None
        current_end = 0.0
        for character, start, end in zip(characters, starts, ends):
            if str(character).isspace():
                if current_chars and current_start is not None:
                    words.append(
                        WordTimestamp(
                            text="".join(current_chars),
                            start=start_offset + current_start / speed,
                            end=start_offset + current_end / speed,
                        )
                    )
                current_chars = []
                current_start = None
                continue
            if current_start is None:
                current_start = float(start)
            current_chars.append(str(character))
            current_end = float(end)
        if current_chars and current_start is not None:
            words.append(
                WordTimestamp(
                    text="".join(current_chars),
                    start=start_offset + current_start / speed,
                    end=start_offset + current_end / speed,
                )
            )
        return words

    @staticmethod
    def _fallback_words(text: str, duration: float, start_offset: float) -> list[WordTimestamp]:
        raw_words = re.findall(r"\S+", text.replace("\n", " "))
        if not raw_words:
            return []
        weights = [max(1, len(re.sub(r"\W", "", word))) for word in raw_words]
        total = sum(weights) or 1
        cursor = start_offset
        words: list[WordTimestamp] = []
        for word, weight in zip(raw_words, weights):
            word_duration = duration * (weight / total)
            end = cursor + word_duration
            words.append(WordTimestamp(text=word, start=cursor, end=end))
            cursor = end
        return words

    @staticmethod
    def _scene_starts_from_prompts(words: list[WordTimestamp], image_prompts_path: Path | None) -> list[float]:
        scene_starts = [0.0]
        if not image_prompts_path or not image_prompts_path.exists() or not words:
            return scene_starts
        try:
            plan = json.loads(image_prompts_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return scene_starts
        anchors = [str(item.get("start_text", "")).strip() for item in plan[2:] if isinstance(item, dict)]
        search_from = 0
        normalized_words = [normalize_word(word.text) for word in words]
        for anchor in anchors:
            anchor_words = [normalize_word(word) for word in anchor.split()]
            anchor_words = [word for word in anchor_words if word]
            match_index = find_word_sequence(normalized_words, anchor_words, search_from)
            if match_index is None:
                continue
            scene_starts.append(words[match_index].start)
            search_from = match_index + len(anchor_words)
        return sorted(set(round(value, 3) for value in scene_starts))

    @staticmethod
    def _get_audio_duration(audio_path: Path) -> float:
        with AudioFileClip(str(audio_path)) as clip:
            return float(clip.duration)

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


def normalize_word(value: str) -> str:
    value = value.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"[^\w]", "", value, flags=re.UNICODE)


def find_word_sequence(words: list[str], anchor_words: list[str], start_index: int) -> int | None:
    if not anchor_words:
        return None
    last_start = len(words) - len(anchor_words)
    for index in range(start_index, last_start + 1):
        if words[index:index + len(anchor_words)] == anchor_words:
            return index
    return None


def scene_index_for_time(start: float, scene_starts: list[float]) -> int:
    scene_index = 0
    for index, scene_start in enumerate(scene_starts):
        if start >= scene_start:
            scene_index = index
    return scene_index


def reindex_segment(segment: SubtitleSegment, index: int) -> SubtitleSegment:
    return SubtitleSegment(
        index=index,
        start=segment.start,
        end=segment.end,
        text=segment.text,
        words=segment.words,
        is_emphasis=segment.is_emphasis,
        emphasis_word=segment.emphasis_word,
        scene_index=segment.scene_index,
    )
