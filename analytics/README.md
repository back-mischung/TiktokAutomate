# Manuelle TikTok Analytics

Dieser Ordner ist nur fuer die Auswertung deiner manuell hochgeladenen TikTok-Videos da.
Es wird keine TikTok API genutzt, kein Scraping gemacht und kein Browser automatisiert.

## Ablauf nach einem neuen Video

1. Video wie gewohnt mit dem Generator erstellen.
2. Video manuell bei TikTok hochladen.
3. Caption aus dem jeweiligen Run-Ordner kopieren.
4. Run-Metadaten in die zentrale CSV importieren:

```powershell
python analytics/scripts/import_run_metadata.py
```

5. TikTok-Link und echte Zahlen manuell in `analytics/data/manual_metrics.csv` eintragen.

Nach 2 Stunden:

- `views_2h`

Nach 24 Stunden:

- `views_24h`
- `likes_24h`
- `comments_24h`
- `shares_24h`
- `saves_24h`
- `average_watch_time_seconds`
- `watched_full_video_percent`
- `profile_views`
- `new_followers`

Nach 7 Tagen:

- `views_7d`

6. Report erzeugen:

```powershell
python analytics/scripts/generate_report.py
```

7. Report lokal im Browser oeffnen:

```powershell
start analytics/reports/weekly_report.html
```

## Werte per Terminal eintragen

Du kannst einzelne Werte auch direkt per CLI setzen:

```powershell
python analytics/scripts/add_metrics.py --run_id "2026-07-11_001" --tiktok_url "https://www.tiktok.com/..." --views_24h 1200 --likes_24h 80 --comments_24h 12 --shares_24h 9
```

Das Script aktualisiert `analytics/data/manual_metrics.csv`.

## Was ausgewertet wird

Der Report vergleicht unter anderem:

- Hook-Kategorien
- Staedte und Bundeslaender
- Postingzeiten
- Videolaengen
- Untertitelvarianten
- Sounddesign-Versionen
- Storytypen
- Trend-Experimente

Dabei werden Kennzahlen wie Engagement Rate, Share Rate, Completion Rate, Follower Conversion und ein einfacher Performance Score berechnet.

## Wichtig

Die Empfehlungen sind am Anfang nur Tendenzen. Unter 10 Videos ist die Datenbasis sehr klein. Fuer stabilere Muster solltest du mindestens 30 Videos sammeln.
