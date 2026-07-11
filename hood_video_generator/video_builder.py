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
        visual_beats_path = metadata_path.parent / "visual_beats.json" if metadata_path else None
        clips = self._build_visual_clips(
            image_paths,
            audio.duration,
            metadata,
            image_prompts_path,
            alignment_path,
            visual_beats_path,
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
        visual_beats_path: Path | None = None,
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
        visual_beats = self._load_or_create_visual_beats(
            story_images,
            image_schedule,
            story_duration,
            image_prompts_path,
            visual_beats_path,
        )
        clips: list[VideoClip] = []
        for scene_index, (image_index, duration) in enumerate(image_schedule):
            scene_beats = [beat for beat in visual_beats if int(beat["scene_index"]) == scene_index]
            clip = self._render_scene_with_visual_beats(
                story_images[image_index],
                scene_beats,
                scene_duration=duration,
                scene_index=scene_index,
            )
            if scene_index == 0:
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

    def _load_or_create_visual_beats(
        self,
        story_images: list[Path],
        image_schedule: list[tuple[int, float]],
        story_duration: float,
        image_prompts_path: Path | None,
        visual_beats_path: Path | None,
    ) -> list[dict]:
        if visual_beats_path and visual_beats_path.exists():
            try:
                existing = json.loads(visual_beats_path.read_text(encoding="utf-8"))
                if self._visual_beats_match(existing, len(story_images), story_duration):
                    logger.info("Nutze vorhandenen visuellen Schnittplan: %s", visual_beats_path)
                    return existing
            except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                logger.warning("visual_beats.json konnte nicht wiederverwendet werden: %s", exc)

        prompt_plan = self._load_image_prompt_plan(image_prompts_path)
        beats = self._build_dynamic_shot_plan(story_images, image_schedule, prompt_plan)
        if visual_beats_path:
            visual_beats_path.write_text(json.dumps(beats, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("Visueller Schnittplan gespeichert: %s", visual_beats_path)
        return beats

    @staticmethod
    def _visual_beats_match(beats: list[dict], scene_count: int, story_duration: float) -> bool:
        if not isinstance(beats, list) or not beats:
            return False
        scene_indices = {int(beat.get("scene_index", -1)) for beat in beats}
        if scene_indices != set(range(scene_count)):
            return False
        max_end = max(float(beat.get("end_time", 0.0)) for beat in beats)
        return abs(max_end - story_duration) < 0.2

    @staticmethod
    def _load_image_prompt_plan(image_prompts_path: Path | None) -> list[dict]:
        if not image_prompts_path or not image_prompts_path.exists():
            return []
        try:
            plan = json.loads(image_prompts_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return plan if isinstance(plan, list) else []

    def _build_dynamic_shot_plan(
        self,
        story_images: list[Path],
        image_schedule: list[tuple[int, float]],
        prompt_plan: list[dict],
    ) -> list[dict]:
        beats: list[dict] = []
        scene_start = 0.0
        for scene_index, (image_index, scene_duration) in enumerate(image_schedule):
            prompt_item = prompt_plan[image_index + 1] if len(prompt_plan) > image_index + 1 else {}
            scene_text = " ".join(
                [
                    str(prompt_item.get("start_text", "")) if isinstance(prompt_item, dict) else "",
                    str(prompt_item.get("prompt", "")) if isinstance(prompt_item, dict) else "",
                ]
            )
            intense = contains_signal_word(scene_text)
            scene_beats = self.create_visual_beats_for_scene(
                scene_index=scene_index,
                source_image=story_images[image_index],
                scene_start=scene_start,
                scene_duration=scene_duration,
                intense=intense,
            )
            beats.extend(scene_beats)
            scene_start += scene_duration
        return beats

    @staticmethod
    def create_visual_beats_for_scene(
        scene_index: int,
        source_image: Path,
        scene_start: float,
        scene_duration: float,
        intense: bool,
    ) -> list[dict]:
        if scene_duration < 2.8:
            beat_count = 1
        elif scene_duration < 5.8:
            beat_count = 2
        else:
            beat_count = 3

        effect_cycle = [
            ("establishing", "in", "center", 1.00, 1.045),
            ("push_in", "in", "right", 1.055, 1.115),
            ("tight_pan", "out", "left", 1.115, 1.075),
        ]
        if intense and beat_count >= 2:
            effect_cycle[1] = ("shock_push", "in", "up", 1.065, 1.155)

        beats: list[dict] = []
        elapsed = 0.0
        for beat_index in range(beat_count):
            remaining = scene_duration - elapsed
            beat_duration = remaining if beat_index == beat_count - 1 else scene_duration / beat_count
            start = scene_start + elapsed
            end = scene_start + elapsed + beat_duration
            effect_type, zoom_direction, pan_direction, zoom_start, zoom_end = effect_cycle[beat_index]
            intensity = "strong" if intense and beat_index == 1 else "medium" if beat_index else "subtle"
            beats.append(
                {
                    "scene_index": scene_index,
                    "source_image": str(source_image),
                    "start_time": round(start, 3),
                    "end_time": round(end, 3),
                    "effect_type": effect_type,
                    "crop_start": safe_crop_for(pan_direction, zoom_start),
                    "crop_end": safe_crop_for(pan_direction, zoom_end),
                    "zoom_start": zoom_start,
                    "zoom_end": zoom_end,
                    "pan_direction": pan_direction,
                    "intensity": intensity,
                }
            )
            elapsed += beat_duration
        return beats

    def _render_scene_with_visual_beats(
        self,
        image_path: Path,
        beats: list[dict],
        scene_duration: float,
        scene_index: int,
    ) -> VideoClip:
        if not beats:
            return self._ken_burns_clip(image_path, scene_duration, scene_index)
        scene_start = min(float(beat["start_time"]) for beat in beats)
        subclips: list[VideoClip] = []
        for local_index, beat in enumerate(beats):
            duration = max(0.05, float(beat["end_time"]) - float(beat["start_time"]))
            relative_start = float(beat["start_time"]) - scene_start
            subclip = self.apply_ken_burns_effect(
                image_path=image_path,
                duration=duration,
                beat=beat,
                local_index=local_index,
            )
            if relative_start > 0.01:
                subclip = subclip.set_start(relative_start)
            subclips.append(subclip)
        scene = concatenate_videoclips(subclips, method="compose", padding=0).set_duration(scene_duration)
        if scene_index > 0 or any(beat.get("intensity") == "strong" for beat in beats):
            scene = self._sanguine_flash(scene, settings.transition_duration)
        return scene

    def apply_ken_burns_effect(self, image_path: Path, duration: float, beat: dict, local_index: int) -> VideoClip:
        width, height = settings.video_width, settings.video_height
        base = ImageClip(str(image_path)).resize(height=height)
        if base.w < width:
            base = base.resize(width=width)
        zoom_start = float(beat.get("zoom_start", 1.0))
        zoom_end = float(beat.get("zoom_end", 1.06))
        pan_direction = str(beat.get("pan_direction", "center"))
        effect_type = str(beat.get("effect_type", "push_in"))
        intensity = str(beat.get("intensity", "subtle"))

        def position(t: float) -> tuple[float, float]:
            progress = min(1.0, max(0.0, t / max(duration, 0.01)))
            zoom = zoom_start + (zoom_end - zoom_start) * smoothstep(progress)
            scaled_w = base.w * zoom
            scaled_h = base.h * zoom
            safe_x = (scaled_w - width) / 2
            safe_y = (scaled_h - height) / 2
            pan_x, pan_y = pan_offsets(pan_direction, safe_x, safe_y, progress)
            if effect_type == "shock_push" and intensity == "strong":
                shake = math.sin(t * 42.0) * max(0.0, 1.0 - progress) * 5.0
                pan_x += shake
            return (-safe_x + pan_x, -safe_y + pan_y)

        clip = base.resize(
            lambda t: zoom_start + (zoom_end - zoom_start) * smoothstep(min(1.0, max(0.0, t / max(duration, 0.01))))
        ).set_position(position)
        canvas = CompositeVideoClip([clip], size=(width, height)).set_duration(duration)
        if effect_type == "shock_push":
            canvas = self._shock_impulse(canvas, duration)
        return canvas

    @staticmethod
    def _shock_impulse(clip: VideoClip, duration: float) -> VideoClip:
        effect_duration = min(0.35, duration)

        def effect(get_frame, t: float):
            frame = get_frame(t).astype(np.float32)
            if t > effect_duration:
                return frame.astype(np.uint8)
            progress = t / max(effect_duration, 0.01)
            pulse = math.sin(progress * math.pi) * 0.18
            frame *= 1.0 + pulse
            frame[..., 0] += 28.0 * pulse
            return np.clip(frame, 0, 255).astype(np.uint8)

        return clip.fl(effect).set_duration(duration)

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
            is_emphasis = bool(segment.get("is_emphasis", False))
            clips.append(
                self._emphasis_text_overlay_clip(
                    segment["text"],
                    start,
                    duration,
                    font_size=settings.subtitle_font_size + 10,
                    y=settings.video_height - settings.subtitle_y_from_bottom,
                )
                if is_emphasis
                else self._text_overlay_clip(
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

    def _emphasis_text_overlay_clip(self, text: str, start: float, duration: float, font_size: int, y: float) -> VideoClip:
        image_path = self._render_text_png(text, font_size, emphasis=True)
        clip = ImageClip(str(image_path)).set_start(start).set_duration(duration)

        def scale(t: float) -> float:
            progress = min(1.0, max(0.0, t / max(duration, 0.01)))
            return 1.0 + 0.075 * math.exp(-7.0 * progress) * math.sin(progress * math.pi)

        def position(t: float) -> tuple[str, float]:
            progress = min(1.0, max(0.0, t / max(duration, 0.01)))
            shake = 3.0 * math.exp(-8.0 * progress) * math.sin(42.0 * t)
            return ("center", int(y + shake))

        return clip.resize(scale).set_position(position)

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
    def _render_text_png(text: str, font_size: int, emphasis: bool = False) -> Path:
        cache_dir = ROOT_DIR / "output" / "_subtitle_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        filename = f"subtitle_{abs(hash((text, font_size, emphasis))) % 10_000_000}.png"
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
            if emphasis:
                for glow_width, alpha in ((13, 70), (7, 120)):
                    draw.text(
                        (x, y),
                        line,
                        font=font,
                        fill=(255, 235, 72, alpha),
                        stroke_width=glow_width,
                        stroke_fill=(255, 220, 42, alpha),
                    )
                draw.text((x, y), line, font=font, fill=(255, 255, 245), stroke_width=5, stroke_fill="black")
            else:
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


SIGNAL_WORDS = [
    "plötzlich",
    "ploetzlich",
    "auf einmal",
    "dann",
    "aber",
    "ich schwöre",
    "ich schwoere",
    "bruder",
    "digga",
    "nachricht",
    "anruf",
    "stimme",
    "schatten",
    "kennzeichen",
    "tür",
    "tuer",
    "polizei",
    "rannte",
    "stand da",
    "sah mich an",
]


def contains_signal_word(value: str) -> bool:
    normalized = value.lower()
    return any(signal in normalized for signal in SIGNAL_WORDS)


def smoothstep(progress: float) -> float:
    progress = max(0.0, min(1.0, progress))
    return progress * progress * (3.0 - 2.0 * progress)


def pan_offsets(direction: str, safe_x: float, safe_y: float, progress: float) -> tuple[float, float]:
    progress = smoothstep(progress)
    x_strength = min(34.0, safe_x * 0.42)
    y_strength = min(28.0, safe_y * 0.28)
    if direction == "left":
        return (x_strength * (1.0 - 2.0 * progress), 0.0)
    if direction == "right":
        return (-x_strength * (1.0 - 2.0 * progress), 0.0)
    if direction == "up":
        return (0.0, y_strength * (1.0 - 2.0 * progress))
    if direction == "down":
        return (0.0, -y_strength * (1.0 - 2.0 * progress))
    return (0.0, 0.0)


def safe_crop_for(direction: str, zoom: float) -> dict:
    margin_x = round(min(0.08, max(0.0, (zoom - 1.0) * 0.35)), 4)
    margin_top = round(min(0.07, max(0.0, (zoom - 1.0) * 0.28)), 4)
    margin_bottom = round(min(0.04, max(0.0, (zoom - 1.0) * 0.18)), 4)
    center_shift = {
        "left": -0.035,
        "right": 0.035,
        "up": -0.025,
        "down": 0.02,
    }.get(direction, 0.0)
    return {
        "x_min": round(0.5 - margin_x + (center_shift if direction in {"left", "right"} else 0.0), 4),
        "x_max": round(0.5 + margin_x + (center_shift if direction in {"left", "right"} else 0.0), 4),
        "y_min": round(0.5 - margin_top + (center_shift if direction in {"up", "down"} else 0.0), 4),
        "y_max": round(0.5 + margin_bottom + (center_shift if direction in {"up", "down"} else 0.0), 4),
    }


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
