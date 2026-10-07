#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "requests",
#   "python-dotenv",
# ]
# ///

"""
Ravelry PDF Downloader
======================
Lädt alle PDFs aus der eigenen Ravelry-Bibliothek herunter:

  1. Volumes (Bücher, Magazine, Collections):
     → library/search.json?type=pdf → volumes[].volume_attachments[].ravelry_download_url

  2. Einzeln gekaufte Ravelry-Pattern:
     → library/search.json (ohne type) → patterns[].download_location[].url (type="ravelry")

Ausschlüsse via ravelry_downloads/ignore.txt (Zeilen = Substring-Filter gegen Dateinamen).
"""

import os
import re
import time
import requests
from dotenv import load_dotenv

# .env laden
load_dotenv()

ACCESS_KEY  = os.getenv("RAVELRY_ACCESS_KEY")
PERSONAL_KEY = os.getenv("RAVELRY_PERSONAL_KEY")

if not ACCESS_KEY or not PERSONAL_KEY:
    raise ValueError(
        "Fehler: RAVELRY_ACCESS_KEY oder RAVELRY_PERSONAL_KEY fehlt in der .env-Datei!"
    )

BASE_URL    = "https://api.ravelry.com"
AUTH        = (ACCESS_KEY, PERSONAL_KEY)
DOWNLOAD_DIR = "ravelry_downloads"
IGNORE_FILE  = os.path.join(DOWNLOAD_DIR, "ignore.txt")


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def sanitize_filename(filename: str) -> str:
    """Bereinigt Dateinamen von Zeichen, die Dateisysteme nicht mögen."""
    return re.sub(r'[\\/*?:"<>|]', "_", filename)


def get_current_username() -> str:
    """Ermittelt den Benutzernamen des API-Inhabers."""
    response = requests.get(f"{BASE_URL}/current_user.json", auth=AUTH)
    response.raise_for_status()
    return response.json()["user"]["username"]


def load_ignore_patterns(ignore_filepath: str) -> list[str]:
    """
    Lädt Ignorier-Muster aus einer Textdatei.
    Erstellt eine Beispiel-Datei, falls noch keine existiert.
    """
    if not os.path.exists(ignore_filepath):
        os.makedirs(os.path.dirname(ignore_filepath), exist_ok=True)
        default_content = (
            "# Trage hier Dateinamen oder Namensbestandteile ein, die NICHT\n"
            "# heruntergeladen werden sollen. Zeilen mit '#' = Kommentar.\n"
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
        print(f"ℹ️  Neue Ignorier-Datei erstellt: '{ignore_filepath}'")
        return []

    patterns = []
    with open(ignore_filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line.lower())

    if patterns:
        print(f"ℹ️  {len(patterns)} Ignorier-Muster aus '{ignore_filepath}' geladen.")
    return patterns


def is_ignored(filename: str, ignore_patterns: list[str]) -> bool:
    """Prüft, ob ein Dateiname mit einem der Ignorier-Muster übereinstimmt."""
    filename_lower = filename.lower()
    return any(p in filename_lower for p in ignore_patterns)


def ensure_download_dir():
    """Stellt sicher, dass das Download-Verzeichnis existiert (Symlink-sicher)."""
    if os.path.islink(DOWNLOAD_DIR):
        real_target = os.path.realpath(DOWNLOAD_DIR)
        if not os.path.exists(real_target):
            raise FileNotFoundError(
                f"Symlink '{DOWNLOAD_DIR}' zeigt auf nicht existierenden Ordner: '{real_target}'"
            )
    else:
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def download_pdf(download_url: str, target_path: str):
    """
    Lädt eine Datei per Stream herunter und prüft auf gültige PDF-Signatur.

    WICHTIG: Kein auth= mitgeben – die URL ist vorsigniert (S3/CDN).
    """
    response = requests.get(download_url, stream=True, timeout=60)
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "")
    chunks = response.iter_content(chunk_size=8192)
    first_chunk = next(chunks, None)

    if not first_chunk:
        raise ValueError("Datei ist leer (0 Bytes).")

    # PDF-Signatur oder Content-Type prüfen
    if not first_chunk.startswith(b"%PDF-") and "application/pdf" not in content_type.lower():
        preview = first_chunk[:300].decode("utf-8", errors="ignore")
        raise ValueError(
            f"Antwort ist kein PDF! (Content-Type: {content_type})\nVorschau:\n{preview}"
        )

    with open(target_path, "wb") as f:
        f.write(first_chunk)
        for chunk in chunks:
            if chunk:
                f.write(chunk)


def try_download(url: str, filename: str, label: str, ignore_patterns: list[str]) -> str:
    """
    Zentraler Download-Helper.
    Gibt zurück: 'downloaded', 'skipped_exists', 'skipped_ignore', 'error'
    """
    clean_name = sanitize_filename(filename)
    if not clean_name.lower().endswith(".pdf"):
        clean_name += ".pdf"

    if is_ignored(clean_name, ignore_patterns):
        print(f"  🚫 Gefiltert (ignore.txt): {clean_name}")
        return "skipped_ignore"

    target_path = os.path.join(DOWNLOAD_DIR, clean_name)
    if os.path.exists(target_path):
        print(f"  ➜  Bereits vorhanden: {clean_name}")
        return "skipped_exists"

    print(f"  ⬇️  Lade herunter ({label}): {clean_name}")
    try:
        download_pdf(url, target_path)
        time.sleep(0.3)
        return "downloaded"
    except Exception as e:
        print(f"  ❌ Fehler: {e}")
        return "error"


# ---------------------------------------------------------------------------
# 1. VOLUMES (Bücher, Magazine, Collections mit eigenem PDF-Anhang)
# ---------------------------------------------------------------------------

def fetch_library_volumes(username: str) -> list:
    """Ruft alle Volume-Einträge aus der Bibliothek ab (type=pdf)."""
    volumes = []
    page = 1
    print("📚 Lade Bibliothek (Volumes/Bücher) …")
    while True:
        res = requests.get(
            f"{BASE_URL}/people/{username}/library/search.json",
            auth=AUTH,
            params={"page": page, "page_size": 100, "type": "pdf"},
        )
        res.raise_for_status()
        data = res.json()
        batch = data.get("volumes", [])
        if not batch:
            break
        volumes.extend(batch)
        paginator = data.get("paginator", {})
        if page >= paginator.get("page_count", 1):
            break
        page += 1

    print(f"  → {len(volumes)} Volume(s) gefunden.\n")
    return volumes


def process_volumes(volumes: list, ignore_patterns: list[str]) -> dict:
    """Verarbeitet Volumes und lädt zugehörige PDFs herunter."""
    stats = {"downloaded": 0, "skipped_exists": 0, "skipped_ignore": 0, "error": 0}

    for idx, vol_summary in enumerate(volumes, start=1):
        vol_id = vol_summary.get("id")
        title  = vol_summary.get("title") or f"Volume_{vol_id}"
        print(f"[{idx}/{len(volumes)}] Volume: {title}")

        res = requests.get(f"{BASE_URL}/volumes/{vol_id}.json", auth=AUTH, timeout=30)
        if res.status_code != 200:
            print(f"  ⚠️  Details konnten nicht geladen werden (HTTP {res.status_code})")
            continue

        vol_data    = res.json().get("volume", {})
        attachments = vol_data.get("volume_attachments", [])

        if not attachments:
            print("  ℹ️  Keine PDF-Anhänge.")
            continue

        for att in attachments:
            filename     = att.get("filename") or f"{sanitize_filename(title)}.pdf"
            download_url = att.get("ravelry_download_url")
            if not download_url:
                continue
            result = try_download(download_url, filename, "Volume", ignore_patterns)
            stats[result] = stats.get(result, 0) + 1

    return stats


# ---------------------------------------------------------------------------
# 2. EINZELN GEKAUFTE PATTERN (ravelry_download)
# ---------------------------------------------------------------------------

def fetch_library_patterns(username: str) -> list:
    """
    Ruft alle direkt auf Ravelry gekauften Pattern aus der Bibliothek ab.

    Hinweis: Die Ravelry-API gibt Library-Einträge in "volumes" zurück, auch
    wenn es sich um einzelne Pattern handelt. Es wird deshalb OHNE type-Filter
    abgerufen und dann nach download_location mit type="ravelry" gefiltert.
    """
    all_items = []
    page = 1
    print("🧶 Lade Bibliothek (einzelne Pattern) …")
    while True:
        res = requests.get(
            f"{BASE_URL}/people/{username}/library/search.json",
            auth=AUTH,
            params={"page": page, "page_size": 100},
        )
        res.raise_for_status()
        data = res.json()

        # Volumes UND Patterns (je nach API-Version in verschiedenen Keys)
        batch = data.get("volumes", []) + data.get("patterns", [])
        if not batch:
            break
        all_items.extend(batch)

        paginator = data.get("paginator", {})
        if page >= paginator.get("page_count", 1):
            break
        page += 1

    print(f"  → {len(all_items)} Gesamteinträge in der Bibliothek.\n")
    return all_items


def get_pattern_download_url(pattern_id: int) -> tuple[str | None, str | None]:
    """
    Holt die Ravelry-Download-URL für ein einzelnes Pattern.
    Gibt (url, filename) zurück oder (None, None) wenn kein Download verfügbar.
    """
    res = requests.get(
        f"{BASE_URL}/patterns/{pattern_id}.json",
        auth=AUTH,
        timeout=30,
    )
    if res.status_code != 200:
        return None, None

    pattern = res.json().get("pattern", {})

    # Nur Ravelry-Downloads (direkt auf Ravelry gekauft)
    if not pattern.get("ravelry_download"):
        return None, None

    download_location = pattern.get("download_location")
    if not download_location:
        return None, None

    # download_location kann eine Liste oder ein einzelnes Objekt sein
    if isinstance(download_location, dict):
        locations = [download_location]
    else:
        locations = download_location

    for loc in locations:
        if loc.get("type") == "ravelry" and loc.get("url"):
            name = pattern.get("name") or f"pattern_{pattern_id}"
            filename = sanitize_filename(name) + ".pdf"
            return loc["url"], filename

    # Fallback: irgendeine URL nehmen
    for loc in locations:
        if loc.get("url"):
            name = pattern.get("name") or f"pattern_{pattern_id}"
            filename = sanitize_filename(name) + ".pdf"
            return loc["url"], filename

    return None, None


def process_individual_patterns(items: list, ignore_patterns: list[str]) -> dict:
    """
    Filtert aus den Library-Items diejenigen heraus, die als Einzelpattern
    verfügbar sind (kein Volume-Attachment, aber ravelry_download).
    """
    stats = {"downloaded": 0, "skipped_exists": 0, "skipped_ignore": 0, "error": 0}
    candidates = []

    for item in items:
        # Volumes mit Attachments wurden bereits in process_volumes behandelt
        if item.get("volume_attachments"):
            continue

        # Pattern-ID herausfinden: entweder direkt oder via patterns-Array
        pattern_id = None

        # Manche Library-Items sind Pattern-Wrappers
        if item.get("ravelry_download"):
            pattern_id = item.get("id")
        elif item.get("patterns"):
            # Manche Volumes enthalten nur Pattern-Referenzen ohne eigenes PDF
            for p in item.get("patterns", []):
                if p.get("ravelry_download") and p.get("id"):
                    candidates.append(p["id"])
            continue
        elif item.get("id") and not item.get("volume_attachments"):
            # Unbekannter Typ – Pattern-Details prüfen
            pattern_id = item.get("id")

        if pattern_id:
            candidates.append(pattern_id)

    # Duplikate entfernen
    candidates = list(set(candidates))
    print(f"  → {len(candidates)} mögliche Einzel-Pattern zum Prüfen.\n")

    for idx, pid in enumerate(candidates, start=1):
        print(f"[{idx}/{len(candidates)}] Prüfe Pattern ID {pid} …")
        url, filename = get_pattern_download_url(pid)
        if not url:
            print("  ℹ️  Kein Ravelry-Download verfügbar.")
            continue
        result = try_download(url, filename, "Pattern", ignore_patterns)
        stats[result] = stats.get(result, 0) + 1

    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ensure_download_dir()
    ignore_patterns = load_ignore_patterns(IGNORE_FILE)
    username = get_current_username()
    print(f"👤 Eingeloggt als: {username}\n")

    total_stats = {"downloaded": 0, "skipped_exists": 0, "skipped_ignore": 0, "error": 0}

    # --- Schritt 1: Volumes ---
    volumes = fetch_library_volumes(username)
    if volumes:
        stats = process_volumes(volumes, ignore_patterns)
        for k, v in stats.items():
            total_stats[k] += v
        print()

    # --- Schritt 2: Einzeln gekaufte Pattern ---
    # Wir holen alle Library-Einträge ungefiltert und prüfen, was dabei ist.
    # (Volumes wurden in Schritt 1 schon behandelt.)
    all_items = fetch_library_patterns(username)
    if all_items:
        stats = process_individual_patterns(all_items, ignore_patterns)
        for k, v in stats.items():
            total_stats[k] += v

    # --- Zusammenfassung ---
    print("\n" + "=" * 50)
    print("✅ FERTIG")
    print(f"  ⬇️  Neu heruntergeladen : {total_stats['downloaded']}")
    print(f"  ➜   Bereits vorhanden  : {total_stats['skipped_exists']}")
    print(f"  🚫  Per ignore.txt gefiltert: {total_stats['skipped_ignore']}")
    print(f"  ❌  Fehler             : {total_stats['error']}")
    print("=" * 50)


if __name__ == "__main__":
    main()
