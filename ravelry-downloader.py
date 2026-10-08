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

  1. Volumes (Bücher, Magazine, Collections mit eigenem PDF-Bundle):
     → library/search.json?type=pdf → volumes[].volume_attachments[].ravelry_download_url

  2. Einzeln gekaufte Ravelry-Pattern:
     → library/search.json (ohne type) → Items mit pattern_id, patterns_count==1
       → /patterns/{id}.json → volumes_in_library → volume_attachments[].ravelry_download_url

  3. Referenz-Collections (patterns_count > 1, aber has_downloads=False):
     Das sind Collections OHNE eigenes gebündeltes PDF – die Mitglieder sind
     stattdessen einzeln verlinkte Pattern (meist kostenlose Ravelry-Downloads,
     z.B. Scheepjes "YARN - The After Party"). Diese werden über
     /pattern_sources/{id}/patterns.json aufgelistet und einzeln geladen.

STEUERUNG ÜBER ZWEI GETRENNTE DATEIEN (unterschiedliche Logik!):

  ravelry_downloads/ignore.txt – EXCLUDE-Logik, gilt für ALLE Downloads
    Eine Zeile = Substring-Filter gegen den Ziel-DATEINAMEN. Alles wird
    geladen, AUSSER was hier als Zeile steht (z.B. '_NL.pdf' für
    niederländische Versionen). Gilt überall – auch für Dateien innerhalb
    einer per collections.txt aktivierten Referenz-Collection.

  ravelry_downloads/collections.txt – INCLUDE-Logik, nur für Variante 3
    Eine Zeile = 'collection:<id-oder-teiltitel>'. Nur AKTIVE (nicht
    auskommentierte) Zeilen schalten den Download dieser Collection frei:
      collection:213142                 <- AKTIV, wird heruntergeladen
      #collection:213142                 <- INAKTIV (Standard für neue Funde)
    Zum Aktivieren einfach das führende '#' entfernen. Neu gefundene
    Collections werden bei jedem Lauf automatisch INAKTIV ergänzt, sodass
    hier immer eine vollständige, durchsuchbare Katalogliste ALLER jemals
    gefundenen Referenz-Collections zum Review entsteht – ohne dass
    versehentlich etwas heruntergeladen wird. Welche IDs schon einmal in
    den Katalog eingetragen wurden, merkt sich das Script in
    ravelry_downloads/.collection_sync.json, damit eine bereits bekannte
    Collection beim nächsten Lauf nicht erneut angehängt wird (unabhängig
    davon, ob du sie aktiviert oder deaktiviert gelassen hast).

VERARBEITUNGSREIHENFOLGE (main()):
  Schritt 1: Volumes mit eigenem PDF-Bundle (process_volumes)
  Schritt 2: Einzeln gekaufte Pattern (process_individual_patterns)
  Schritt 3: Referenz-Collections, deren Mitglieder einzeln (process_reference_collections)
  Schritt 4: Transparenz-Report für Items ohne Download-Pfad (report_unhandled_items)
  Schritt 5: Log der per ignore.txt gefilterten Einträge (write_excluded_log)
  Innerhalb jeder Stufe läuft es in der Reihenfolge, in der die Ravelry-API
  die Library-Einträge paginiert zurückgibt (keine eigene Sortierung durch
  dieses Script).

LOG-DATEIEN (werden bei JEDEM Lauf überschrieben, zeigen also den Stand
des letzten Laufs, nicht kumulativ über mehrere Läufe):
  - ravelry_downloads/skipped_non_downloadable.txt
    Library-Einträge ohne erkennbaren Download-Pfad (Schritt 4).
  - ravelry_downloads/excluded_by_ignore.txt
    Dateien/Collections, die in DIESEM Lauf per ignore.txt bzw.
    collections.txt NICHT heruntergeladen wurden (Schritt 5). Reines Log,
    kein Steuer-Mechanismus – zum Ändern selbst ignore.txt/collections.txt
    bearbeiten.

KOSTENPFLICHTIGE DOWNLOADS:
----------------------------
Deren URLs verlangen eine eingeloggte Browser-Session statt der REST-API-Keys.
Liefert ein Download-Versuch eine HTML-Login-Seite statt eines PDFs, öffnet
dieses Script automatisch einen sichtbaren Browser (Playwright) zum manuellen
Einloggen – siehe ravelry_common.ensure_browser_login(). Die Session wird
danach lokal zwischengespeichert (.ravelry_session.json), sodass spätere
Läufe nicht erneut einloggen müssen.
"""

import json
import os
import time

from ravelry_common import (
    api_get,
    download_with_login_fallback,
    fetch_file_variants,
    get_current_username,
    sanitize_filename,
)

BASE_URL             = "https://api.ravelry.com"
DOWNLOAD_DIR         = "ravelry_downloads"
IGNORE_FILE          = os.path.join(DOWNLOAD_DIR, "ignore.txt")
COLLECTIONS_FILE     = os.path.join(DOWNLOAD_DIR, "collections.txt")
COLLECTION_SYNC_FILE = os.path.join(DOWNLOAD_DIR, ".collection_sync.json")

# Log-Dateien (werden bei JEDEM Lauf überschrieben, zeigen also immer den
# Stand des letzten Laufs – kein Steuer-Mechanismus, nur Transparenz):
#   - SKIPPED_REPORT_FILE: Library-Einträge ohne erkennbaren Download-Pfad
#     (siehe report_unhandled_items())
#   - EXCLUDED_LOG_FILE:   Dateien/Collections, die in diesem Lauf NICHT
#     heruntergeladen wurden (per ignore.txt ODER collections.txt)
SKIPPED_REPORT_FILE = os.path.join(DOWNLOAD_DIR, "skipped_non_downloadable.txt")
EXCLUDED_LOG_FILE   = os.path.join(DOWNLOAD_DIR, "excluded_by_ignore.txt")

# Browser-Cookies werden lazy (erst bei Bedarf) geholt und dann für den
# restlichen Lauf wiederverwendet, damit nicht pro Datei neu eingeloggt wird.
browser_cookies: dict | None = None

# Sammelt alle in diesem Lauf nicht heruntergeladenen Dateinamen/Titel,
# wird am Ende von main() als EXCLUDED_LOG_FILE geschrieben (siehe
# write_excluded_log()). Modul-globaler Zustand analog zu browser_cookies.
excluded_this_run: list[str] = []


# ---------------------------------------------------------------------------
# ignore.txt – Dateinamen-Filter (EXCLUDE-Logik, gilt für ALLE Downloads)
# ---------------------------------------------------------------------------

def load_ignore_patterns(ignore_filepath: str) -> list[str]:
    """
    Lädt Dateinamen-Ignorier-Muster aus ignore.txt.
    Erstellt eine Beispiel-Datei, falls noch keine existiert.

    EXCLUDE-Logik: eine Zeile = Substring-Filter gegen den Ziel-DATEINAMEN.
    Alles wird geladen, AUSSER was hier als Zeile steht. Gilt für JEDEN
    Download (Volumes, Einzelpattern, UND Dateien innerhalb einer per
    collections.txt aktivierten Referenz-Collection).
    """
    if not os.path.exists(ignore_filepath):
        os.makedirs(os.path.dirname(ignore_filepath), exist_ok=True)
        default_content = (
            "# Trage hier Dateinamen oder Namensbestandteile ein, die NICHT\n"
            "# heruntergeladen werden sollen. Zeilen mit '#' = Kommentar.\n"
            "# Gilt für ALLE Downloads, auch innerhalb aktivierter Collections\n"
            "# (siehe collections.txt).\n"
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

    filename_patterns = []
    with open(ignore_filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Inline-Kommentare abschneiden
            line_without_comment = line.split("#", 1)[0].strip()
            if line_without_comment:
                filename_patterns.append(line_without_comment.lower())

    if filename_patterns:
        print(f"ℹ️  {len(filename_patterns)} Datei-Ignorier-Muster aus '{ignore_filepath}' geladen.")
    return filename_patterns


def is_ignored(filename: str, ignore_patterns: list[str]) -> bool:
    """Prüft, ob ein Dateiname mit einem der Ignorier-Muster übereinstimmt."""
    filename_lower = filename.lower()
    return any(p in filename_lower for p in ignore_patterns)


# ---------------------------------------------------------------------------
# collections.txt – Referenz-Collection-Freigabe (INCLUDE-Logik)
# ---------------------------------------------------------------------------

def load_collection_includes(collections_filepath: str) -> list[str]:
    """
    Lädt die Liste AKTIVER Collection-Freigaben aus collections.txt.
    Erstellt eine Beispiel-Datei, falls noch keine existiert.

    INCLUDE-Logik: Standard ist NICHT laden. Nur eine AKTIVE Zeile (ohne
    führendes '#') schaltet den Download dieser Collection frei:
      collection:213142                 <- AKTIV, wird heruntergeladen
      #collection:213142                 <- INAKTIV (Standard für neue Funde)
    <id-oder-teiltitel> = pattern_source_id ODER Teil des Titels.
    """
    if not os.path.exists(collections_filepath):
        os.makedirs(os.path.dirname(collections_filepath), exist_ok=True)
        default_content = (
            "# Referenz-Collections (patterns_count>1 ohne eigenes PDF-Bundle,\n"
            "# z.B. Scheepjes 'YARN - The After Party') werden hier als Katalog\n"
            "# gesammelt. Standard ist NICHT laden (INCLUDE-Logik) – nur eine\n"
            "# AKTIVE Zeile (ohne führendes '#') schaltet den Download frei:\n"
            "#\n"
            "#   collection:213142                 <- AKTIV, wird heruntergeladen\n"
            "#   #collection:213142                 <- inaktiv (Standard)\n"
            "#\n"
            "# Zum Aktivieren einfach das führende '#' vor der Zeile entfernen.\n"
            "# <wert> = pattern_source_id ODER Teil des Titels, z.B.:\n"
            "#   collection:Yarn - The After Party\n"
        )
        with open(collections_filepath, "w", encoding="utf-8") as f:
            f.write(default_content)
        print(f"ℹ️  Neue Collections-Datei erstellt: '{collections_filepath}'")
        return []

    collection_includes = []
    with open(collections_filepath, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue

            # Führendes '#' abstreifen, um AKTIV ('collection:...') von
            # INAKTIV ('#collection:...') zu unterscheiden. Zeilen, die NACH
            # dem Abstreifen nicht mit 'collection:' beginnen, sind reine
            # Kommentare.
            stripped_hash = line.lstrip("#").strip()
            if not stripped_hash.lower().startswith("collection:"):
                continue  # reiner Kommentar

            is_active = not line.startswith("#")
            if not is_active:
                continue

            # Inline-Kommentar abschneiden: 'collection:213142  # Titel'
            value = stripped_hash.split(":", 1)[1]
            value = value.split("#", 1)[0].strip().lower()
            if value:
                collection_includes.append(value)

    if collection_includes:
        print(f"ℹ️  {len(collection_includes)} aktive Collection-Freigabe(n) aus "
              f"'{collections_filepath}' geladen.")
    return collection_includes


def is_collection_included(collection_item: dict, collection_includes: list[str]) -> bool:
    """
    Prüft, ob eine Referenz-Collection per AKTIVER 'collection:<id-oder-titel>'-
    Zeile in collections.txt zum Download freigegeben wurde (INCLUDE-Logik:
    Standard ist NICHT laden, nur explizit aktivierte Collections werden
    geladen).
    """
    src_id = str(collection_item.get("pattern_source_id", "")).lower()
    title  = (collection_item.get("title") or "").lower()
    return any(incl == src_id or incl in title for incl in collection_includes)


def load_synced_collection_ids() -> set[int]:
    """Lädt die Menge der pattern_source_ids, die schon einmal in
    collections.txt automatisch eingetragen wurden (siehe
    sync_new_reference_collections)."""
    if not os.path.exists(COLLECTION_SYNC_FILE):
        return set()
    try:
        with open(COLLECTION_SYNC_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (json.JSONDecodeError, OSError):
        return set()


def save_synced_collection_ids(ids: set[int]) -> None:
    with open(COLLECTION_SYNC_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f, indent=2)


def sync_new_reference_collections(collections: list[dict]) -> None:
    """
    Trägt NEUE Referenz-Collections (die noch nie zuvor gesehen wurden)
    automatisch INAKTIV als '#collection:<id>  # <Titel> (<n> Pattern)' in
    collections.txt ein. So entsteht eine vollständige, durchsuchbare
    Katalogliste zum Review, ohne dass versehentlich etwas heruntergeladen
    wird. Zum Aktivieren einfach das führende '#' entfernen.

    Bereits einmal in den Katalog eingetragene IDs werden in
    COLLECTION_SYNC_FILE gemerkt, damit eine bekannte Collection beim
    nächsten Lauf nicht erneut angehängt wird – unabhängig davon, ob du sie
    inzwischen aktiviert oder deaktiviert gelassen hast.
    """
    already_synced = load_synced_collection_ids()
    new_ones = [
        c for c in collections
        if c.get("pattern_source_id") not in already_synced
    ]
    if not new_ones:
        return

    lines = [
        f"#collection:{c['pattern_source_id']}  "
        f"# {c.get('title', 'Unbenannt')} ({c.get('patterns_count', '?')} Pattern)"
        for c in new_ones
    ]
    header = (
        f"\n# --- Automatisch ergänzt am {time.strftime('%Y-%m-%d %H:%M')} "
        f"({len(new_ones)} neue Referenz-Collection(en)) ---\n"
        "# Standardmäßig INAKTIV. Führendes '#' entfernen = Collection WIRD "
        "heruntergeladen.\n"
    )
    with open(COLLECTIONS_FILE, "a", encoding="utf-8") as f:
        f.write(header + "\n".join(lines) + "\n")

    already_synced.update(c["pattern_source_id"] for c in new_ones)
    save_synced_collection_ids(already_synced)

    print(f"ℹ️  {len(new_ones)} neue Referenz-Collection(en) automatisch (inaktiv) in "
          f"'{COLLECTIONS_FILE}' eingetragen.")


# ---------------------------------------------------------------------------
# Allgemeine Hilfsfunktionen
# ---------------------------------------------------------------------------

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

    is_ignored() (ignore.txt) wird hier für JEDEN Download geprüft, auch für
    Dateien innerhalb einer per collections.txt aktivierten Referenz-
    Collection – die beiden Mechanismen sind unabhängig und wirken beide.
    """
    global browser_cookies

    clean_name = sanitize_filename(filename)
    if not clean_name.lower().endswith(".pdf"):
        clean_name += ".pdf"

    if is_ignored(clean_name, ignore_patterns):
        print(f"  🚫 Gefiltert (ignore.txt): {clean_name}")
        excluded_this_run.append(f"{clean_name}  (Datei-Filter, {label})")
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
# 3. REFERENZ-COLLECTIONS (patterns_count > 1, aber has_downloads=False)
# ---------------------------------------------------------------------------
#
# Manche Collections bündeln kein eigenes PDF, sondern verweisen nur auf
# mehrere einzeln verlinkte Pattern (häufig kostenlose Ravelry-Downloads,
# z.B. Yarn-Hersteller-Sammlungen wie Scheepjes "YARN - The After Party").
# Solche Collections werden per /pattern_sources/{id}/patterns.json
# aufgelistet; jedes enthaltene Pattern wird dann wie ein normales
# Einzelpattern behandelt (gleicher Download-Weg wie in Variante 2).

def find_reference_collections(items: list) -> list[dict]:
    """Filtert Library-Items, die Referenz-Collections sind (patterns_count>1,
    has_downloads=False) – also KEIN eigenes PDF-Bundle besitzen."""
    return [
        item for item in items
        if item.get("patterns_count", 1) > 1 and not item.get("has_downloads")
    ]


# ---------------------------------------------------------------------------
# 4. UNVERARBEITETE EINTRÄGE (Transparenz-Report, kein Download-Versuch)
# ---------------------------------------------------------------------------
#
# Nicht jeder Library-Eintrag passt in eines der drei Download-Schemata oben.
# Beobachtet wurden u.a.:
#   - 'single_pattern_source': pattern_source_id gesetzt, patterns_count==1,
#     aber KEIN pattern_id (z.B. Zeitschriften-Einzelhefte wie "Star Book
#     No. 169" oder "Filati Häkeln 02"). Verifiziert per Live-Abfrage: das
#     verknüpfte Pattern hat weder ravelry_download noch download_location
#     -> technisch nicht herunterladbar.
#   - 'orphan': weder pattern_id noch pattern_source_id gesetzt (z.B. "Noctiluca
#     Dress", ein bei Etsy erworbenes Pattern, oder "Crochet Every Way Stitch
#     Dictionary", ein reines Nachschlagewerk ohne einzelnes PDF).
#
# Diese Items sind bestätigt extern erworben und ABSICHTLICH NICHT herunter-
# zuladen (dient nur als durchsuchbare Referenz in der Library, siehe
# docs/ravelry-api-kb.md). Statt sie lautlos zu verschlucken, werden sie
# hier explizit erkannt und geloggt/reportet, damit nichts "verschwindet"
# ohne dass man es nachvollziehen kann.

def categorize_item(item: dict) -> str:
    """
    Ordnet einen Library-Eintrag genau einer Kategorie zu:
      - 'volume_bundle'         : has_downloads=True -> eigenes PDF-Bundle
                                   (wird von process_volumes behandelt)
      - 'individual_pattern'    : pattern_id gesetzt, patterns_count==1,
                                   has_downloads=False (process_individual_patterns)
      - 'reference_collection'  : patterns_count>1, has_downloads=False
                                   (process_reference_collections)
      - 'single_pattern_source' : pattern_source_id gesetzt, patterns_count==1,
                                   kein pattern_id -> i.d.R. extern erworbene
                                   Zeitschriften-Einzelhefte, nicht downloadbar
      - 'orphan'                : weder pattern_id noch pattern_source_id ->
                                   i.d.R. extern erworbene Patterns/Bücher,
                                   nur zu Recherchezwecken in der Library
    """
    if item.get("has_downloads"):
        return "volume_bundle"
    if item.get("pattern_id") and item.get("patterns_count", 1) == 1:
        return "individual_pattern"
    if item.get("patterns_count", 1) > 1:
        return "reference_collection"
    if item.get("pattern_source_id"):
        return "single_pattern_source"
    return "orphan"


def find_unhandled_items(items: list) -> list[dict]:
    """Items, die in KEINEM der drei Download-Pfade landen (single_pattern_source,
    orphan) – werden bewusst nicht herunterladen, siehe Modulkommentar oben."""
    return [
        item for item in items
        if categorize_item(item) in ("single_pattern_source", "orphan")
    ]


def report_unhandled_items(items: list) -> None:
    """
    Loggt alle unverarbeiteten Items (siehe find_unhandled_items) und schreibt
    die vollständige Liste als Report-Datei nach DOWNLOAD_DIR. Lädt NICHTS
    herunter – reine Transparenz, damit nichts lautlos verschwindet.
    """
    unhandled = find_unhandled_items(items)
    if not unhandled:
        return

    print(f"\nℹ️  {len(unhandled)} Library-Eintrag/Einträge ohne Download-Pfad "
          f"(typischerweise extern erworben, nur zur Recherche in der Library):")
    for item in unhandled[:10]:
        print(f"    - {item.get('title', 'Unbenannt')!r}")
    if len(unhandled) > 10:
        print(f"    … und {len(unhandled) - 10} weitere (vollständige Liste siehe Report-Datei).")

    try:
        with open(SKIPPED_REPORT_FILE, "w", encoding="utf-8") as f:
            f.write(
                "# Library-Einträge ohne erkennbaren Ravelry-Download-Pfad.\n"
                "# Diese Datei wird bei jedem Lauf überschrieben – reiner Report,\n"
                "# KEIN Steuer-Mechanismus (im Gegensatz zu ignore.txt/collections.txt).\n"
                "# Typischerweise extern erworbene Patterns/Zeitschriften, die nur\n"
                "# zu Recherchezwecken in die Library aufgenommen wurden.\n\n"
            )
            for item in unhandled:
                f.write(f"{item.get('title', 'Unbenannt')}\n")
        print(f"    → Vollständige Liste: {SKIPPED_REPORT_FILE}")
    except OSError as e:
        print(f"    ⚠️  Report konnte nicht geschrieben werden: {e}")


def write_excluded_log() -> None:
    """
    Schreibt alle in diesem Lauf nicht heruntergeladenen Einträge (per
    ignore.txt ODER per fehlender Freigabe in collections.txt) nach
    EXCLUDED_LOG_FILE. Wird bei JEDEM Lauf überschrieben – zeigt also nur,
    was im LETZTEN Lauf aktiv gefiltert wurde (nicht kumulativ über
    mehrere Läufe).
    """
    if not excluded_this_run:
        return

    try:
        with open(EXCLUDED_LOG_FILE, "w", encoding="utf-8") as f:
            f.write(
                "# Nicht heruntergeladene Einträge (letzter Lauf).\n"
                "# Diese Datei wird bei jedem Lauf überschrieben – reines Log,\n"
                "# zum Ändern selbst ignore.txt bzw. collections.txt bearbeiten.\n\n"
            )
            for entry in excluded_this_run:
                f.write(f"{entry}\n")
        print(f"\nℹ️  {len(excluded_this_run)} nicht heruntergeladene Einträge "
              f"protokolliert: {EXCLUDED_LOG_FILE}")
    except OSError as e:
        print(f"⚠️  Excluded-Log konnte nicht geschrieben werden: {e}")


def process_reference_collections(
    collections: list[dict],
    ignore_patterns: list[str],
    collection_includes: list[str],
) -> dict:
    """
    Lädt für jede per collections.txt AKTIVIERTE Referenz-Collection alle
    enthaltenen Pattern einzeln herunter (sofern sie ravelry_download
    anbieten, z.B. kostenlos sind). Nicht aktivierte Collections werden
    übersprungen und ins Excluded-Log eingetragen.
    """
    stats = {"downloaded": 0, "skipped_exists": 0, "skipped_ignore": 0, "error": 0}

    for col in collections:
        src_id = col.get("pattern_source_id")
        title  = col.get("title") or f"Collection_{src_id}"

        if not is_collection_included(col, collection_includes):
            print(f"🚫 Collection nicht aktiviert (collections.txt): {title!r} (source_id={src_id})")
            excluded_this_run.append(
                f"{title}  (Collection nicht aktiviert, source_id={src_id}, "
                f"{col.get('patterns_count', '?')} Pattern)"
            )
            continue

        print(f"\n📖 Referenz-Collection: {title!r}  ({col.get('patterns_count')} Pattern, "
              f"source_id={src_id})")

        # Alle Pattern dieser Quelle holen (paginiert)
        src_patterns = []
        page = 1
        while True:
            data = api_get(f"/pattern_sources/{src_id}/patterns.json",
                            {"page": page, "page_size": 100})
            batch = data.get("patterns", [])
            if not batch:
                break
            src_patterns.extend(batch)
            paginator = data.get("paginator", {})
            if page >= paginator.get("page_count", 1):
                break
            page += 1

        print(f"  → {len(src_patterns)} Pattern in dieser Collection gefunden.")

        for idx, p in enumerate(src_patterns, start=1):
            pid = p.get("id")
            name = p.get("name", f"pattern_{pid}")
            print(f"  [{idx}/{len(src_patterns)}] {name!r} …")

            # Volle Pattern-Details holen (Summary aus pattern_sources hat
            # kein download_location/ravelry_download-Feld)
            try:
                detail = api_get(f"/patterns/{pid}.json").get("pattern", {})
            except Exception as e:
                print(f"    ⚠️  Details konnten nicht geladen werden ({e})")
                stats["error"] += 1
                continue

            if not detail.get("ravelry_download"):
                print("    ℹ️  Kein Ravelry-Download verfügbar (externe Quelle).")
                continue

            # Bereits gekauft/in Library? -> über Volume laden (wie Variante 2)
            if detail.get("pdf_in_library") and detail.get("volumes_in_library"):
                vol_detail = api_get(
                    f"/volumes/{detail['volumes_in_library'][0]}.json"
                ).get("volume", {})
                attachments = vol_detail.get("volume_attachments", [])
                if not attachments:
                    continue
                att = attachments[0]
                url = att.get("ravelry_download_url")
                filename = att.get("filename") or sanitize_filename(name) + ".pdf"
                if not url:
                    print("    ℹ️  Keine Download-URL gefunden.")
                    continue
                result = try_download(url, filename, "Collection-Pattern", ignore_patterns)
                stats[result] = stats.get(result, 0) + 1
                continue

            # Nicht in Library, aber ravelry_download=true -> i.d.R. kostenlos,
            # download_location.url ist dann der direkte /dls/-Downloadlink.
            loc = detail.get("download_location")
            if isinstance(loc, dict):
                loc = [loc]
            url = next((l["url"] for l in (loc or []) if l.get("url")), None)

            if not url:
                print("    ℹ️  Keine Download-URL gefunden.")
                continue

            # Pattern mit MEHREREN Dateien liefert /dls/-URL statt eines
            # PDFs eine "Datei wählen"-Seite mit je einem Link pro Datei.
            # Das betrifft nicht nur Sprachübersetzungen (sehr häufig bei
            # Referenz-Collections wie Scheepjes "YARN - The After Party"),
            # sondern z.B. auch "Easy Read"-Versionen, separate Strick-
            # diagramme/Charts oder druckfreundliche Fassungen. Jede dieser
            # Dateien wird einzeln über try_download() geladen, damit
            # ignore.txt (das bereits etliche Sprach-Ausschlüsse wie
            # _NL.pdf/_FR.pdf/_KR.pdf pflegt und beliebig um andere
            # Varianten-Ausschlüsse ergänzt werden kann) genauso greift wie
            # bei allen anderen Downloads – KEINE Bevorzugung im Code.
            file_variants = fetch_file_variants(url)
            if file_variants is not None:
                for variant_filename, variant_url in file_variants:
                    result = try_download(
                        variant_url, variant_filename, "Collection-Pattern", ignore_patterns
                    )
                    stats[result] = stats.get(result, 0) + 1
                continue

            filename = sanitize_filename(name) + ".pdf"
            result = try_download(url, filename, "Collection-Pattern", ignore_patterns)
            stats[result] = stats.get(result, 0) + 1

    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    excluded_this_run.clear()  # Log soll nur den aktuellen Lauf zeigen
    ensure_download_dir()
    ignore_patterns = load_ignore_patterns(IGNORE_FILE)
    username = get_current_username()
    print(f"👤 Eingeloggt als: {username}\n")

    total_stats = {"downloaded": 0, "skipped_exists": 0, "skipped_ignore": 0, "error": 0}

    # --- Schritt 1: Volumes (eBooks, Collections mit eigenem PDF-Bundle) ---
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

    # --- Schritt 3: Referenz-Collections (ohne eigenes PDF-Bundle) ---
    if all_items:
        reference_collections = find_reference_collections(all_items)
        if reference_collections:
            print(f"\n📚 {len(reference_collections)} Referenz-Collection(en) gefunden "
                  f"(ohne eigenes PDF-Bundle, Mitglieder einzeln verlinkt).")

            # Neue Collections automatisch (inaktiv) in collections.txt eintragen,
            # dann die Freigabeliste neu einlesen (enthält jetzt die frischen Einträge).
            sync_new_reference_collections(reference_collections)
            collection_includes = load_collection_includes(COLLECTIONS_FILE)

            stats = process_reference_collections(
                reference_collections, ignore_patterns, collection_includes
            )
            for k, v in stats.items():
                total_stats[k] += v

    # --- Schritt 4: Transparenz-Report für nicht verarbeitbare Einträge ---
    if all_items:
        report_unhandled_items(all_items)

    # --- Schritt 5: Log der nicht heruntergeladenen Einträge ---
    write_excluded_log()

    # --- Zusammenfassung ---
    print("\n" + "=" * 50)
    print("✅ FERTIG")
    print(f"  ⬇️  Neu heruntergeladen : {total_stats['downloaded']}")
    print(f"  ➜   Bereits vorhanden  : {total_stats['skipped_exists']}")
    print(f"  🚫  Nicht heruntergeladen: {total_stats['skipped_ignore']}")
    print(f"  ❌  Fehler             : {total_stats['error']}")
    print("=" * 50)


if __name__ == "__main__":
    main()
