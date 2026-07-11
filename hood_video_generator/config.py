from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env", override=True)


class Settings(BaseSettings):
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_text_model: str = Field(default="gpt-5.4-mini", alias="OPENAI_TEXT_MODEL")
    openai_image_model: str = Field(default="gpt-image-2", alias="OPENAI_IMAGE_MODEL")
    elevenlabs_api_key: str = Field(default="", alias="ELEVENLABS_API_KEY")
    elevenlabs_voice_id: str = Field(default="", alias="ELEVENLABS_VOICE_ID")
    elevenlabs_model_id: str = Field(default="eleven_multilingual_v2", alias="ELEVENLABS_MODEL_ID")
    output_dir: Path = Field(default=Path("output"), alias="OUTPUT_DIR")
    video_width: int = Field(default=1080, alias="VIDEO_WIDTH")
    video_height: int = Field(default=1920, alias="VIDEO_HEIGHT")
    video_fps: int = Field(default=30, alias="VIDEO_FPS")
    image_size: str = Field(default="1024x1024", alias="IMAGE_SIZE")
    image_quality: str = Field(default="low", alias="IMAGE_QUALITY")
    image_output_format: str = Field(default="jpeg", alias="IMAGE_OUTPUT_FORMAT")
    image_output_compression: int = Field(default=75, alias="IMAGE_OUTPUT_COMPRESSION")
    total_image_count: int = Field(default=8, alias="TOTAL_IMAGE_COUNT")
    openai_text_input_usd_per_1m: float = Field(default=0.75, alias="OPENAI_TEXT_INPUT_USD_PER_1M")
    openai_text_output_usd_per_1m: float = Field(default=4.50, alias="OPENAI_TEXT_OUTPUT_USD_PER_1M")
    openai_image_estimated_usd_per_image: float = Field(default=0.011, alias="OPENAI_IMAGE_ESTIMATED_USD_PER_IMAGE")
    story_min_chars: int = Field(default=1050, alias="STORY_MIN_CHARS")
    story_target_chars: int = Field(default=1150, alias="STORY_TARGET_CHARS")
    story_max_chars: int = Field(default=1250, alias="STORY_MAX_CHARS")
    video_min_duration_seconds: float = Field(default=64.0, alias="VIDEO_MIN_DURATION_SECONDS")
    video_max_duration_seconds: float = Field(default=70.0, alias="VIDEO_MAX_DURATION_SECONDS")
    voice_speed: float = Field(default=1.3, alias="VOICE_SPEED")
    subtitle_font_size: int = Field(default=86, alias="SUBTITLE_FONT_SIZE")
    subtitle_y_from_bottom: int = Field(default=360, alias="SUBTITLE_Y_FROM_BOTTOM")
    subtitle_mode: str = Field(default="grouped_emphasis", alias="SUBTITLE_MODE")
    subtitle_min_words: int = Field(default=1, alias="SUBTITLE_MIN_WORDS")
    subtitle_max_words: int = Field(default=4, alias="SUBTITLE_MAX_WORDS")
    cover_enabled: bool = Field(default=True, alias="COVER_ENABLED")
    cover_duration: float = Field(default=1.5, alias="COVER_DURATION")
    cover_title_text: str = Field(default="Hood Storys aus\ndeutschen Städten", alias="COVER_TITLE_TEXT")
    outro_enabled: bool = Field(default=True, alias="OUTRO_ENABLED")
    outro_duration: float = Field(default=3.0, alias="OUTRO_DURATION")
    story_end_padding_seconds: float = Field(default=0.35, alias="STORY_END_PADDING_SECONDS")
    audio_boundary_fade_seconds: float = Field(default=0.04, alias="AUDIO_BOUNDARY_FADE_SECONDS")
    outro_text: str = Field(
        default="Folge für weitere\ndeutsche Hoodstorys\n\nWelche Stadt als\nnächstes ???\n\nSchreibt es\nin die\nKommentare !",
        alias="OUTRO_TEXT",
    )
    transition_duration: float = Field(default=0.7, alias="TRANSITION_DURATION")
    cover_transition_sound: str = Field(default="assets/sfx/cover_transition.mp3", alias="COVER_TRANSITION_SOUND")
    cover_transition_volume: float = Field(default=0.316, alias="COVER_TRANSITION_VOLUME")
    cover_transition_reload_volume: float = Field(default=0.45, alias="COVER_TRANSITION_RELOAD_VOLUME")
    cover_transition_split_seconds: float = Field(default=3.25, alias="COVER_TRANSITION_SPLIT_SECONDS")
    cover_transition_sound_start_seconds: float = Field(default=1.55, alias="COVER_TRANSITION_SOUND_START_SECONDS")
    cover_transition_first_speed: float = Field(default=2.5, alias="COVER_TRANSITION_FIRST_SPEED")
    cover_transition_second_speed: float = Field(default=0.65, alias="COVER_TRANSITION_SECOND_SPEED")
    cover_transition_sync_advance_seconds: float = Field(default=0.10, alias="COVER_TRANSITION_SYNC_ADVANCE_SECONDS")
    background_music: str = Field(default="assets/music/background.mp3", alias="BACKGROUND_MUSIC")
    background_music_volume: float = Field(default=0.032, alias="BACKGROUND_MUSIC_VOLUME")
    cover_title_font_size: int = Field(default=92, alias="COVER_TITLE_FONT_SIZE")
    cover_episode_font_size: int = Field(default=88, alias="COVER_EPISODE_FONT_SIZE")
    outro_font_size: int = Field(default=92, alias="OUTRO_FONT_SIZE")
    ken_burns_zoom: float = Field(default=0.06, alias="KEN_BURNS_ZOOM")
    ken_burns_drift: int = Field(default=24, alias="KEN_BURNS_DRIFT")

    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore", populate_by_name=True)

    @property
    def resolved_output_dir(self) -> Path:
        return self.output_dir if self.output_dir.is_absolute() else ROOT_DIR / self.output_dir


settings = Settings()


def configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def require_env(value: str, name: str) -> str:
    if not value:
        raise RuntimeError(f"{name} fehlt. Bitte in .env eintragen.")
    return value
