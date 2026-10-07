#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "requests",
#   "python-dotenv",
# ]
# ///

import os
import re
import time
import requests
from dotenv import load_dotenv

# .env laden
load_dotenv()

ACCESS_KEY = os.getenv("RAVELRY_ACCESS_KEY")
PERSONAL_KEY = os.getenv("RAVELRY_PERSONAL_KEY")

if not ACCESS_KEY or not PERSONAL_KEY:
    raise ValueError("Fehler: RAVELRY_ACCESS_KEY oder RAVELRY_PERSONAL_KEY fehlt in der .env-Datei!")

BASE_URL = "https://api.ravelry.com"
AUTH = (ACCESS_KEY, PERSONAL_KEY)
DOWNLOAD_DIR = "ravelry_downloads"
IGNORE_FILE = os.path.join(DOWNLOAD_DIR, "ignore.txt")


def sanitize_filename(filename: str) -> str:
    """Bereinigt Dateinamen von ungültigen Zeichen."""
    return re.sub(r'[\\/*?:"<>|]', "_", filename)


def get_current_username() -> str:
    """Ermittelt den Benutzernamen des API-Inhabers."""
    response = requests.get(f"{BASE_URL}/current_user.json", auth=AUTH)
    response.raise_for_status()
    return response.json()["user"]["username"]


def load_ignore_patterns(ignore_filepath: str) -> list[str]:
    """Lädt Ignorier-Muster aus einer Textdatei.
    
    Erstellt eine Beispiel-Datei, falls noch keine existiert.
    """
    if not os.path.exists(ignore_filepath):
        # Beispielhafte ignore.txt anlegen
        os.makedirs(os.path.dirname(ignore_filepath), exist_ok=True)
        default_content = (
            "# Trage hier Dateinamen oder Namensbestandteile ein, die NICHT heruntergeladen werden sollen.\n"
            "# Zeilen mit '#' werden als Kommentar ignoriert.\n"
            "#\n"
            "# Beispiele für Sprach-Ausschlüsse:\n"
            "# _NL.pdf\n"
            "# _FR.pdf\n"
            "# _ES.pdf\n"
            "# _IT.pdf\n"
            "# _RU.pdf\n"
        )
        with open(ignore_filepath, "w", encoding="utf-8") as f:
            f.write(default_content)
        print(f"ℹ️ Neue Ignorier-Datei erstellt: '{ignore_filepath}'")
        return []

    patterns = []
    with open(ignore_filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # Kommentare und Leerzeilen ignorieren
            if line and not line.startswith("#"):
                patterns.append(line.lower())

    if patterns:
        print(f"ℹ️ {len(patterns)} Ignorier-Muster aus '{ignore_filepath}' geladen.")
    return patterns


def is_ignored(filename: str, ignore_patterns: list[str]) -> bool:
    """Prüft, ob ein Dateiname mit einem der Ignorier-Muster übereinstimmt."""
    filename_lower = filename.lower()
    for pattern in ignore_patterns:
        if pattern in filename_lower:
            return True
    return False


def fetch_library_volumes(username: str) -> list:
    """Ruft alle Einträge aus der Ravelry-Bibliothek ab, die digitale Inhalte enthalten."""
    volumes = []
    page = 1
    page_size = 50

    print("Lade Bibliotheksübersicht...")
    while True:
        url = f"{BASE_URL}/people/{username}/library/search.json"
        params = {
            "page": page,
            "page_size": page_size,
            "type": "pdf",
        }

        response = requests.get(url, auth=AUTH, params=params)
        response.raise_for_status()

        data = response.json()
        current_volumes = data.get("volumes", [])
        if not current_volumes:
            break

        volumes.extend(current_volumes)

        paginator = data.get("paginator", {})
        if page >= paginator.get("page_count", 1):
            break

        page += 1

    print(f"Insgesamt {len(volumes)} digitale Einträge in der Bibliothek gefunden.\n")
    return volumes


def download_pdf(download_url: str, target_path: str):
    """Lädt eine Datei per Stream herunter und prüft, ob es sich um ein gültiges PDF handelt."""
    # Hinweis: Bei den eigentlichen Download-URLs KEIN auth=AUTH mitgeben,
    # da es sich oft um direkte S3/CDN-Links mit eigener Signatur handelt.
    response = requests.get(download_url, stream=True)
    response.raise_for_status()

    # 1. Content-Type und erste Bytes prüfen
    content_type = response.headers.get("Content-Type", "")

    # Einen kleinen Puffer für den Header-Check lesen
    chunks = response.iter_content(chunk_size=8192)
    first_chunk = next(chunks, None)

    if not first_chunk:
        raise ValueError("Datei ist leer (0 Bytes).")

    # Prüfung auf PDF-Signature (Magische Bytes %PDF-) oder Content-Type
    if not first_chunk.startswith(b"%PDF-") and "application/pdf" not in content_type.lower():
        # Falls es eine HTML-Seite ist, den Inhalt anzeigen/protokollieren
        preview = first_chunk[:300].decode("utf-8", errors="ignore")
        raise ValueError(f"Antwort ist kein PDF! (Content-Type: {content_type}). Vorschau:\n{preview}")

    # File schreiben
    with open(target_path, "wb") as f:
        f.write(first_chunk)
        for chunk in chunks:
            if chunk:
                f.write(chunk)

def process_library_downloads(username: str, volumes: list):
    """Prüft Bibliotheks-Einträge auf volume_attachments und lädt PDFs herunter."""
    
    # Symlink-sichere Ordnerprüfung
    if os.path.islink(DOWNLOAD_DIR):
        real_target = os.path.realpath(DOWNLOAD_DIR)
        if not os.path.exists(real_target):
            raise FileNotFoundError(
                f"Fehler: Symlink '{DOWNLOAD_DIR}' zeigt auf nicht existierenden Ordner: '{real_target}'"
            )
    else:
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    # Ignorier-Muster laden
    ignore_patterns = load_ignore_patterns(IGNORE_FILE)

    downloaded_count = 0
    skipped_ignore_count = 0

    for index, vol_summary in enumerate(volumes, start=1):
        vol_id = vol_summary.get("id")
        title = vol_summary.get("title") or f"Volume_{vol_id}"
        print(f"[{index}/{len(volumes)}] Prüfe: {title}")

        vol_url = f"{BASE_URL}/volumes/{vol_id}.json"
        res = requests.get(vol_url, auth=AUTH)
        if res.status_code != 200:
            print(f"  ⚠️ Details konnten nicht geladen werden (HTTP {res.status_code})")
            continue

        vol_data = res.json().get("volume", {})
        attachments = vol_data.get("volume_attachments", [])

        if not attachments:
            continue

        for att in attachments:
            file_name = att.get("filename") or f"{sanitize_filename(title)}.pdf"
            clean_file_name = sanitize_filename(file_name)

            if not clean_file_name.lower().endswith(".pdf"):
                clean_file_name += ".pdf"

            # 1. Ignorier-Liste prüfen
            if is_ignored(clean_file_name, ignore_patterns):
                print(f"  🚫 Übersprungen (in ignore.txt gefiltert): {clean_file_name}")
                skipped_ignore_count += 1
                continue

            download_url = att.get("ravelry_download_url")
            if not download_url:
                continue

            target_path = os.path.join(DOWNLOAD_DIR, clean_file_name)

            # 2. Bereits existierende Dateien prüfen
            if os.path.exists(target_path):
                print(f"  ➜ Übersprungen (bereits vorhanden): {clean_file_name}")
                continue

            print(f"  ⬇️ Lade herunter: {clean_file_name} ...")
            try:
                download_pdf(download_url, target_path)
                downloaded_count += 1
                time.sleep(0.3)
            except Exception as e:
                print(f"  ❌ Fehler beim Download von {clean_file_name}: {e}")

    print(
        f"\nFertig! {downloaded_count} neue PDF(s) heruntergeladen "
        f"({skipped_ignore_count} Datei(en) per ignore.txt gefiltert)."
    )


if __name__ == "__main__":
    username = get_current_username()
    print(f"Eingeloggt als: {username}\n")

    volumes = fetch_library_volumes(username)
    process_library_downloads(username, volumes)
