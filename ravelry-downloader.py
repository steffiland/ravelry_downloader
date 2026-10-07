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

Ausschlüsse via ravelry_downloads/ignore.txt:
  - Normale Zeile  → Substring-Filter gegen den Ziel-Dateinamen
  - 'collection:<id-oder-teiltitel>' → überspringt eine ganze Referenz-Collection
    (Variante 3 oben) komplett, z.B. 'collection:213142' oder
    'collection:Yarn - The After Party'

AUTOMATISCHER OPT-OUT-SYNC für Referenz-Collections (Variante 3):
--------------------------------------------------------------------
Referenz-Collections werden standardmäßig NICHT herunterladen (praktisch für
Bibliotheken, in die z.B. gekaufte Zeitschriften nur zu Recherche-Zwecken
eingetragen wurden, ohne dass ein Download je funktionieren soll). Bei jedem
Lauf schreibt das Script neu gefundene Referenz-Collections automatisch als
'collection:<id>  # <Titel> (<Anzahl> Pattern)' in ignore.txt – du musst
nichts manuell eintragen. Willst du eine bestimmte Collection doch
herunterladen, lösche einfach ihre Zeile aus ignore.txt. Welche IDs schon
einmal eingetragen wurden, merkt sich das Script in
ravelry_downloads/.collection_sync.json – eine gelöschte Zeile wird dadurch
NICHT beim nächsten Lauf automatisch wieder hinzugefügt.

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
    get_current_username,
    sanitize_filename,
)

BASE_URL         = "https://api.ravelry.com"
DOWNLOAD_DIR     = "ravelry_downloads"
IGNORE_FILE      = os.path.join(DOWNLOAD_DIR, "ignore.txt")
COLLECTION_SYNC_FILE = os.path.join(DOWNLOAD_DIR, ".collection_sync.json")

# Browser-Cookies werden lazy (erst bei Bedarf) geholt und dann für den
# restlichen Lauf wiederverwendet, damit nicht pro Datei neu eingeloggt wird.
browser_cookies: dict | None = None


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def load_ignore_patterns(ignore_filepath: str) -> tuple[list[str], list[str]]:
    """
    Lädt Ignorier-Muster aus einer Textdatei.
    Erstellt eine Beispiel-Datei, falls noch keine existiert.

    Es gibt zwei Arten von Zeilen:
      - normale Zeile       -> Substring-Filter gegen Ziel-DATEINAMEN
      - 'collection:<wert>' -> überspringt eine ganze Referenz-Collection
                                (<wert> = pattern_source_id ODER Teil des Titels)

    Gibt (filename_patterns, collection_excludes) zurück.
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
            "#\n"
            "# Ganze Referenz-Collections ausschließen (patterns_count>1 ohne\n"
            "# eigenes PDF-Bundle, z.B. Scheepjes 'YARN - The After Party'):\n"
            "# Entweder per pattern_source_id oder per (Teil-)Titel:\n"
            "# collection:213142\n"
            "# collection:Yarn - The After Party\n"
        )
        with open(ignore_filepath, "w", encoding="utf-8") as f:
            f.write(default_content)
        print(f"ℹ️  Neue Ignorier-Datei erstellt: '{ignore_filepath}'")
        return [], []

    filename_patterns = []
    collection_excludes = []
    with open(ignore_filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Inline-Kommentare abschneiden (z.B. aus den automatisch von
            # sync_new_reference_collections() generierten Zeilen:
            # 'collection:213142  # Titel (147 Pattern)')
            line_without_comment = line.split("#", 1)[0].strip()
            if not line_without_comment:
                continue

            if line_without_comment.lower().startswith("collection:"):
                value = line_without_comment.split(":", 1)[1].strip().lower()
                if value:
                    collection_excludes.append(value)
            else:
                filename_patterns.append(line_without_comment.lower())

    if filename_patterns:
        print(f"ℹ️  {len(filename_patterns)} Datei-Ignorier-Muster aus '{ignore_filepath}' geladen.")
    if collection_excludes:
        print(f"ℹ️  {len(collection_excludes)} Collection-Ausschluss(e) aus '{ignore_filepath}' geladen.")
    return filename_patterns, collection_excludes


def is_ignored(filename: str, ignore_patterns: list[str]) -> bool:
    """Prüft, ob ein Dateiname mit einem der Ignorier-Muster übereinstimmt."""
    filename_lower = filename.lower()
    return any(p in filename_lower for p in ignore_patterns)


def is_collection_ignored(collection_item: dict, collection_excludes: list[str]) -> bool:
    """
    Prüft, ob eine Referenz-Collection per 'collection:<id-oder-titel>' in
    ignore.txt ausgeschlossen wurde.
    """
    src_id = str(collection_item.get("pattern_source_id", "")).lower()
    title  = (collection_item.get("title") or "").lower()
    return any(excl == src_id or excl in title for excl in collection_excludes)


def load_synced_collection_ids() -> set[int]:
    """Lädt die Menge der pattern_source_ids, die schon einmal in ignore.txt
    automatisch eingetragen wurden (siehe sync_new_reference_collections)."""
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
    automatisch als 'collection:<id>  # <Titel> (<n> Pattern)' in ignore.txt
    ein. So sind sie standardmäßig vom Download ausgeschlossen – wer eine
    bestimmte Collection doch laden will, löscht einfach ihre Zeile.

    Bereits einmal synchronisierte IDs werden in COLLECTION_SYNC_FILE
    gemerkt, damit eine manuell gelöschte Zeile NICHT erneut hinzugefügt
    wird (sonst könnte man nie dauerhaft "ja, bitte laden" sagen).
    """
    already_synced = load_synced_collection_ids()
    new_ones = [
        c for c in collections
        if c.get("pattern_source_id") not in already_synced
    ]
    if not new_ones:
        return

    lines = [
        f"collection:{c['pattern_source_id']}  "
        f"# {c.get('title', 'Unbenannt')} ({c.get('patterns_count', '?')} Pattern)"
        for c in new_ones
    ]
    header = (
        f"\n# --- Automatisch ergänzt am {time.strftime('%Y-%m-%d %H:%M')} "
        f"({len(new_ones)} neue Referenz-Collection(en)) ---\n"
        "# Standardmäßig ausgeschlossen. Zeile löschen = Collection WIRD "
        "heruntergeladen.\n"
    )
    with open(IGNORE_FILE, "a", encoding="utf-8") as f:
        f.write(header + "\n".join(lines) + "\n")

    already_synced.update(c["pattern_source_id"] for c in new_ones)
    save_synced_collection_ids(already_synced)

    print(f"ℹ️  {len(new_ones)} neue Referenz-Collection(en) automatisch in "
          f"'{IGNORE_FILE}' eingetragen (standardmäßig ausgeschlossen).")


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


def process_reference_collections(
    collections: list[dict],
    ignore_patterns: list[str],
    collection_excludes: list[str],
) -> dict:
    """
    Lädt für jede Referenz-Collection alle enthaltenen Pattern einzeln
    herunter (sofern sie ravelry_download anbieten, z.B. kostenlos sind).
    """
    stats = {"downloaded": 0, "skipped_exists": 0, "skipped_ignore": 0, "error": 0}

    for col in collections:
        src_id = col.get("pattern_source_id")
        title  = col.get("title") or f"Collection_{src_id}"

        if is_collection_ignored(col, collection_excludes):
            print(f"🚫 Collection übersprungen (ignore.txt): {title!r} (source_id={src_id})")
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
            else:
                # Nicht in Library, aber ravelry_download=true -> i.d.R. kostenlos,
                # download_location.url ist dann der direkte /dls/-Downloadlink.
                loc = detail.get("download_location")
                if isinstance(loc, dict):
                    loc = [loc]
                url = next((l["url"] for l in (loc or []) if l.get("url")), None)
                filename = sanitize_filename(name) + ".pdf"

            if not url:
                print("    ℹ️  Keine Download-URL gefunden.")
                continue

            result = try_download(url, filename, "Collection-Pattern", ignore_patterns)
            stats[result] = stats.get(result, 0) + 1

    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ensure_download_dir()
    ignore_patterns, collection_excludes = load_ignore_patterns(IGNORE_FILE)
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

            # Neue Collections automatisch als Opt-out in ignore.txt eintragen,
            # dann die Ignore-Liste neu einlesen (enthält jetzt die frischen Einträge).
            sync_new_reference_collections(reference_collections)
            ignore_patterns, collection_excludes = load_ignore_patterns(IGNORE_FILE)

            stats = process_reference_collections(
                reference_collections, ignore_patterns, collection_excludes
            )
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
