from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import imageio_ffmpeg
from moviepy.editor import AudioFileClip, CompositeAudioClip, afx

from config import ROOT_DIR, settings


logger = logging.getLogger(__name__)


SOUND_ALIASES = {
    "signature_hit": ["MOVIE LOGO INTRO SOUND EFFECT HD"],
    "low_boom": ["Cinematic Boom - sound effect - [High quality]"],
    "short_whoosh": ["Long Cinematic Whoosh Sound Effect"],
    "glitch_short": ["Glitch Sound Effect"],
    "dark_ambient_loop": ["Night Traffic Sounds"],
    "deep_riser": ["Riser - Sound Effect (Free)", "Riser Sound Effect No Copyright (Free To Use For Video Editing)#soundeffects#editing #nocopyright"],
    "glitch_heavy": ["Glitch Sound Effect"],
    "sanguine_flash": ["Flash Sound Effect"],
    "tape_stop": ["Slow Motion Sound Effect"],
    "heartbeat_low": ["Heartbeat Sound Effect"],
    "city_night_ambience": ["Night Traffic Sounds"],
}

TWIST_SIGNALS = [
    "plötzlich", "ploetzlich", "auf einmal", "aber", "dann stand", "ich schwöre", "ich schwoere",
    "bruder", "digga", "nachricht", "anruf", "stimme", "schatten", "tür", "tuer",
    "kennzeichen", "polizei", "rannte", "sah mich an", "war offen", "war weg", "stand da",
]

DIGITAL_SIGNALS = [
    "nachricht", "whatsapp", "handy", "anruf", "nummer", "video", "foto", "standort",
    "kamera", "aufnahme", "screenshot", "stimme", "display",
]


@dataclass
class SoundEvent:
    sound_name: str
    original_file_path: str
    converted_file_path: str
    start_time: float
    end_time: float
    volume: float
    reason: str
    related_scene_index: int
    related_text: str
    is_optional: bool
    was_applied: bool
    conversion_needed: bool
    conversion_successful: bool


@dataclass(frozen=True)
class PreparedSound:
    sound_name: str
    original_path: Path | None
    audio_path: Path | None
    conversion_needed: bool
    conversion_successful: bool


class SoundDesigner:
    def __init__(self, sound_plan_path: Path) -> None:
        self.sound_plan_path = sound_plan_path
        self.events: list[SoundEvent] = []

    def mix(
        self,
        base_voice_path: Path,
        output_path: Path,
        story_text: str,
        alignment_path: Path | None,
        image_prompts_path: Path | None,
        duration: float,
    ) -> Path:
        if not settings.sound_design_enabled:
            self._save_plan()
            return base_voice_path

        voice = AudioFileClip(str(base_voice_path))
        layers = [voice]
        scene_starts = self._scene_starts(story_text, alignment_path, image_prompts_path)
        signal_events = self._signal_times(story_text, alignment_path, scene_starts)

        if settings.use_ambient_loop:
            self._add_loop(layers, "dark_ambient_loop", 0.0, duration, settings.ambient_volume, "very quiet background ambience", 0, "", True)

        if settings.use_signature_hit:
            self._add_one_shot(layers, "signature_hit", 0.72, settings.signature_hit_volume, "signature sound on series overlay", 0, "Hood Storys overlay", False, max_duration=0.9)

        if settings.use_transition_whoosh:
            for scene_index, start in enumerate(scene_starts[1:], start=1):
                self._add_one_shot(
                    layers,
                    "short_whoosh",
                    max(0.0, start - 0.08),
                    settings.transition_whoosh_volume,
                    "real story image transition",
                    scene_index,
                    "",
                    False,
                    max_duration=0.55,
                )

        twist_events = signal_events["twist"][:4]
        if settings.use_low_boom_on_twists:
            for event in twist_events:
                self._add_one_shot(
                    layers,
                    "low_boom",
                    event["time"],
                    settings.low_boom_volume,
                    "twist or threat signal word",
                    event["scene_index"],
                    event["text"],
                    False,
                    max_duration=0.9,
                )

        if settings.use_glitch_on_digital_moments:
            for event in signal_events["digital"][:3]:
                self._add_one_shot(
                    layers,
                    "glitch_short",
                    event["time"],
                    settings.glitch_volume,
                    "digital or unnatural story moment",
                    event["scene_index"],
                    event["text"],
                    False,
                    max_duration=0.45,
                )

        if settings.use_riser_before_twist and twist_events:
            first_twist = twist_events[0]
            self._add_one_shot(
                layers,
                "deep_riser",
                max(0.0, first_twist["time"] - 1.4),
                settings.riser_volume,
                "short riser before first twist",
                first_twist["scene_index"],
                first_twist["text"],
                True,
                max_duration=1.4,
            )

        combined = CompositeAudioClip(layers).set_duration(duration)
        combined.write_audiofile(str(output_path), fps=44100, logger=None)
        for clip in layers:
            clip.close()
        combined.close()
        self._save_plan()
        return output_path

    def prepare_sound_asset(self, sound_name: str) -> PreparedSound:
        sounds_dir = resolve_asset(settings.sound_assets_dir)
        converted_dir = resolve_asset(settings.converted_sound_output_dir)
        candidates = [sound_name, *SOUND_ALIASES.get(sound_name, [])]
        for stem in candidates:
            for suffix in (".wav", ".mp3", ".mp4"):
                path = sounds_dir / f"{stem}{suffix}"
                if not path.exists():
                    continue
                if suffix in {".wav", ".mp3"}:
                    return PreparedSound(sound_name, path, path, False, True)
                converted = converted_dir / f"{sound_name}.mp3"
                if converted.exists():
                    return PreparedSound(sound_name, path, converted, True, True)
                if not settings.auto_convert_mp4_sounds:
                    logger.warning("Sound %s liegt nur als mp4 vor, Auto-Konvertierung ist deaktiviert.", sound_name)
                    return PreparedSound(sound_name, path, None, True, False)
                converted_dir.mkdir(parents=True, exist_ok=True)
                success = convert_mp4_audio(path, converted)
                if success:
                    return PreparedSound(sound_name, path, converted, True, True)
                return PreparedSound(sound_name, path, None, True, False)
        logger.warning("Sound fehlt und wird uebersprungen: %s", sound_name)
        return PreparedSound(sound_name, None, None, False, False)

    def _add_one_shot(
        self,
        layers: list,
        sound_name: str,
        start: float,
        volume: float,
        reason: str,
        scene_index: int,
        related_text: str,
        is_optional: bool,
        max_duration: float,
    ) -> None:
        prepared = self.prepare_sound_asset(sound_name)
        end_time = start
        was_applied = False
        if prepared.audio_path and prepared.conversion_successful:
            clip = AudioFileClip(str(prepared.audio_path))
            clip = clip.subclip(0, min(max_duration, clip.duration)).volumex(volume).set_start(start)
            end_time = start + float(clip.duration)
            layers.append(clip)
            was_applied = True
        self.events.append(
            SoundEvent(
                sound_name=sound_name,
                original_file_path=str(prepared.original_path or ""),
                converted_file_path=str(prepared.audio_path or ""),
                start_time=round(start, 3),
                end_time=round(end_time, 3),
                volume=volume,
                reason=reason,
                related_scene_index=scene_index,
                related_text=related_text,
                is_optional=is_optional,
                was_applied=was_applied,
                conversion_needed=prepared.conversion_needed,
                conversion_successful=prepared.conversion_successful,
            )
        )

    def _add_loop(
        self,
        layers: list,
        sound_name: str,
        start: float,
        duration: float,
        volume: float,
        reason: str,
        scene_index: int,
        related_text: str,
        is_optional: bool,
    ) -> None:
        prepared = self.prepare_sound_asset(sound_name)
        was_applied = False
        if prepared.audio_path and prepared.conversion_successful:
            clip = AudioFileClip(str(prepared.audio_path)).volumex(volume)
            if clip.duration < duration:
                clip = clip.fx(afx.audio_loop, duration=duration)
            else:
                clip = clip.subclip(0, duration)
            clip = clip.set_start(start)
            layers.append(clip)
            was_applied = True
        self.events.append(
            SoundEvent(
                sound_name=sound_name,
                original_file_path=str(prepared.original_path or ""),
                converted_file_path=str(prepared.audio_path or ""),
                start_time=round(start, 3),
                end_time=round(start + duration, 3),
                volume=volume,
                reason=reason,
                related_scene_index=scene_index,
                related_text=related_text,
                is_optional=is_optional,
                was_applied=was_applied,
                conversion_needed=prepared.conversion_needed,
                conversion_successful=prepared.conversion_successful,
            )
        )

    def _scene_starts(self, story_text: str, alignment_path: Path | None, image_prompts_path: Path | None) -> list[float]:
        words = words_from_alignment(alignment_path)
        starts = [0.0]
        if not image_prompts_path or not image_prompts_path.exists() or not words:
            return starts
        try:
            plan = json.loads(image_prompts_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return starts
        anchors = [str(item.get("start_text", "")).strip() for item in plan[2:] if isinstance(item, dict)]
        search_from = 0
        normalized_words = [word for word, _ in words]
        for anchor in anchors:
            anchor_words = [normalize_word(word) for word in anchor.split()]
            anchor_words = [word for word in anchor_words if word]
            match_index = find_word_sequence(normalized_words, anchor_words, search_from)
            if match_index is None:
                continue
            starts.append(words[match_index][1] / max(settings.voice_speed, 0.01))
            search_from = match_index + len(anchor_words)
        return sorted(set(round(start, 3) for start in starts))

    def _signal_times(self, story_text: str, alignment_path: Path | None, scene_starts: list[float]) -> dict[str, list[dict]]:
        words = words_from_alignment(alignment_path)
        if not words:
            return {"twist": [], "digital": []}
        normalized_story = story_text.lower()
        events = {"twist": [], "digital": []}
        for index, (word, start) in enumerate(words):
            phrase2 = f"{word} {words[index + 1][0]}" if index + 1 < len(words) else word
            raw_text = phrase2 if phrase2 in TWIST_SIGNALS or phrase2 in DIGITAL_SIGNALS else word
            time = start / max(settings.voice_speed, 0.01)
            scene_index = scene_index_for_time(time, scene_starts)
            if word in TWIST_SIGNALS or phrase2 in TWIST_SIGNALS:
                events["twist"].append({"time": time, "scene_index": scene_index, "text": raw_text})
            if word in DIGITAL_SIGNALS or phrase2 in DIGITAL_SIGNALS:
                events["digital"].append({"time": time, "scene_index": scene_index, "text": raw_text})
        if not events["twist"] and any(signal in normalized_story for signal in TWIST_SIGNALS):
            events["twist"].append({"time": 4.0, "scene_index": scene_index_for_time(4.0, scene_starts), "text": "story twist"})
        return events

    def _save_plan(self) -> None:
        self.sound_plan_path.parent.mkdir(parents=True, exist_ok=True)
        self.sound_plan_path.write_text(
            json.dumps([asdict(event) for event in self.events], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def convert_mp4_audio(input_path: Path, output_path: Path) -> bool:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    try:
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(input_path),
                "-vn",
                "-acodec",
                "libmp3lame",
                "-q:a",
                "3",
                str(output_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (OSError, subprocess.CalledProcessError) as exc:
        logger.warning("Sound konnte nicht konvertiert werden: %s (%s)", input_path, exc)
        return False


def words_from_alignment(alignment_path: Path | None) -> list[tuple[str, float]]:
    if not alignment_path or not alignment_path.exists():
        return []
    data = json.loads(alignment_path.read_text(encoding="utf-8"))
    characters = data.get("characters", [])
    starts = data.get("character_start_times_seconds", [])
    if not characters or len(characters) != len(starts):
        return []
    words: list[tuple[str, float]] = []
    current: list[str] = []
    current_start: float | None = None
    for character, start in zip(characters, starts):
        character = str(character)
        if character.isspace():
            if current and current_start is not None:
                normalized = normalize_word("".join(current))
                if normalized:
                    words.append((normalized, current_start))
            current = []
            current_start = None
            continue
        if current_start is None:
            current_start = float(start)
        current.append(character)
    if current and current_start is not None:
        normalized = normalize_word("".join(current))
        if normalized:
            words.append((normalized, current_start))
    return words


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


def resolve_asset(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT_DIR / path
