# TikTok Video Uploader

Dieses Projekt lädt eine fertige lokale MP4-Datei über die offizielle TikTok Content Posting API als Inbox-/Draft-Upload hoch.

Es nutzt ausschließlich `video.upload` und nicht `video.publish`.

Das bedeutet: Das Video wird nicht automatisch öffentlich gepostet. Nach erfolgreichem Upload soll TikTok dem Nutzer eine Inbox-Benachrichtigung schicken. Der Nutzer öffnet diese Benachrichtigung in der TikTok-App, prüft das Video und postet es manuell.

Story, Bilder, Voiceover, MoviePy, Untertitel und Videogenerierung sind hier bewusst nicht enthalten. Diese Teile bleiben in separaten Modulen.

## Offizielle API-Idee

Der Upload besteht aus zwei Schritten:

1. Upload initialisieren:

```http
POST https://open.tiktokapis.com/v2/post/publish/inbox/video/init/
Authorization: Bearer <USER_ACCESS_TOKEN>
Content-Type: application/json; charset=UTF-8
```

2. MP4-Datei per `PUT` an die zurückgegebene `upload_url` senden.

Benötigter Scope:

```text
video.upload
```

Wichtig: Verwende nicht `/v2/post/publish/video/init/`, denn dieser Endpoint gehört zu `video.publish` und wäre für Direct Post.

## Projektstruktur

```text
tiktok_video_uploader/
├── README.md
├── requirements.txt
├── .env.example
├── main.py
├── config.py
├── oauth_manual.py
├── tiktok_client.py
├── video_validator.py
├── token_store.py
└── examples/
    └── upload_example.py
```

## TikTok Developer Account

1. Öffne das TikTok Developer Portal:
   `https://developers.tiktok.com/`
2. Erstelle oder nutze einen bestehenden Developer Account.
3. Erstelle eine App.
4. Aktiviere bzw. beantrage die Produkte/Scopes, die du brauchst.
5. Für dieses Projekt brauchst du den Scope `video.upload`.
6. Kopiere `Client key` und `Client secret` aus deiner App.

Eine TikTok Developer App ist die registrierte OAuth/API-Anwendung. Sie legt fest, welche Redirect URIs erlaubt sind und welche Scopes deine Anwendung anfragen darf.

## Redirect URI

Dieses Projekt startet keinen lokalen Callback-Server mehr und braucht kein ngrok.

Nutze stattdessen deine feste Vercel-Callback-URL:

```text
https://DEINE-VERCEL-DOMAIN/callback
```

Trage exakt diese Redirect URI in deiner TikTok Developer App unter Login Kit ein und setze exakt dieselbe URI in `.env`.

Wichtig: Die URI beim Login-Link und beim Token Exchange muss bytegenau gleich sein. Ein Unterschied wie `/callback` vs. `/callback/` verursacht `redirect_uri mismatch`.
## Installation

```bash
cd tiktok_video_uploader
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

macOS/Linux:

```bash
cd tiktok_video_uploader
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## .env Anlegen

Kopiere die Beispiel-Datei:

```bash
copy .env.example .env
```

macOS/Linux:

```bash
cp .env.example .env
```

Fülle dann deine Daten aus:

```env
TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=
TIKTOK_REDIRECT_URI=https://DEINE-VERCEL-DOMAIN/callback
TIKTOK_SCOPES=video.upload
TIKTOK_TOKEN_FILE=tokens.json
TIKTOK_CHUNK_SIZE_MB=10
```

Secrets werden nicht hardcodiert. `tokens.json` wird lokal gespeichert und ist in `.gitignore` eingetragen.

## OAuth Starten

```bash
python main.py auth
```

Das Skript erzeugt einen TikTok Login-Link mit deiner `TIKTOK_REDIRECT_URI` aus `.env` und oeffnet ihn im Browser.

Falls der Browser nicht automatisch geoeffnet werden soll:

```bash
python main.py auth --no-browser
```

Nach dem TikTok Login landest du auf deiner Vercel-Callback-Seite. Dort kopierst du den Authorization Code und fuegst ihn im Terminal ein, wenn diese Frage erscheint:

```text
Kopiere den Authorization Code von der Vercel-Callback-Seite hier hinein:
```

Danach tauscht das Skript den Code gegen Token und speichert lokal:

```text
access_token
refresh_token
expires_at
refresh_expires_at
open_id
scope
token_type
```

in:

```text
tokens.json
```
## Token Status Prüfen

```bash
python main.py status
```

Das zeigt, ob ein Token gespeichert ist, welche Open ID vorhanden ist, welche Scopes gespeichert wurden und wann Access Token und Refresh Token ablaufen.

Wenn der Access Token abgelaufen ist, refreshed `upload` ihn automatisch über den Refresh Token.

## Video Hochladen

```bash
python main.py upload --file ./output/video.mp4
```

Nach erfolgreichem Upload erscheint:

```text
Upload abgeschlossen. TikTok sollte eine Inbox-Benachrichtigung senden.
```

Das Video ist danach nicht öffentlich. Öffne TikTok auf dem Handy, gehe zur Inbox-Benachrichtigung und poste das Video manuell.

## Beispiel

```bash
python examples/upload_example.py ../hood_video_generator/output/2026-06-09_001/final_video.mp4
```

## Video Validator

Vor dem Upload prüft `video_validator.py`:

- Datei existiert
- Endung ist `.mp4`
- Datei ist nicht leer
- optional mit `ffprobe`, ob Video-Codec wahrscheinlich H.264 und Audio-Codec AAC ist

Wenn `ffprobe` nicht installiert ist, kommt nur eine Warnung. Der Upload bricht dadurch nicht ab.

## Chunk Upload

Der Upload nutzt `FILE_UPLOAD` und Chunks.

Standard:

```text
TIKTOK_CHUNK_SIZE_MB=10
```

TikTok erlaubt laut Media Transfer Guide Chunks ab 5 MB bis 64 MB. Kleine Dateien unter 5 MB werden als ein einzelner Chunk hochgeladen. Der letzte Chunk darf den Rest enthalten.

Das Skript setzt beim PUT-Upload:

```http
Content-Type: video/mp4
Content-Length: <chunk bytes>
Content-Range: bytes <start>-<end>/<total>
```

## Rate Limit

TikTok limitiert Init-Requests für den Upload ungefähr auf 6 Requests pro Minute pro User Access Token.

Wenn du viele Uploads testest, warte zwischen Uploads. Der Datei-Upload an `upload_url` ist ein separater Schritt nach dem Init.

## Typische Fehler

`scope_not_authorized`:
Dein Access Token enthält nicht `video.upload`. Prüfe die App-Freigabe im Developer Portal, setze `TIKTOK_SCOPES=video.upload` und starte `python main.py auth` neu.

`access_token_invalid`:
Der Token ist abgelaufen, widerrufen oder falsch gespeichert. Versuche `python main.py auth` erneut. Wenn nur der Access Token abgelaufen ist, refreshed das Skript automatisch.

`rate_limit_exceeded`:
Zu viele Upload-Init-Requests in kurzer Zeit. Warte mindestens eine Minute.

`video format invalid`:
Prüfe MP4-Container, H.264 Video und AAC Audio. Erzeuge dein Video z. B. mit FFmpeg/MoviePy als `libx264` plus `aac`.

`redirect_uri mismatch`:
Die Redirect URI in `.env` stimmt nicht exakt mit der URI in der TikTok Developer App überein.

`code_verifier` oder OAuth-Fehler:
Dieses Projekt nutzt PKCE (`code_challenge`, `code_verifier`). Falls TikTok für deine konkrete App-Konfiguration andere Parameter erwartet, prüfe die aktuellen TikTok Login Kit Docs. Die Stelle ist im Code mit `# TODO: verify with current TikTok docs` markiert.

## Sicherheit

- Keine Secrets im Code speichern.
- `.env` und `tokens.json` nicht committen.
- `client_secret` niemals im Frontend verwenden.
- Keine inoffiziellen TikTok-Scraper.
- Kein Selenium.
- Keine Browser-Automation.
- Nur offizielle TikTok API.

## Spätere Verbindung Mit Dem Video-Generator

Ein separates Video-Generator-Modul kann später einfach diese Datei übergeben:

```text
../hood_video_generator/output/<run_id>/final_video.mp4
```

Dann:

```bash
python main.py upload --file ../hood_video_generator/output/<run_id>/final_video.mp4
```

## Kurzanleitung Nach PC-Neustart

Die konkrete Schritt-fuer-Schritt-Anleitung fuer den Alltag steht in:

```text
START_HIER_NACH_PC_START.md
```

## Vercel Callback URL Finden

Deine feste Callback URL hat dieses Format:

```text
https://DEINE-VERCEL-DOMAIN/callback
```

Du findest die Domain entweder im Vercel Dashboard unter:

```text
Project -> Deployments / Domains
```

oder im Terminal mit:

```bash
vercel ls
```

Die Vercel-Seite `/callback` muss den Query-Parameter `code` aus der URL anzeigen, damit du ihn kopieren kannst.

Beispiel nach TikTok Login:

```text
https://deine-domain.vercel.app/callback?code=AUTHORIZATION_CODE&state=...
```

Kopiere nur den Wert von `code`, nicht die ganze URL.
