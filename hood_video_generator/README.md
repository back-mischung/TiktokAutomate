# Hood Video Generator

Dieses Projekt erzeugt automatisch ein vertikales deutsches TikTok-Story-Video im Format 9:16.

Der Workflow:

1. Eine deutsche Hood-/Urban-Story wird aus `prompts/story_prompt.txt` generiert.
2. Aus der Story werden genau 10 Bildprompts erzeugt.
3. Mit der OpenAI Image API werden 10 Bilder generiert.
4. ElevenLabs erzeugt ein Voiceover als MP3.
5. Aus Story und Audiolänge werden einfache SRT- und JSON-Untertitel erzeugt.
6. MoviePy/FFmpeg baut daraus ein fertiges MP4-Video mit Ken-Burns-Bewegung, Crossfades, Intro, Outro und eingebrannten Untertiteln.

Das Projekt lädt nichts zu TikTok hoch. Dieses Projekt kann später mit dem separaten TikTok-video.upload-Modul verbunden werden. Dafür wird einfach `output/<run_id>/final_video.mp4` an den TikTok-Uploader übergeben.

## Installation

Voraussetzung: Python 3.11 oder neuer.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Auf macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## FFmpeg Installieren

MoviePy benötigt FFmpeg für Audio/Video-Export.

Windows:

```bash
winget install Gyan.FFmpeg
```

Danach ein neues Terminal öffnen und prüfen:

```bash
ffmpeg -version
```

macOS mit Homebrew:

```bash
brew install ffmpeg
ffmpeg -version
```

## API Keys

Kopiere `.env.example` nach `.env`:

```bash
copy .env.example .env
```

Auf macOS/Linux:

```bash
cp .env.example .env
```

Trage dann deine Keys ein:

```env
OPENAI_API_KEY=
OPENAI_TEXT_MODEL=gpt-4.1-mini
OPENAI_IMAGE_MODEL=gpt-image-1
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=
ELEVENLABS_MODEL_ID=eleven_multilingual_v2
OUTPUT_DIR=output
VIDEO_WIDTH=1080
VIDEO_HEIGHT=1920
VIDEO_FPS=30
```

`OPENAI_API_KEY` bekommst du im OpenAI Dashboard. `ELEVENLABS_API_KEY` und `ELEVENLABS_VOICE_ID` bekommst du in deinem ElevenLabs Account. Die Voice-ID muss zu einer Stimme gehören, die dein Account nutzen darf.

Hinweis: Modellnamen und unterstützte Bildgrößen können sich ändern. In `config.py` und `image_generator.py` sind TODOs markiert, falls du `OPENAI_TEXT_MODEL`, `OPENAI_IMAGE_MODEL` oder die Bildgröße anpassen musst.

## Prompt Bearbeiten

Der Story-Prompt liegt in:

```text
prompts/story_prompt.txt
```

Du kannst ihn frei bearbeiten. Die Story wird trotzdem automatisch in den aktuellen Run-Ordner gespeichert.

Der Systemprompt für die 10 Bildprompts liegt in:

```text
prompts/image_prompt_system.txt
```

## Ersten Test Starten

Kompletter Ablauf:

```bash
python main.py generate
```

Nur Story erzeugen:

```bash
python main.py generate --story-only
```

Vorhandene Bilder im aktuellen neuen Run-Ordner nutzen:

```bash
python main.py generate --skip-images
```

Einen bestimmten vorhandenen Run nutzen:

```bash
python main.py generate --run-id 2026-06-09_001 --skip-images
```

Vorhandenes Voiceover nutzen:

```bash
python main.py generate --skip-voice
```

Nur Video aus einem bestehenden Run bauen:

```bash
python main.py build --run-id 2026-06-09_001
```

## Ausgabe

Jeder Lauf bekommt einen eigenen Ordner:

```text
output/
└── 2026-06-09_001/
    ├── story.txt
    ├── image_prompts.json
    ├── images/
    │   ├── image_01.png
    │   └── ...
    ├── audio/
    │   └── voiceover.mp3
    ├── subtitles/
    │   ├── subtitles.srt
    │   └── subtitles.json
    └── final_video.mp4
```

## Intro, Outro Und Schrift

Wenn `assets/intro/intro.png` existiert, wird es am Anfang 1,5 Sekunden gezeigt.

Wenn `assets/outro/outro.png` existiert, wird es am Ende 1,5 Sekunden gezeigt.

Für Untertitel kannst du optional eine Schrift hier ablegen:

```text
assets/fonts/subtitle.ttf
```

Wenn keine Schrift gefunden wird, nutzt Pillow eine Standardschrift. Auf Windows wird außerdem automatisch `arialbd.ttf` versucht.

## Typische Fehler

`OPENAI_API_KEY fehlt`:
Prüfe, ob `.env` existiert und der Key eingetragen ist.

`ELEVENLABS_API_KEY fehlt`:
Trage deinen ElevenLabs API Key in `.env` ein.

`Voice-ID wurde nicht gefunden`:
Prüfe, ob `ELEVENLABS_VOICE_ID` korrekt ist und dein Account Zugriff auf diese Stimme hat.

`FFmpeg nicht installiert`:
Installiere FFmpeg und öffne danach ein neues Terminal.

`MoviePy Exportfehler`:
Prüfe FFmpeg, freien Speicherplatz und ob das Audio korrekt erzeugt wurde.

`Bildgröße wird vom Modell nicht unterstützt`:
Passe `image_size` in `config.py` an. Für viele aktuelle Bildmodelle ist `1024x1536` die praktikable 9:16-nahe Größe.

`Untertitel-Schrift nicht gefunden`:
Lege eine `.ttf`-Datei als `assets/fonts/subtitle.ttf` ab oder nutze eine Systemschrift.

## Was Nicht Enthalten Ist

Dieses Projekt enthält keine TikTok-Automation, keinen Browser, kein Selenium, keine CapCut-Automation und keinen Upload. Der Fokus liegt nur auf der Video-Generierung.
