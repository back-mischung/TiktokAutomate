from __future__ import annotations

import argparse
import datetime as dt

from config import configure_logging, settings
from oauth_manual import run_manual_oauth
from tiktok_client import TikTokClient
from token_store import TokenStore


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="TikTok video.upload Inbox/Draft Uploader")
    subparsers = parser.add_subparsers(dest="command", required=True)

    auth_parser = subparsers.add_parser("auth", help="TikTok Login-Link erzeugen und Authorization Code manuell einfuegen")
    auth_parser.add_argument("--no-browser", action="store_true", help="Browser nicht automatisch öffnen")

    upload_parser = subparsers.add_parser("upload", help="MP4 als TikTok Inbox/Draft Upload hochladen")
    upload_parser.add_argument("--file", required=True, help="Pfad zur lokalen MP4-Datei")

    subparsers.add_parser("status", help="Gespeicherten Token-Status anzeigen")

    args = parser.parse_args()
    if args.command == "auth":
        run_manual_oauth(open_browser=not args.no_browser)
    elif args.command == "upload":
        result = TikTokClient().upload_video_to_inbox(args.file)
        publish_id = result.get("data", {}).get("publish_id")
        print("Upload abgeschlossen. TikTok sollte eine Inbox-Benachrichtigung senden.")
        if publish_id:
            print(f"publish_id: {publish_id}")
        print("Wichtig: Das Video wurde NICHT veröffentlicht. Bitte in der TikTok-App prüfen und manuell posten.")
    elif args.command == "status":
        print_token_status()


def print_token_status() -> None:
    store = TokenStore(settings.token_file)
    if not store.exists():
        print("Kein Token gespeichert. Starte zuerst: python main.py auth")
        return
    token = store.load()
    expires_at = dt.datetime.fromtimestamp(token.expires_at).astimezone()
    refresh_expires_at = (
        dt.datetime.fromtimestamp(token.refresh_expires_at).astimezone()
        if token.refresh_expires_at
        else None
    )
    print(f"Token-Datei: {settings.token_file}")
    print(f"Open ID: {token.open_id or '(nicht gespeichert)'}")
    print(f"Scope: {token.scope or '(nicht gespeichert)'}")
    print(f"Access Token läuft ab: {expires_at.isoformat()}")
    print(f"Access Token Status: {'abgelaufen/refresh nötig' if token.is_expired else 'gültig'}")
    if refresh_expires_at:
        print(f"Refresh Token läuft ab: {refresh_expires_at.isoformat()}")


if __name__ == "__main__":
    main()
