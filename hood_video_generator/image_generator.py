from __future__ import annotations

import base64
import logging
import time
from pathlib import Path

from openai import OpenAI
from PIL import Image

from config import require_env, settings
from usage_tracker import UsageTracker


logger = logging.getLogger(__name__)


class ImageGenerator:
    def __init__(self, usage_tracker: UsageTracker | None = None) -> None:
        self.client = OpenAI(api_key=require_env(settings.openai_api_key, "OPENAI_API_KEY"))
        self.usage_tracker = usage_tracker

    def generate_images(self, prompts: list[str], output_dir: Path) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        image_paths: list[Path] = []
        for index, prompt in enumerate(prompts, start=1):
            output_path = output_dir / f"image_{index:02d}.{self._extension()}"
            logger.info("Generating image %s/%s with model %s", index, len(prompts), settings.openai_image_model)
            self._generate_single_image(prompt, output_path)
            image_paths.append(output_path)
            time.sleep(1.5)
        return image_paths

    def _generate_single_image(self, prompt: str, output_path: Path) -> None:
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                params = {
                    "model": settings.openai_image_model,
                    "prompt": prompt,
                    "size": settings.image_size,
                    "n": 1,
                    "quality": settings.image_quality,
                }
                if settings.image_output_format in {"jpeg", "png", "webp"}:
                    params["output_format"] = settings.image_output_format
                if settings.image_output_format in {"jpeg", "webp"}:
                    params["output_compression"] = settings.image_output_compression
                response = self.client.images.generate(**params)
                if self.usage_tracker:
                    self.usage_tracker.add_openai_image(
                        settings.openai_image_model,
                        f"image_generation_{output_path.stem}",
                        {
                            "size": settings.image_size,
                            "quality": settings.image_quality,
                            "output_format": settings.image_output_format,
                            "output_compression": settings.image_output_compression,
                            "attempt": attempt,
                        },
                    )
                image_data = response.data[0]
                if getattr(image_data, "b64_json", None):
                    output_path.write_bytes(base64.b64decode(image_data.b64_json))
                elif getattr(image_data, "url", None):
                    self._download_image(image_data.url, output_path)
                else:
                    raise RuntimeError("OpenAI Image API hat weder b64_json noch URL geliefert.")
                self._compress_image(output_path)
                return
            except Exception as exc:
                last_error = exc
                logger.warning("Image generation attempt %s failed for %s: %s", attempt, output_path.name, exc)
                time.sleep(2 * attempt)
        raise RuntimeError(f"Bild konnte nach 3 Versuchen nicht erzeugt werden: {output_path}") from last_error

    @staticmethod
    def _download_image(url: str, output_path: Path) -> None:
        import requests

        response = requests.get(url, timeout=60)
        response.raise_for_status()
        output_path.write_bytes(response.content)

    @staticmethod
    def _extension() -> str:
        if settings.image_output_format == "jpeg":
            return "jpg"
        if settings.image_output_format in {"png", "webp"}:
            return settings.image_output_format
        return "png"

    @staticmethod
    def _compress_image(output_path: Path) -> None:
        if output_path.suffix.lower() not in {".jpg", ".jpeg", ".webp"}:
            return
        with Image.open(output_path) as image:
            image = image.convert("RGB")
            image.save(output_path, quality=settings.image_output_compression, optimize=True)
