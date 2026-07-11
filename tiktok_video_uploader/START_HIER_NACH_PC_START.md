# TikTok-Upload starten

Diese Anleitung ist nur dafuer da, ein fertiges MP4-Video mit diesem Projekt zu TikTok hochzuladen.

## 1. Redirect URI pruefen

In `tiktok_video_uploader/.env` muss deine feste Vercel-Callback-URL stehen:

```env
TIKTOK_REDIRECT_URI=https://DEINE-VERCEL-DOMAIN/callback
```

Dieselbe URL muss im TikTok Developer Portal unter Login Kit als Web Redirect URI eingetragen sein.

## 2. Terminal im Projekt oeffnen

```powershell
cd "C:\Users\kilia\Vs Code Projekte\TiktokAutomate\tiktok_video_uploader"
```

## 3. Virtuelle Umgebung aktivieren

```powershell
.\.venv\Scripts\activate
```

Danach sollte links im Terminal `(.venv)` stehen.

## 4. Token pruefen

```powershell
python main.py status
```

Wenn der Token gueltig ist, direkt weiter zu Schritt 6.

## 5. Falls Token fehlt oder abgelaufen ist

```powershell
python main.py auth
```

Die Anwendung oeffnet den TikTok Login-Link.

Nach dem TikTok Login landest du auf deiner Vercel-Callback-Seite.

Kopiere dort den Authorization Code und fuege ihn im Terminal ein.

Danach nochmal pruefen:

```powershell
python main.py status
```

## 6. Fertiges Video hochladen

Beispiel:

```powershell
python main.py upload --file "..\hood_video_generator\output\2026-06-09_004\final_video.mp4"
```

Fuer ein neues Video den Ordnernamen austauschen:

```powershell
python main.py upload --file "..\hood_video_generator\output\NEUER_RUN_ID\final_video.mp4"
```

Wenn im Terminal `Upload abgeschlossen` und eine `publish_id` steht, hat TikTok den Upload angenommen.
