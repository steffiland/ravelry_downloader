#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "requests",
#   "python-dotenv",
#   "playwright",
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

KOSTENPFLICHTIGE DOWNLOADS:
----------------------------
Deren URLs verlangen eine eingeloggte Browser-Session statt der REST-API-Keys.
Liefert ein Download-Versuch eine HTML-Login-Seite statt eines PDFs, öffnet
dieses Script automatisch einen sichtbaren Browser (Playwright) zum manuellen
Einloggen – siehe ravelry_common.ensure_browser_login(). Die Session wird
danach lokal zwischengespeichert (.ravelry_session.json), sodass spätere
Läufe nicht erneut einloggen müssen.
"""

import os
import time

from ravelry_common import (
    api_get,
    download_with_login_fallback,
    get_current_username,
    sanitize_filename,
)

BASE_URL     = "https://api.ravelry.com"
DOWNLOAD_DIR = "ravelry_downloads"
IGNORE_FILE  = os.path.join(DOWNLOAD_DIR, "ignore.txt")

# Browser-Cookies werden lazy (erst bei Bedarf) geholt und dann für den
# restlichen Lauf wiederverwendet, damit nicht pro Datei neu eingeloggt wird.
browser_cookies: dict | None = None


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

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


def try_download(url: str, filename: str, label: str, ignore_patterns: list[str]) -> str:
    """
    Zentraler Download-Helper mit automatischem Browser-Login-Fallback.
    Gibt zurück: 'downloaded', 'skipped_exists', 'skipped_ignore', 'error'
    """
    global browser_cookies

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
    ok, msg, browser_cookies = download_with_login_fallback(url, target_path, browser_cookies)
    if ok:
        time.sleep(0.3)
        return "downloaded"
    else:
        print(f"  ❌ Fehler: {msg}")
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
        data = api_get(
            f"/people/{username}/library/search.json",
            {"page": page, "page_size": 100, "type": "pdf"},
        )
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

        try:
            vol_data = api_get(f"/volumes/{vol_id}.json").get("volume", {})
        except Exception as e:
            print(f"  ⚠️  Details konnten nicht geladen werden ({e})")
            continue

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
    Ruft alle Library-Einträge ab (ohne type-Filter), um daraus Einzelpattern
    herauszufiltern (patterns_count == 1, pattern_id gesetzt).
    """
    all_items = []
    page = 1
    print("🧶 Lade Bibliothek (einzelne Pattern) …")
    while True:
        data = api_get(
            f"/people/{username}/library/search.json",
            {"page": page, "page_size": 100},
        )
        batch = data.get("volumes", [])
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
    Holt die Download-URL für ein bereits gekauftes Einzelpattern.

    WICHTIG: pattern.download_location.url ist eine KAUF-/CHECKOUT-URL
    (zum Erwerben), KEINE Download-URL für bereits gekaufte Inhalte!
    Ist das Pattern schon in der Library (pdf_in_library=true), läuft der
    PDF-Download über das zugehörige Volume: volumes_in_library ->
    /volumes/{id}.json -> volume_attachments[].ravelry_download_url.

    Gibt (url, filename) zurück oder (None, None) wenn kein Download verfügbar.
    """
    try:
        pattern = api_get(f"/patterns/{pattern_id}.json").get("pattern", {})
    except Exception:
        return None, None

    if not pattern.get("ravelry_download") or not pattern.get("pdf_in_library"):
        return None, None

    volume_ids = pattern.get("volumes_in_library") or []
    if not volume_ids:
        return None, None

    try:
        vol_detail = api_get(f"/volumes/{volume_ids[0]}.json").get("volume", {})
    except Exception:
        return None, None

    attachments = vol_detail.get("volume_attachments", [])
    if not attachments:
        return None, None

    att = attachments[0]
    url = att.get("ravelry_download_url")
    if not url:
        return None, None

    name = pattern.get("name") or f"pattern_{pattern_id}"
    filename = att.get("filename") or sanitize_filename(name) + ".pdf"
    return url, filename


def process_individual_patterns(items: list, ignore_patterns: list[str]) -> dict:
    """
    Filtert aus den Library-Items Einzelpattern heraus (patterns_count == 1,
    pattern_id gesetzt) und lädt deren PDFs herunter. Volumes mit eigenen
    volume_attachments wurden bereits in process_volumes behandelt.
    """
    stats = {"downloaded": 0, "skipped_exists": 0, "skipped_ignore": 0, "error": 0}

    candidates = sorted({
        item["pattern_id"]
        for item in items
        if item.get("pattern_id") and item.get("patterns_count", 1) == 1
    })

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

    # --- Schritt 1: Volumes (eBooks, Collections) ---
    volumes = fetch_library_volumes(username)
    if volumes:
        stats = process_volumes(volumes, ignore_patterns)
        for k, v in stats.items():
            total_stats[k] += v
        print()

    # --- Schritt 2: Einzeln gekaufte Pattern ---
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
