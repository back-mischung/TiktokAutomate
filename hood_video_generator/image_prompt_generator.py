from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from openai import OpenAI

from config import ROOT_DIR, require_env, settings
from usage_tracker import UsageTracker


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImagePromptSpec:
    prompt: str
    start_text: str = ""


class ImagePromptGenerator:
    def __init__(self, output_path: Path, usage_tracker: UsageTracker | None = None) -> None:
        self.output_path = output_path
        self.system_prompt_path = ROOT_DIR / "prompts" / "image_prompt_system.txt"
        self.client = OpenAI(api_key=require_env(settings.openai_api_key, "OPENAI_API_KEY"))
        self.usage_tracker = usage_tracker

    def generate_image_prompts(self, story: str) -> list[ImagePromptSpec]:
        system_prompt = self.system_prompt_path.read_text(encoding="utf-8").strip()
        response = self.client.responses.create(
            model=settings.openai_text_model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": story},
            ],
        )
        if self.usage_tracker:
            self.usage_tracker.add_openai_response(response, settings.openai_text_model, "image_prompt_generation")
        prompts = self._parse_prompt_list(response.output_text)
        self.output_path.write_text(
            json.dumps([asdict(prompt) for prompt in prompts], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Saved %s image prompts to %s", len(prompts), self.output_path)
        return prompts

    @staticmethod
    def _parse_prompt_list(raw_text: str) -> list[ImagePromptSpec]:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.removeprefix("json").strip()
        data = json.loads(cleaned)
        if not isinstance(data, list) or len(data) != settings.total_image_count:
            raise RuntimeError(
                f"Bildprompt-Ausgabe muss eine JSON-Liste mit genau {settings.total_image_count} Objekten sein."
            )
        prompts: list[ImagePromptSpec] = []
        for index, item in enumerate(data):
            if isinstance(item, str):
                prompts.append(ImagePromptSpec(prompt=item))
                continue
            if not isinstance(item, dict) or not isinstance(item.get("prompt"), str):
                raise RuntimeError(f"Ungueltiger Bildplan an Position {index + 1}.")
            start_text = item.get("start_text", "")
            if not isinstance(start_text, str):
                raise RuntimeError(f"start_text muss an Position {index + 1} ein String sein.")
            prompts.append(ImagePromptSpec(prompt=item["prompt"].strip(), start_text=start_text.strip()))
        return prompts
