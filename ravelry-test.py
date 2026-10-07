#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "requests",
#   "python-dotenv",
#   "playwright",
# ]
# ///

"""
Ravelry API – Download-Test
============================
Testet für jede Pattern-Variante, ob ein PDF-Download funktioniert,
indem jeweils das ERSTE verfügbare Exemplar heruntergeladen wird.

Varianten:
  1. Kostenloses Ravelry-Pattern  (ravelry_download=true, free=true)
  2. Kostenpflichtiges Ravelry-Pattern (ravelry_download=true, free=false, in library)
  3. Einzelkauf-Pattern aus der Library (via library/search)
  4. eBook / Volume aus der Library   (volume_attachments)
  5. Collection                       (ein Volume mit patterns_count > 1)
  6. Bundle                           (mehrere Einzelpattern, gleicher Kauf-Zeitstempel)

Downloads landen in: test_downloads/

KOSTENPFLICHTIGE DOWNLOADS (Varianten 2-6):
---------------------------------------------
Deren URLs (/download/{id}/checkout) verlangen eine eingeloggte Browser-
Session statt der REST-API-Keys. Liefert ein Download-Versuch eine
HTML-Login-Seite statt eines PDFs, öffnet dieses Script automatisch einen
sichtbaren Browser (Playwright) zum manuellen Einloggen – siehe
ravelry_common.ensure_browser_login(). Die Session wird danach lokal
zwischengespeichert (.ravelry_session.json), sodass spätere Läufe nicht
erneut einloggen müssen.
"""

import json
import sys
import time

from ravelry_common import (
    AUTH,
    api_get,
    download_with_login_fallback,
    get_current_username,
    sanitize_filename,
)
from collections import defaultdict

TEST_DIR = "test_downloads"
import os
os.makedirs(TEST_DIR, exist_ok=True)

# Browser-Cookies werden lazy (erst bei Bedarf) geholt und dann für den
# restlichen Lauf wiederverwendet, damit nicht pro Variante neu eingeloggt wird.
browser_cookies: dict | None = None


# ── Hilfsfunktionen ────────────────────────────────────────────────────────

def save_pdf(url: str, filename: str) -> tuple[bool, str]:
    """Lädt ein PDF herunter, mit automatischem Browser-Login-Fallback."""
    global browser_cookies
    path = os.path.join(TEST_DIR, sanitize_filename(filename))
    ok, msg, browser_cookies = download_with_login_fallback(url, path, browser_cookies)
    return ok, msg


def result(label: str, ok: bool, detail: str):
    icon = "✅" if ok else "❌"
    print(f"\n{icon}  {label}")
    print(f"   {detail}")


def section(title: str):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print('─' * 60)


def dump(label: str, data):
    """Kompakte JSON-Ausgabe für Debug-Zwecke."""
    print(f"\n  ↳ {label}:")
    print("    " + json.dumps(data, indent=2, ensure_ascii=False)
          .replace("\n", "\n    ")[:600])


# ── Username ermitteln ─────────────────────────────────────────────────────

me = get_current_username()
print(f"\n👤 Eingeloggt als: {me}")


# ══════════════════════════════════════════════════════════════════════════
# VARIANTE 1 – Kostenloses Ravelry-Pattern (ravelry_download + free)
# ══════════════════════════════════════════════════════════════════════════
section("1 · Kostenloses Ravelry-Download-Pattern")

data = api_get("/patterns/search.json", {
    "availability": "free+ravelry",  # kostenlos UND direkt auf Ravelry
    "page_size": 1,
    "sort": "favorites",
})
patterns_free = data.get("patterns", [])

if not patterns_free:
    result("Variante 1", False, "Kein freies Ravelry-Download-Pattern gefunden.")
else:
    pid  = patterns_free[0]["id"]
    name = patterns_free[0].get("name", f"pattern_{pid}")
    print(f"  Pattern: {name!r}  (ID {pid})")

    detail = api_get(f"/patterns/{pid}.json")["pattern"]
    dump("Pattern-Felder (Auszug)", {
        "ravelry_download": detail.get("ravelry_download"),
        "free": detail.get("free"),
        "downloadable": detail.get("downloadable"),
        "pdf_url": detail.get("pdf_url"),
        "download_location": detail.get("download_location"),
    })

    loc = detail.get("download_location")
    # download_location kann dict oder list sein
    if isinstance(loc, dict):
        loc = [loc]
    url = next((l["url"] for l in (loc or []) if l.get("url")), None)

    if url:
        ok, msg = save_pdf(url, f"01_free_{sanitize_filename(name)}.pdf")
        result("Variante 1 – Kostenloses Ravelry-Pattern", ok, msg)
    else:
        result("Variante 1", False, "Keine download_location.url gefunden.")
    time.sleep(0.3)


# ══════════════════════════════════════════════════════════════════════════
# VARIANTE 2 – Kostenpflichtiges Ravelry-Pattern (aus eigener Library)
# ══════════════════════════════════════════════════════════════════════════
section("2 · Kostenpflichtiges Ravelry-Pattern (Library)")

# WICHTIG: library/search.json liefert IMMER "volume"-Objekte zurück – auch
# für einzeln gekaufte Pattern (Ravelry legt dafür intern ein 1:1-Volume an).
# Die relevanten Felder sind:
#   id                 -> Volume-ID (für /volumes/{id}.json)
#   pattern_id         -> echte Pattern-ID (für /patterns/{id}.json), oder null
#   pattern_source_id  -> gesetzt bei Collections/Heften, sonst null
#   patterns_count     -> >1 bedeutet Collection
#   has_downloads      -> ob überhaupt PDFs hinterlegt sind
lib_data = api_get(f"/people/{me}/library/search.json", {"page_size": 100})
all_volumes = lib_data.get("volumes", [])
paginator = lib_data.get("paginator", {})

print(f"  Library-Einträge (Seite 1): {len(all_volumes)} Volumes "
      f"(gesamt: {paginator.get('results')})")

# Einzelpattern = patterns_count == 1 UND pattern_id gesetzt
paid_pattern_found = False
for item in all_volumes:
    pid = item.get("pattern_id")
    if not pid or item.get("patterns_count", 1) != 1:
        continue  # keine Einzelpattern-Entry (sondern Collection o.ä.)

    detail = api_get(f"/patterns/{pid}.json").get("pattern", {})
    if not detail.get("ravelry_download") or detail.get("free"):
        continue  # wir suchen explizit ein KOSTENPFLICHTIGES Pattern

    name = detail.get("name", f"pattern_{pid}")
    print(f"  Pattern: {name!r}  (Pattern-ID {pid}, Volume-ID {item.get('id')})")
    dump("Pattern-Felder (Auszug)", {
        "ravelry_download": detail.get("ravelry_download"),
        "free": detail.get("free"),
        "pdf_in_library": detail.get("pdf_in_library"),
        "volumes_in_library": detail.get("volumes_in_library"),
        "download_location": detail.get("download_location"),
    })

    # WICHTIG: download_location.url ist eine KAUF-/CHECKOUT-URL (zum
    # Erwerben eines Patterns), KEINE Download-URL für bereits gekaufte
    # Inhalte! Ist das Pattern schon in der Library (pdf_in_library=true),
    # muss der PDF-Download über das zugehörige Volume laufen (wie bei den
    # Varianten 3/4): volumes_in_library -> /volumes/{id}.json ->
    # volume_attachments[].ravelry_download_url.
    url, filename = None, None
    volume_ids = detail.get("volumes_in_library") or []
    if detail.get("pdf_in_library") and volume_ids:
        vol_detail = api_get(f"/volumes/{volume_ids[0]}.json").get("volume", {})
        attachments = vol_detail.get("volume_attachments", [])
        if attachments:
            att = attachments[0]
            url = att.get("ravelry_download_url")
            filename = att.get("filename") or f"{sanitize_filename(name)}.pdf"

    if url:
        ok, msg = save_pdf(url, f"02_paid_{sanitize_filename(filename)}")
        result("Variante 2 – Kostenpflichtiges Ravelry-Pattern", ok, msg)
    else:
        result("Variante 2", False,
               "Pattern weder mit volumes_in_library noch mit Download-URL gefunden.")
    paid_pattern_found = True
    time.sleep(0.3)
    break  # nur das erste

if not paid_pattern_found:
    result("Variante 2", False,
           "Kein kostenpflichtiges Einzelpattern in der Library gefunden.")


# ══════════════════════════════════════════════════════════════════════════
# VARIANTE 3 – PDF aus der Library (library/search, erster Treffer gesamt)
# ══════════════════════════════════════════════════════════════════════════
section("3 · Erster Library-Eintrag überhaupt (library/search ohne Filter)")

# Die Summary-Objekte aus library/search enthalten KEINE volume_attachments –
# die stecken erst in den Details unter /volumes/{id}.json.
first_item = all_volumes[0] if all_volumes else None

if not first_item:
    result("Variante 3", False, "Library ist leer.")
else:
    print(f"  Summary-Keys: {list(first_item.keys())}")
    dump("Erster Library-Eintrag (Summary)", first_item)

    vol_id = first_item.get("id")
    vol_detail = api_get(f"/volumes/{vol_id}.json").get("volume", {})
    attachments = vol_detail.get("volume_attachments", [])
    dump("Volume-Details: volume_attachments (Dateinamen)",
         [a.get("filename") for a in attachments])

    url, filename = None, None
    if attachments:
        att = attachments[0]
        url = att.get("ravelry_download_url")
        filename = att.get("filename") or f"03_library_{vol_id}.pdf"

    if url:
        ok, msg = save_pdf(url, f"03_library_{sanitize_filename(filename)}")
        result("Variante 3 – Library-Eintrag", ok, msg)
    else:
        result("Variante 3", False, "Keine Download-URL in diesem Eintrag gefunden.")
    time.sleep(0.3)


# ══════════════════════════════════════════════════════════════════════════
# VARIANTE 4 – eBook / Volume (Buch mit PDF-Anhang)
# ══════════════════════════════════════════════════════════════════════════
section("4 · eBook / Volume (type=pdf)")

pdf_lib = api_get(f"/people/{me}/library/search.json", {
    "page_size": 1,
    "type": "pdf",
})
pdf_volumes = pdf_lib.get("volumes", [])

if not pdf_volumes:
    result("Variante 4", False, "Keine Volumes in der Library gefunden.")
else:
    vol_id    = pdf_volumes[0]["id"]
    vol_title = pdf_volumes[0].get("title", f"Volume_{vol_id}")
    print(f"  Volume: {vol_title!r}  (ID {vol_id})")

    vol_detail = api_get(f"/volumes/{vol_id}.json")["volume"]
    attachments = vol_detail.get("volume_attachments", [])

    dump("Volume-Felder (Auszug)", {
        "id": vol_detail.get("id"),
        "title": vol_detail.get("title"),
        "volume_attachments": [
            {k: v for k, v in a.items() if k != "ravelry_download_url"}
            for a in attachments
        ],
    })

    if not attachments:
        result("Variante 4", False, "Volume hat keine PDF-Anhänge.")
    else:
        att = attachments[0]
        url = att.get("ravelry_download_url")
        filename = att.get("filename") or f"04_ebook_{sanitize_filename(vol_title)}.pdf"
        if url:
            ok, msg = save_pdf(url, f"04_ebook_{sanitize_filename(filename)}")
            result("Variante 4 – eBook/Volume", ok, msg)
        else:
            result("Variante 4", False, "ravelry_download_url fehlt in attachment.")
    time.sleep(0.3)


# ══════════════════════════════════════════════════════════════════════════
# VARIANTE 5 – Collection (mehrere Pattern in einem Heft/eBook, eigene Library)
# ══════════════════════════════════════════════════════════════════════════
section("5 · Collection (patterns_count > 1, eigene Library)")

# Eine Collection erkennt man in der eigenen Library an patterns_count > 1
# UND has_downloads=True. pattern_sources/search.json liefert zwar Collections,
# aber KEIN volume_id-Feld – also nicht direkt mit einem eigenen PDF verknüpft.
# Deshalb: über die eigene Library suchen (dort ist der Download garantiert).
collection_item = next(
    (v for v in all_volumes
     if v.get("patterns_count", 1) > 1 and v.get("has_downloads")),
    None,
)

if not collection_item:
    result("Variante 5", False,
           "Keine Collection (patterns_count>1) mit Downloads in der Library gefunden.")
else:
    vol_id = collection_item.get("id")
    title  = collection_item.get("title", f"Collection_{vol_id}")
    print(f"  Collection: {title!r}  (Volume-ID {vol_id}, "
          f"{collection_item.get('patterns_count')} Patterns)")

    vol_detail  = api_get(f"/volumes/{vol_id}.json").get("volume", {})
    attachments = vol_detail.get("volume_attachments", [])
    dump("Collection-Attachments (Dateinamen)",
         [a.get("filename") for a in attachments])

    if not attachments:
        result("Variante 5", False, "Collection-Volume hat keine PDF-Anhänge.")
    else:
        att = attachments[0]
        url = att.get("ravelry_download_url")
        filename = att.get("filename") or f"05_collection_{sanitize_filename(title)}.pdf"
        if url:
            ok, msg = save_pdf(url, f"05_collection_{sanitize_filename(filename)}")
            result("Variante 5 – Collection", ok, msg)
        else:
            result("Variante 5", False, "ravelry_download_url fehlt in attachment.")
    time.sleep(0.3)


# ══════════════════════════════════════════════════════════════════════════
# VARIANTE 6 – Bundle (mehrere Einzelpattern gemeinsam gekauft)
# ══════════════════════════════════════════════════════════════════════════
section("6 · Bundle (mehrere Einzelpattern im selben Kauf)")

# Ein Bundle-Kauf (z.B. Designer-Paket mit mehreren Patterns) erzeugt pro
# Pattern ein EIGENES Volume mit eigener pattern_id, aber alle mit demselben
# created_at-Zeitstempel (= derselbe Checkout). patterns_count ist bei jedem
# einzelnen Eintrag 1 – das unterscheidet es von einer "Collection"
# (Variante 5, EIN Volume mit patterns_count > 1).
all_lib = []
for pg in range(1, 10):
    page_data = api_get(f"/people/{me}/library/search.json", {"page_size": 100, "page": pg})
    all_lib.extend(page_data.get("volumes", []))
    if pg >= page_data.get("paginator", {}).get("page_count", 1):
        break

by_timestamp: dict = defaultdict(list)
for item in all_lib:
    if item.get("pattern_id") and item.get("patterns_count", 1) == 1:
        by_timestamp[item.get("created_at")].append(item)

bundle_group = next((items for items in by_timestamp.values() if len(items) > 1), None)

if not bundle_group:
    result("Variante 6", False,
           "Keine Gruppe von Einzelpattern mit identischem Kauf-Zeitstempel gefunden.")
else:
    print(f"  Bundle gefunden: {len(bundle_group)} Pattern mit Zeitstempel "
          f"{bundle_group[0].get('created_at')}")
    dump("Bundle-Mitglieder", [
        {"title": it.get("title"), "pattern_id": it.get("pattern_id")}
        for it in bundle_group
    ])

    first = bundle_group[0]
    vol_id = first.get("id")
    vol_detail = api_get(f"/volumes/{vol_id}.json").get("volume", {})
    attachments = vol_detail.get("volume_attachments", [])

    url, filename = None, None
    if attachments:
        att = attachments[0]
        url = att.get("ravelry_download_url")
        filename = att.get("filename") or f"06_bundle_{sanitize_filename(first.get('title', str(vol_id)))}.pdf"

    if url:
        ok, msg = save_pdf(url, f"06_bundle_{sanitize_filename(filename)}")
        result(f"Variante 6 – Bundle-Teil: {first.get('title')!r}", ok, msg)
    else:
        result("Variante 6", False, "Erstes Bundle-Pattern hat keinen PDF-Anhang.")
    time.sleep(0.3)


# ══════════════════════════════════════════════════════════════════════════
# ZUSAMMENFASSUNG
# ══════════════════════════════════════════════════════════════════════════
print(f"\n{'═' * 60}")
print(f"  Downloads gespeichert in: {os.path.abspath(TEST_DIR)}/")
for f in sorted(os.listdir(TEST_DIR)):
    size = os.path.getsize(os.path.join(TEST_DIR, f)) // 1024
    print(f"    {f}  ({size} KB)")
print('═' * 60)
