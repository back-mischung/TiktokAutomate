from __future__ import annotations

import subprocess
from pathlib import Path

import imageio_ffmpeg
from moviepy.editor import AudioFileClip, concatenate_audioclips


def tempo_adjust(input_path: Path, output_path: Path, factor: float) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(input_path),
            "-filter:a",
            atempo_filter(factor),
            "-vn",
            "-acodec",
            "libmp3lame",
            "-q:a",
            "2",
            str(output_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return output_path


def split_tempo_adjust(
    input_path: Path,
    output_path: Path,
    split_seconds: float,
    first_factor: float,
    second_factor: float,
) -> tuple[Path, float]:
    temp_dir = output_path.parent
    first_raw = temp_dir / f"{output_path.stem}_first_raw.mp3"
    second_raw = temp_dir / f"{output_path.stem}_second_raw.mp3"
    first_done = temp_dir / f"{output_path.stem}_first.mp3"
    second_done = temp_dir / f"{output_path.stem}_second.mp3"
    with AudioFileClip(str(input_path)) as clip:
        split_seconds = max(0.05, min(split_seconds, clip.duration - 0.05))
        clip.subclip(0, split_seconds).write_audiofile(str(first_raw), fps=44100, logger=None)
        clip.subclip(split_seconds).write_audiofile(str(second_raw), fps=44100, logger=None)
    tempo_adjust(first_raw, first_done, first_factor)
    tempo_adjust(second_raw, second_done, second_factor)
    with AudioFileClip(str(first_done)) as first, AudioFileClip(str(second_done)) as second:
        processed_first_duration = float(first.duration)
        combined = concatenate_audioclips([first, second])
        combined.write_audiofile(str(output_path), fps=44100, logger=None)
        combined.close()
    for path in (first_raw, second_raw, first_done, second_done):
        path.unlink(missing_ok=True)
    return output_path, processed_first_duration


def split_tempo_adjust_parts(
    input_path: Path,
    first_output_path: Path,
    second_output_path: Path,
    sound_start_seconds: float,
    split_seconds: float,
    first_factor: float,
    second_factor: float,
) -> tuple[Path, Path]:
    temp_dir = first_output_path.parent
    temp_dir.mkdir(parents=True, exist_ok=True)
    first_raw = temp_dir / f"{first_output_path.stem}_raw.mp3"
    second_raw = temp_dir / f"{second_output_path.stem}_raw.mp3"
    with AudioFileClip(str(input_path)) as clip:
        split_seconds = max(0.05, min(split_seconds, clip.duration - 0.05))
        sound_start_seconds = max(0.0, min(sound_start_seconds, split_seconds - 0.05))
        clip.subclip(sound_start_seconds, split_seconds).write_audiofile(str(first_raw), fps=44100, logger=None)
        clip.subclip(split_seconds).write_audiofile(str(second_raw), fps=44100, logger=None)
    tempo_adjust(first_raw, first_output_path, first_factor)
    tempo_adjust(second_raw, second_output_path, second_factor)
    first_raw.unlink(missing_ok=True)
    second_raw.unlink(missing_ok=True)
    return first_output_path, second_output_path


def atempo_filter(factor: float) -> str:
    if factor <= 0:
        raise ValueError("Tempo factor must be positive.")
    parts: list[float] = []
    remaining = factor
    while remaining > 2.0:
        parts.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        parts.append(0.5)
        remaining /= 0.5
    parts.append(remaining)
    return ",".join(f"atempo={part:.6f}" for part in parts)
