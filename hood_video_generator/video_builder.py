from __future__ import annotations

import json
import logging
import math
import re
from pathlib import Path

import numpy as np
from moviepy.editor import AudioFileClip, CompositeAudioClip, CompositeVideoClip, ImageClip, VideoClip, afx, concatenate_videoclips
from PIL import Image, ImageDraw, ImageFont

from config import ROOT_DIR, settings
from story_metadata import StoryMetadata, load_metadata


logger = logging.getLogger(__name__)

if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.Resampling.LANCZOS


class VideoBuilder:
    def build_video(
        self,
        image_paths: list[Path],
        audio_path: Path,
        subtitles_path: Path,
        output_path: Path,
        metadata_path: Path | None = None,
        image_prompts_path: Path | None = None,
        alignment_path: Path | None = None,
    ) -> Path:
        if len(image_paths) != settings.total_image_count:
            raise RuntimeError(f"Es werden genau {settings.total_image_count} Bilder erwartet, gefunden: {len(image_paths)}")
        audio = AudioFileClip(str(audio_path))
        metadata = load_metadata(metadata_path) if metadata_path else None
        clips = self._build_visual_clips(
            image_paths,
            audio.duration,
            metadata,
            image_prompts_path,
            alignment_path,
        )
        base = concatenate_videoclips(clips, method="compose", padding=0)
        audio = self._mix_background_music(audio)
        base = base.set_duration(audio.duration).set_audio(audio)
        subtitle_clips = self._build_subtitle_clips(subtitles_path)
        video = CompositeVideoClip([base, *subtitle_clips], size=(settings.video_width, settings.video_height))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Exporting final video to %s", output_path)
        video.write_videofile(
            str(output_path),
            codec="libx264",
            audio_codec="aac",
            fps=settings.video_fps,
            threads=4,
            preset="medium",
        )
        audio.close()
        video.close()
        base.close()
        return output_path

    def _build_visual_clips(
        self,
        image_paths: list[Path],
        audio_duration: float,
        metadata: StoryMetadata | None,
        image_prompts_path: Path | None = None,
        alignment_path: Path | None = None,
    ) -> list[VideoClip]:
        outro = None
        if settings.outro_enabled:
            outro = self._outro_clip(
                settings.outro_duration,
            )
        story_images = image_paths[1:]
        asset_duration = sum(clip.duration for clip in [outro] if clip is not None)
        story_duration = max(1.0, audio_duration - asset_duration)
        image_schedule = self._story_image_schedule(
            len(story_images),
            story_duration,
            image_prompts_path,
            alignment_path,
        )
        clips: list[VideoClip] = []
        for animation_index, (image_index, duration) in enumerate(image_schedule):
            clip = self._ken_burns_clip(story_images[image_index], duration, animation_index)
            if animation_index == 0:
                title_overlay = self._series_overlay_clip(metadata, start=0.75, duration=1.2)
                if title_overlay:
                    clip = CompositeVideoClip([clip, title_overlay], size=(settings.video_width, settings.video_height)).set_duration(duration)
            clips.append(clip)
        if outro:
            clips.append(outro)
        return clips

    @staticmethod
    def _story_image_schedule(
        image_count: int,
        story_duration: float,
        image_prompts_path: Path | None,
        alignment_path: Path | None,
    ) -> list[tuple[int, float]]:
        fallback = [(index, story_duration / image_count) for index in range(image_count)]
        if not image_prompts_path or not image_prompts_path.exists() or not alignment_path or not alignment_path.exists():
            logger.info("Keine Szenenanker vorhanden; verteile Storybilder gleichmaessig.")
            return fallback
        try:
            plan = json.loads(image_prompts_path.read_text(encoding="utf-8"))
            if not isinstance(plan, list) or len(plan) < image_count + 1 or not all(isinstance(item, dict) for item in plan):
                return fallback
            anchors = [str(item.get("start_text", "")).strip() for item in plan[1:image_count + 1]]
            alignment = json.loads(alignment_path.read_text(encoding="utf-8"))
            words = alignment_word_starts(alignment)
            if not words:
                return fallback

            starts = [0.0]
            search_from = 0
            for anchor in anchors[1:]:
                anchor_words = [normalize_match_word(word) for word in anchor.split()]
                anchor_words = [word for word in anchor_words if word]
                match_index = find_word_sequence(words, anchor_words, search_from)
                if match_index is None:
                    raise RuntimeError(
                        f"Szenenanker wurde nicht in der gesprochenen Story gefunden: {anchor!r}. "
                        "Bild-Timing wird nicht zufaellig verteilt."
                    )
                relative_start = words[match_index][1] / max(settings.voice_speed, 0.01)
                starts.append(min(story_duration, relative_start))
                search_from = match_index + len(anchor_words)

            if any(next_start - start < 0.25 for start, next_start in zip(starts, starts[1:])):
                raise RuntimeError("Szenenanker sind nicht streng chronologisch. Bild-Timing wird abgebrochen.")
            schedule = [
                (image_index, next_start - start)
                for image_index, (start, next_start) in enumerate(zip(starts, starts[1:]))
            ]
            schedule.append((len(starts) - 1, story_duration - starts[-1]))
            logger.info(
                "Alle Storybilder starten an ihren gesprochenen Szenenankern: %s",
                [(index + 2, round(start, 2)) for index, start in enumerate(starts)],
            )
            return schedule
        except RuntimeError:
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("Szenen-Timing konnte nicht geladen werden: %s", exc)
            return fallback

    def _ken_burns_clip(self, image_path: Path, duration: float, index: int) -> VideoClip:
        width, height = settings.video_width, settings.video_height
        base = ImageClip(str(image_path)).resize(height=height)
        if base.w < width:
            base = base.resize(width=width)
        direction = -1 if index % 2 else 1

        def position(t: float) -> tuple[float, float]:
            zoom = 1.0 + settings.ken_burns_zoom * (t / max(duration, 0.01))
            scaled_w = base.w * zoom
            scaled_h = base.h * zoom
            x_center_offset = (scaled_w - width) / 2
            y_center_offset = (scaled_h - height) / 2
            drift = direction * settings.ken_burns_drift * (t / max(duration, 0.01))
            return (-x_center_offset + drift, -y_center_offset)

        clip = base.resize(lambda t: 1.0 + settings.ken_burns_zoom * (t / max(duration, 0.01))).set_position(position)
        canvas = CompositeVideoClip([clip], size=(width, height)).set_duration(duration)
        return self._sanguine_flash(canvas, settings.transition_duration)

    def _cover_clip(self, image_path: Path, duration: float, metadata: StoryMetadata | None) -> VideoClip | None:
        if not image_path.exists():
            return None
        image = ImageClip(str(image_path)).resize(height=settings.video_height)
        if image.w < settings.video_width:
            image = image.resize(width=settings.video_width)
        image = image.set_duration(duration)

        def dark_mystery_frame(get_frame, t: float):
            progress = min(1.0, max(0.0, t / max(duration, 0.01)))
            frame = get_frame(t).astype(np.float32)
            gray = np.dot(frame[..., :3], [0.299, 0.587, 0.114])[..., None]
            desaturated = frame * (1.0 - 0.72 * progress) + gray * (0.72 * progress)
            return np.clip(desaturated * (1.0 - 0.32 * progress), 0, 255).astype("uint8")

        image = (
            image.fl(dark_mystery_frame)
            .resize(lambda t: 1.0 + 0.045 * min(1.0, t / max(duration, 0.01)))
            .set_position("center")
        )
        episode = metadata.episode_number if metadata else 1
        city = metadata.city if metadata else "deutschen Städten"
        title = self._glow_text_clip(display_text(settings.cover_title_text), 0, duration, font_size=settings.cover_title_font_size, y=655)
        episode_clip = self._glow_text_clip(f"Folge {episode}: {city}", 0, duration, font_size=settings.cover_episode_font_size, y=1100)
        return CompositeVideoClip([image, title, episode_clip], size=(settings.video_width, settings.video_height)).set_duration(duration)

    def _series_overlay_clip(self, metadata: StoryMetadata | None, start: float, duration: float) -> VideoClip | None:
        if not metadata:
            return None
        text = f"Hood Storys\nFolge {metadata.episode_number}: {metadata.city}"
        image_path = self._render_series_overlay_png(text)
        return (
            ImageClip(str(image_path))
            .set_start(start)
            .set_duration(duration)
            .set_position((58, 118))
            .crossfadein(0.12)
            .crossfadeout(0.18)
        )

    def _outro_clip(self, duration: float) -> VideoClip:
        background_path = self._render_outro_background()
        background = ImageClip(str(background_path)).set_duration(duration)
        text_clip = self._glow_text_clip(
            display_text(settings.outro_text),
            0,
            duration,
            font_size=settings.outro_font_size,
            y=300,
        )

        def outro_scale(t: float) -> float:
            entrance = 1.0 - math.exp(-7.0 * max(0.0, t))
            pulse = 0.008 * math.sin(2.0 * math.pi * 1.15 * t)
            return 0.88 + 0.12 * entrance + pulse

        def outro_position(t: float) -> tuple[str, float]:
            kick = 10.0 * math.exp(-5.0 * max(0.0, t)) * math.sin(28.0 * t)
            return ("center", 300 + kick)

        text_clip = (
            text_clip.resize(outro_scale)
            .set_position(outro_position)
            .crossfadein(min(0.18, duration))
        )
        outro = CompositeVideoClip(
            [background, text_clip],
            size=(settings.video_width, settings.video_height),
        ).set_duration(duration)

        def multicolor_glitch(get_frame, t: float):
            frame = get_frame(t).astype(np.uint8)
            frame_number = int(t * settings.video_fps)
            rng = np.random.default_rng(frame_number)
            strength = 3 + int(5 * abs(math.sin(t * 13.0)))

            glitched = frame.copy()
            glitched[..., 0] = np.roll(frame[..., 0], strength, axis=1)
            glitched[..., 1] = frame[..., 1]
            glitched[..., 2] = np.roll(frame[..., 2], -strength, axis=1)

            if frame_number % 5 in {0, 1}:
                for _ in range(4):
                    band_height = int(rng.integers(8, 34))
                    y = int(rng.integers(0, max(1, settings.video_height - band_height)))
                    shift = int(rng.integers(-28, 29))
                    glitched[y:y + band_height] = np.roll(
                        glitched[y:y + band_height],
                        shift,
                        axis=1,
                    )

            scanline_offset = frame_number % 4
            glitched[scanline_offset::4, :, 1] = (
                glitched[scanline_offset::4, :, 1].astype(np.float32) * 0.82
            ).astype(np.uint8)
            return glitched

        outro = outro.fl(multicolor_glitch).set_duration(duration)
        return self._sanguine_flash(outro, settings.transition_duration)

    @staticmethod
    def _sanguine_flash(clip: VideoClip, duration: float) -> VideoClip:
        effect_duration = min(max(0.01, duration), clip.duration)

        def effect(get_frame, t: float):
            frame = get_frame(t).astype(np.float32)
            if t >= effect_duration:
                return frame.astype(np.uint8)
            progress = max(0.0, min(1.0, t / effect_duration))
            decay = (1.0 - progress) ** 1.7
            pulse = (0.55 + 0.45 * abs(math.sin(progress * math.pi * 3.0))) * decay
            white_flash = math.exp(-progress * 13.0)

            shifted = frame.copy()
            offset = max(1, int(round(12.0 * decay)))
            shifted[..., 0] = np.roll(frame[..., 0], offset, axis=1)
            shifted[..., 2] = np.roll(frame[..., 2], -offset, axis=1)
            shifted *= 1.0 - 0.22 * pulse
            shifted[..., 0] += 150.0 * pulse + 95.0 * white_flash
            shifted[..., 1] += 38.0 * white_flash
            shifted[..., 2] += 42.0 * white_flash
            return np.clip(shifted, 0, 255).astype(np.uint8)

        return clip.fl(effect).set_duration(clip.duration)

    def _build_subtitle_clips(self, subtitles_path: Path) -> list[VideoClip]:
        json_path = subtitles_path.with_suffix(".json")
        if not json_path.exists():
            logger.warning("Subtitle JSON not found: %s", json_path)
            return []
        segments = json.loads(json_path.read_text(encoding="utf-8"))
        clips = []
        for index, segment in enumerate(segments):
            start = float(segment["start"])
            end = float(segment["end"])
            if index + 1 < len(segments):
                end = min(end, float(segments[index + 1]["start"]))
            duration = end - start
            if duration <= 0:
                continue
            clips.append(
                self._text_overlay_clip(
                    segment["text"],
                    start,
                    duration,
                    font_size=settings.subtitle_font_size,
                    y=settings.video_height - settings.subtitle_y_from_bottom,
                )
            )
        return clips

    def _text_overlay_clip(self, text: str, start: float, duration: float, font_size: int, y: float) -> VideoClip:
        image_path = self._render_text_png(text, font_size)
        return ImageClip(str(image_path)).set_start(start).set_duration(duration).set_position(("center", int(y)))

    def _glow_text_clip(self, text: str, start: float, duration: float, font_size: int, y: float) -> VideoClip:
        image_path = self._render_glow_text_png(text, font_size)
        return ImageClip(str(image_path)).set_start(start).set_duration(duration).set_position(("center", int(y)))

    @staticmethod
    def _cover_duration(metadata: StoryMetadata | None) -> float:
        if metadata and metadata.cover_duration_seconds:
            return metadata.cover_duration_seconds
        return settings.cover_duration

    @staticmethod
    def _mix_background_music(audio: AudioFileClip) -> AudioFileClip | CompositeAudioClip:
        music_path = resolve_asset(settings.background_music)
        if not music_path.exists():
            return audio
        music = AudioFileClip(str(music_path)).volumex(settings.background_music_volume)
        if music.duration < audio.duration:
            music = music.fx(afx.audio_loop, duration=audio.duration)
        else:
            music = music.subclip(0, audio.duration)
        music = music.fx(afx.audio_fadeout, min(0.5, audio.duration))
        return CompositeAudioClip([audio, music]).set_duration(audio.duration)

    @staticmethod
    def _render_text_png(text: str, font_size: int) -> Path:
        cache_dir = ROOT_DIR / "output" / "_subtitle_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        filename = f"subtitle_{abs(hash((text, font_size))) % 10_000_000}.png"
        output_path = cache_dir / filename
        if output_path.exists():
            return output_path
        max_width = int(settings.video_width * 0.94)
        font = load_font(font_size)
        lines = wrap_text(text, font, max_width)
        line_height = int(font_size * 1.22)
        image_height = max(line_height, line_height * len(lines)) + 28
        image = Image.new("RGBA", (max_width + 40, image_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        y = 14
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font, stroke_width=5)
            x = (image.width - (bbox[2] - bbox[0])) / 2
            draw.text((x, y), line, font=font, fill="white", stroke_width=5, stroke_fill="black")
            y += line_height
        image.save(output_path)
        return output_path

    @staticmethod
    def _render_glow_text_png(text: str, font_size: int) -> Path:
        cache_dir = ROOT_DIR / "output" / "_subtitle_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        filename = f"glow_{abs(hash((text, font_size))) % 10_000_000}.png"
        output_path = cache_dir / filename
        if output_path.exists():
            return output_path
        max_width = int(settings.video_width * 0.90)
        font = load_font(font_size, bold=False)
        lines = text.splitlines()
        wrapped: list[str] = []
        for line in lines:
            wrapped.extend(wrap_text(line, font, max_width) if line.strip() else [""])
        line_height = int(font_size * 1.22)
        image_height = max(line_height, line_height * len(wrapped)) + 110
        image = Image.new("RGBA", (max_width + 110, image_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        y = 55
        for line in wrapped:
            if not line:
                y += line_height
                continue
            bbox = draw.textbbox((0, 0), line, font=font, stroke_width=0)
            x = (image.width - (bbox[2] - bbox[0])) / 2
            for glow_width, glow_alpha in ((16, 55), (9, 95), (4, 145)):
                draw.text((x, y), line, font=font, fill=(255, 242, 80, glow_alpha), stroke_width=glow_width, stroke_fill=(255, 232, 42, glow_alpha))
            draw.text((x, y), line, font=font, fill="white")
            y += line_height
        image.save(output_path)
        return output_path

    @staticmethod
    def _render_series_overlay_png(text: str) -> Path:
        cache_dir = ROOT_DIR / "output" / "_subtitle_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        filename = f"series_overlay_{abs(hash(text)) % 10_000_000}.png"
        output_path = cache_dir / filename
        if output_path.exists():
            return output_path
        font = load_font(38, bold=False)
        small_font = load_font(31, bold=False)
        lines = text.splitlines()
        image = Image.new("RGBA", (620, 132), (0, 0, 0, 0))
        panel = Image.new("RGBA", image.size, (0, 0, 0, 118))
        image.alpha_composite(panel)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((0, 0, image.width - 1, image.height - 1), radius=12, outline=(255, 242, 100, 105), width=2)
        draw.text((24, 18), lines[0], font=font, fill=(255, 255, 255, 235))
        draw.text((24, 70), lines[1], font=small_font, fill=(255, 242, 112, 230))
        image.save(output_path)
        return output_path

    @staticmethod
    def _render_outro_background() -> Path:
        cache_dir = ROOT_DIR / "output" / "_subtitle_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        output_path = cache_dir / "outro_black_background.png"
        if output_path.exists():
            return output_path
        image = Image.new("RGB", (settings.video_width, settings.video_height), (0, 0, 0))
        image.save(output_path)
        return output_path


def load_font(font_size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_candidates = []
    if bold:
        font_candidates.extend([
            ROOT_DIR / "assets" / "fonts" / "subtitle.ttf",
            Path("C:/Windows/Fonts/arialbd.ttf"),
            Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ])
    font_candidates.extend([
        ROOT_DIR / "assets" / "fonts" / "regular.ttf",
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ])
    for font_path in font_candidates:
        if font_path.exists():
            return ImageFont.truetype(str(font_path), font_size)
    logger.warning("Keine Untertitel-Schrift gefunden. Pillow Default-Font wird genutzt.")
    return ImageFont.load_default()


def wrap_text(text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    for word in words:
        candidate = f"{current} {word}".strip()
        width = measure.textbbox((0, 0), candidate, font=font, stroke_width=5)[2]
        if width <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:3] if len(lines) > 3 else lines


def resolve_asset(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT_DIR / path


def display_text(value: str) -> str:
    return value.replace("\\n", "\n")


def alignment_word_starts(alignment: dict) -> list[tuple[str, float]]:
    characters = alignment.get("characters", [])
    starts = alignment.get("character_start_times_seconds", [])
    if not characters or len(characters) != len(starts):
        return []
    words: list[tuple[str, float]] = []
    current: list[str] = []
    current_start: float | None = None
    for character, start in zip(characters, starts):
        character = str(character)
        if character.isspace():
            if current and current_start is not None:
                normalized = normalize_match_word("".join(current))
                if normalized:
                    words.append((normalized, current_start))
            current = []
            current_start = None
            continue
        if current_start is None:
            current_start = float(start)
        current.append(character)
    if current and current_start is not None:
        normalized = normalize_match_word("".join(current))
        if normalized:
            words.append((normalized, current_start))
    return words


def normalize_match_word(value: str) -> str:
    return re.sub(r"[^\wäöüß]", "", value.lower(), flags=re.UNICODE)


def find_word_sequence(
    words: list[tuple[str, float]],
    anchor_words: list[str],
    start_index: int,
) -> int | None:
    if not anchor_words:
        return None
    spoken_words = [word for word, _ in words]
    last_start = len(spoken_words) - len(anchor_words)
    for index in range(start_index, last_start + 1):
        if spoken_words[index:index + len(anchor_words)] == anchor_words:
            return index
    return None
