from __future__ import annotations

import logging
import json
import re
from pathlib import Path

from openai import OpenAI

from config import ROOT_DIR, require_env, settings
from usage_tracker import UsageTracker


logger = logging.getLogger(__name__)


class StoryGenerator:
    def __init__(
        self,
        output_path: Path,
        episode_number: int | None = None,
        usage_tracker: UsageTracker | None = None,
        city: str | None = None,
    ) -> None:
        self.output_path = output_path
        self.episode_number = episode_number or self._derive_episode_number(output_path)
        self.prompt_path = ROOT_DIR / "prompts" / "story_prompt.txt"
        self.client = OpenAI(api_key=require_env(settings.openai_api_key, "OPENAI_API_KEY"))
        self.usage_tracker = usage_tracker
        self.city = city.strip() if city else None
        self.used_cities = self._used_cities(output_path)
        self.generated_city: str | None = None

    def generate_story(self) -> str:
        prompt = self.prompt_path.read_text(encoding="utf-8").strip()
        story = ""
        max_attempts = 5
        retry_reason = ""
        for attempt in range(1, max_attempts + 1):
            request_prompt = (
                self._first_attempt_prompt(prompt)
                if attempt == 1
                else self._correction_prompt(prompt, story, retry_reason, attempt)
            )
            generated_city, story = self._request_story(request_prompt)
            self.generated_city = generated_city
            char_count = len(story)
            problems: list[str] = []
            if char_count < settings.story_min_chars:
                problems.append(f"zu kurz: {char_count} Zeichen")
            elif char_count > settings.story_max_chars:
                problems.append(f"zu lang: {char_count} Zeichen")
            city_problem = self._city_problem(generated_city)
            if city_problem:
                problems.append(city_problem)
            if not problems:
                break
            retry_reason = "; ".join(problems)
            logger.info("Story ungueltig (%s). Text retry %s/%s.", retry_reason, attempt, max_attempts)
        final_problems: list[str] = []
        if len(story) < settings.story_min_chars or len(story) > settings.story_max_chars:
            final_problems.append(
                f"Story hat {len(story)} Zeichen; erlaubt sind {settings.story_min_chars} bis {settings.story_max_chars}"
            )
        city_problem = self._city_problem(self.generated_city or "")
        if city_problem:
            final_problems.append(city_problem)
        if final_problems:
            raise RuntimeError(
                f"Story nach {max_attempts} Versuchen ungueltig: {'; '.join(final_problems)}. "
                "Abbruch, damit keine Bild- oder Voice-Credits verschwendet werden."
            )
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(story, encoding="utf-8")
        logger.info("Story saved to %s", self.output_path)
        return story

    def _first_attempt_prompt(self, base_prompt: str) -> str:
        return (
            f"{base_prompt}\n\n"
            f"WICHTIGER LAENGENPUFFER: Ziele intern auf etwa {settings.story_target_chars} Zeichen, "
            f"damit die fertige Ausgabe sicher zwischen {settings.story_min_chars} und {settings.story_max_chars} Zeichen liegt."
        )

    def _correction_prompt(self, base_prompt: str, previous_story: str, reason: str, attempt: int) -> str:
        current_length = len(previous_story)
        if current_length > settings.story_max_chars:
            target = max(settings.story_min_chars, settings.story_target_chars - (attempt * 60))
            length_rule = (
                f"Die letzte Story hatte {current_length} Zeichen und war zu lang. "
                f"Schreibe diesmal deutlich kuerzer: Ziel {target} bis {target + 120} Zeichen, "
                f"aber niemals ueber {settings.story_max_chars} Zeichen."
            )
        elif current_length < settings.story_min_chars:
            length_rule = (
                f"Die letzte Story hatte {current_length} Zeichen und war zu kurz. "
                f"Schreibe diesmal laenger: Ziel {settings.story_target_chars} bis {settings.story_max_chars - 50} Zeichen."
            )
        else:
            length_rule = (
                f"Ziel: {settings.story_min_chars} bis {settings.story_target_chars} Zeichen, "
                f"maximal {settings.story_max_chars} Zeichen."
            )
        return (
            f"{base_prompt}\n\n"
            f"Die letzte Ausgabe ist unbrauchbar ({reason}).\n"
            "Schreibe eine komplett neue Story. Wiederhole weder Stadt noch Handlung der letzten Ausgabe.\n"
            f"{length_rule}\n"
            "Nutze nur 4 sehr kurze Absaetze nach der ersten Zeile.\n"
            "Maximal 12 Saetze nach der ersten Zeile. Keine langen Beschreibungen, keine Zusatzsaetze.\n"
            f"Die Folgennummer bleibt {self.episode_number}.\n"
            "Keine Erklaerung, nur die Story."
        )

    def _request_story(self, prompt: str) -> tuple[str, str]:
        response = self.client.responses.create(
            model=settings.openai_text_model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Du erzeugst ausschliesslich valides JSON ohne Markdown. "
                        "Die Zeichenlaenge der Story ist wichtiger als Stil. Ueberschreite nie das genannte Maximum."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        self._request_instructions(prompt)
                        + "\n\nGib exakt dieses JSON-Format zurueck:\n"
                        '{"city": "Stadtname", "story": "Reiner Storytext ohne Titelzeile"}\n'
                        "Die Story darf nicht mit Hood Storys, Folge oder dem Stadtnamen als Titel beginnen."
                    ),
                },
            ],
        )
        if self.usage_tracker:
            self.usage_tracker.add_openai_response(response, settings.openai_text_model, "story_generation")
        text = response.output_text.strip()
        if not text:
            raise RuntimeError("OpenAI hat keine Story zurueckgegeben.")
        try:
            data = json.loads(strip_json_fence(text))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"OpenAI hat kein valides Story-JSON zurueckgegeben: {exc}") from exc
        city = str(data.get("city", "")).strip()
        story = str(data.get("story", "")).strip()
        if not city or not story:
            raise RuntimeError("OpenAI Story-JSON muss city und story enthalten.")
        return city, remove_story_header(story)

    def _request_instructions(self, prompt: str) -> str:
        instructions = f"{prompt}\n\nFolgennummer: {self.episode_number}"
        if self.city:
            instructions += (
                f"\nStadt fuer diese eine Story zwingend: {self.city}. "
                "Nutze keine andere Stadt und schreibe sie auch in die Kopfzeile."
            )
        elif self.used_cities:
            instructions += (
                "\nBEREITS VERWENDETE STAEDTE - KEINE DAVON DARF ERNEUT VERWENDET WERDEN: "
                + ", ".join(sorted(self.used_cities, key=str.casefold))
                + ". Waehle zwingend eine andere deutsche Stadt."
            )
        return instructions

    def _city_problem(self, city: str) -> str | None:
        city = city.strip()
        if not city:
            return "Stadt fehlt in den Metadaten"
        if self.city and city.casefold() != self.city.casefold():
            return f"falsche Stadt: {city}; verlangt war {self.city}"
        if not self.city and city.casefold() in {used.casefold() for used in self.used_cities}:
            return f"Stadt bereits verwendet: {city}"
        return None

    @staticmethod
    def _extract_city(story: str) -> str | None:
        match = re.search(r"Folge\s+\d+\s*:\s*([^\r\n]+)", story, re.IGNORECASE)
        return match.group(1).strip() if match else None

    @classmethod
    def _used_cities(cls, output_path: Path) -> set[str]:
        output_dir = output_path.parent.parent
        cities: set[str] = set()
        for metadata_path in output_dir.glob("*/metadata.json"):
            if metadata_path.parent == output_path.parent:
                continue
            try:
                data = json.loads(metadata_path.read_text(encoding="utf-8"))
                city = str(data.get("city", "")).strip()
            except (OSError, json.JSONDecodeError):
                city = ""
            if city:
                cities.add(city)
        for story_path in output_dir.glob("*/story.txt"):
            if story_path == output_path:
                continue
            city = cls._extract_city(story_path.read_text(encoding="utf-8", errors="ignore"))
            if city:
                cities.add(city)
        return cities

    @staticmethod
    def _derive_episode_number(output_path: Path) -> int:
        output_dir = output_path.parent.parent
        highest = 0
        for metadata_path in output_dir.glob("*/metadata.json"):
            if metadata_path.parent == output_path.parent:
                continue
            try:
                data = json.loads(metadata_path.read_text(encoding="utf-8"))
                highest = max(highest, int(data.get("episode_number", 0)))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass
        for story_path in output_dir.glob("*/story.txt"):
            if story_path == output_path:
                continue
            match = re.search(r"Folge\s+(\d+)\s*:", story_path.read_text(encoding="utf-8", errors="ignore"))
            if match:
                highest = max(highest, int(match.group(1)))
        if highest:
            return highest + 1
        run_id = output_path.parent.name
        try:
            return int(run_id.rsplit("_", 1)[1])
        except (IndexError, ValueError):
            return 1


def strip_json_fence(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.removeprefix("json").strip()
    return cleaned


def remove_story_header(story: str) -> str:
    return re.sub(
        r"^\s*Hood Storys aus deutschen St(?:ä|ae|Ã¤|ÃƒÂ¤)dten\s+Folge\s+\d+\s*:\s*.+?(?:\r?\n)+",
        "",
        story,
        count=1,
        flags=re.IGNORECASE,
    ).strip()
