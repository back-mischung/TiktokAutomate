from __future__ import annotations

import json
import logging
import re
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
    image_type: str = "story_scene"
    scene_purpose: str = ""
    location: str = ""
    characters_shown: str = ""
    camera_perspective: str = ""
    visual_mood: str = ""
    key_object: str = ""
    spoiler_check_passed: bool = True


class ImagePromptGenerator:
    def __init__(
        self,
        output_path: Path,
        scene_plan_path: Path | None = None,
        usage_tracker: UsageTracker | None = None,
    ) -> None:
        self.output_path = output_path
        self.scene_plan_path = scene_plan_path or output_path.with_name("image_scene_plan.json")
        self.system_prompt_path = ROOT_DIR / "prompts" / "image_prompt_system.txt"
        self.client = OpenAI(api_key=require_env(settings.openai_api_key, "OPENAI_API_KEY"))
        self.usage_tracker = usage_tracker

    def generate_image_prompts(self, story: str) -> list[ImagePromptSpec]:
        system_prompt = self.system_prompt_path.read_text(encoding="utf-8").strip()
        prompts: list[ImagePromptSpec] | None = None
        last_error: Exception | None = None
        last_output = ""
        for attempt in range(1, 6):
            retry_note = (
                ""
                if attempt == 1
                else (
                    "\n\nWICHTIGER RETRY: Die letzte Antwort war kein valides Format. "
                    f"Antworte diesmal NUR mit einer JSON-Liste mit exakt {settings.total_image_count} Objekten. "
                    "Kein Markdown, kein Text davor oder danach."
                )
            )
            response = self.client.responses.create(
                model=settings.openai_text_model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": story + retry_note},
                ],
            )
            if self.usage_tracker:
                self.usage_tracker.add_openai_response(response, settings.openai_text_model, "image_prompt_generation")
            last_output = response.output_text
            try:
                prompts = self._parse_prompt_list(last_output)
                break
            except (json.JSONDecodeError, RuntimeError) as exc:
                last_error = exc
                logger.info("Bildprompt-Ausgabe ungueltig (%s). Retry %s/5.", exc, attempt)
        if prompts is None:
            debug_path = self.output_path.with_suffix(".raw_response.txt")
            debug_path.parent.mkdir(parents=True, exist_ok=True)
            debug_path.write_text(last_output, encoding="utf-8")
            raise RuntimeError(
                f"Bildprompt-Erstellung nach 5 Versuchen fehlgeschlagen: {last_error}. "
                f"Letzte Rohantwort gespeichert unter {debug_path}"
            )
        self._warn_about_scene_plan(prompts, story)
        self.output_path.write_text(
            json.dumps(
                [{"prompt": prompt.prompt, "start_text": prompt.start_text} for prompt in prompts],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self.scene_plan_path.write_text(
            json.dumps([self._scene_plan_item(index, prompt) for index, prompt in enumerate(prompts, start=1)], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Saved %s image prompts to %s", len(prompts), self.output_path)
        logger.info("Saved image scene plan to %s", self.scene_plan_path)
        return prompts

    @staticmethod
    def _parse_prompt_list(raw_text: str) -> list[ImagePromptSpec]:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.removeprefix("json").strip()
        if not cleaned.startswith("["):
            match = re.search(r"\[[\s\S]*\]", cleaned)
            if match:
                cleaned = match.group(0)
        data = json.loads(cleaned)
        if not isinstance(data, list) or len(data) != settings.total_image_count:
            raise RuntimeError(
                f"Bildprompt-Ausgabe muss eine JSON-Liste mit genau {settings.total_image_count} Objekten sein."
            )
        prompts: list[ImagePromptSpec] = []
        for index, item in enumerate(data):
            if isinstance(item, str):
                prompts.append(ImagePromptSpec(prompt=item, image_type="story_scene"))
                continue
            if not isinstance(item, dict) or not isinstance(item.get("prompt"), str):
                raise RuntimeError(f"Ungueltiger Bildplan an Position {index + 1}.")
            start_text = item.get("start_text", "")
            if not isinstance(start_text, str):
                raise RuntimeError(f"start_text muss an Position {index + 1} ein String sein.")
            prompts.append(
                ImagePromptSpec(
                    prompt=item["prompt"].strip(),
                    start_text=start_text.strip(),
                    image_type=str(item.get("image_type", "story_scene")).strip(),
                    scene_purpose=str(item.get("scene_purpose", "")).strip(),
                    location=str(item.get("location", "")).strip(),
                    characters_shown=str(item.get("characters_shown", "")).strip(),
                    camera_perspective=str(item.get("camera_perspective", "")).strip(),
                    visual_mood=str(item.get("visual_mood", "")).strip(),
                    key_object=str(item.get("key_object", "")).strip(),
                    spoiler_check_passed=bool(item.get("spoiler_check_passed", True)),
                )
            )
        return prompts

    @staticmethod
    def _scene_plan_item(index: int, prompt: ImagePromptSpec) -> dict:
        return {
            "image_index": index,
            "image_type": "story_scene",
            "start_text": prompt.start_text,
            "scene_purpose": prompt.scene_purpose,
            "location": prompt.location,
            "characters_shown": prompt.characters_shown,
            "camera_perspective": prompt.camera_perspective,
            "visual_mood": prompt.visual_mood,
            "key_object": prompt.key_object,
            "spoiler_check_passed": prompt.spoiler_check_passed,
        }

    def _warn_about_scene_plan(self, prompts: list[ImagePromptSpec], story_input: str) -> None:
        story = self._story_text_only(story_input)
        story_prompts = prompts[1:]
        anchors = [prompt.start_text for prompt in story_prompts]
        seen: set[str] = set()
        for anchor in anchors:
            normalized = anchor.casefold()
            if not anchor:
                logger.warning("Bildplan-Warnung: start_text fehlt.")
                continue
            if normalized in seen:
                logger.warning("Bildplan-Warnung: doppelter start_text: %s", anchor)
            seen.add(normalized)
            count = story.count(anchor)
            if count != 1:
                logger.warning("Bildplan-Warnung: start_text kommt %s-mal in der Story vor: %s", count, anchor)
            if re.search(r"\b(Hood Storys|Folge)\b", anchor, re.IGNORECASE):
                logger.warning("Bildplan-Warnung: start_text zeigt auf Overlay/Titelzeile: %s", anchor)

        similar_street_count = 0
        previous_signature = ""
        for index, prompt in enumerate(story_prompts, start=2):
            full_text = " ".join(
                [
                    prompt.prompt,
                    prompt.location,
                    prompt.camera_perspective,
                    prompt.visual_mood,
                    prompt.scene_purpose,
                ]
            ).lower()
            signature = self._scene_signature(prompt)
            if signature == previous_signature:
                logger.warning("Bildplan-Warnung: Bild %s wirkt der vorherigen Szene sehr aehnlich.", index)
            previous_signature = signature
            if "dunkle stra" in full_text or "dark street" in full_text:
                similar_street_count += 1
            if re.search(r"\b(readable text|visible text|text on|sign says|license plate text|lesbarer text)\b", full_text):
                logger.warning("Bildplan-Warnung: Bild %s verlangt moeglicherweise lesbaren Text.", index)
            if re.search(r"\b(celebrity|real person|private person|famous|promi|echte person|minderjaehrig|minor|teen|child|kid)\b", full_text):
                logger.warning("Bildplan-Warnung: Bild %s koennte reale Personen oder Minderjaehrige darstellen.", index)
            if "fictional adult person" not in full_text and ("person" in full_text or "mann" in full_text or "frau" in full_text):
                logger.warning("Bildplan-Warnung: Bild %s mit Person enthaelt nicht eindeutig fictional adult person.", index)
            if not prompt.spoiler_check_passed:
                logger.warning("Bildplan-Warnung: Bild %s hat spoiler_check_passed=false.", index)

        if similar_street_count >= 3:
            logger.warning("Bildplan-Warnung: mehrere Szenen wirken wie Person auf dunkler Strasse.")
        if story_prompts and self._first_scene_may_spoil(story, story_prompts[0]):
            logger.warning("Bildplan-Warnung: erstes Storybild koennte spaetere Inhalte vorwegnehmen.")

    @staticmethod
    def _story_text_only(story_input: str) -> str:
        marker = "Gesprochene Story:"
        return story_input.split(marker, 1)[1].strip() if marker in story_input else story_input

    @staticmethod
    def _scene_signature(prompt: ImagePromptSpec) -> str:
        location = normalize_words(prompt.location)
        perspective = normalize_words(prompt.camera_perspective)
        mood = normalize_words(prompt.visual_mood)
        purpose = normalize_words(prompt.scene_purpose)
        return "|".join([location[:22], perspective[:18], mood[:18], purpose[:18]])

    @staticmethod
    def _first_scene_may_spoil(story: str, first_prompt: ImagePromptSpec) -> bool:
        first_sentence_match = re.search(r"^(.+?[.!?])(?:\s|$)", re.sub(r"\s+", " ", story.strip()))
        if not first_sentence_match:
            return False
        first_sentence = first_sentence_match.group(1).casefold()
        prompt_text = " ".join([first_prompt.prompt, first_prompt.key_object, first_prompt.characters_shown]).casefold()
        late_signal_words = ["polizei", "messer", "waffe", "blut", "verfolger", "stimme", "schatten", "kennzeichen", "anruf"]
        return any(word in prompt_text and word not in first_sentence for word in late_signal_words)


def normalize_words(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\wäöüß ]", "", value.lower(), flags=re.UNICODE)).strip()
