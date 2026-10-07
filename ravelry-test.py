#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "requests",
#   "python-dotenv",
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
  5. Collection / Pattern-Source      (mehrere Pattern in einem Buch/Heft)
  6. Bundle-Pattern                   (mehrere Patterns gemeinsam gekauft → ravelry_download)

Downloads landen in: test_downloads/
"""

import os
import json
import re
import sys
import time
import requests
from dotenv import load_dotenv

load_dotenv()

ACCESS_KEY   = os.getenv("RAVELRY_ACCESS_KEY")
PERSONAL_KEY = os.getenv("RAVELRY_PERSONAL_KEY")

if not ACCESS_KEY or not PERSONAL_KEY:
    sys.exit("❌ RAVELRY_ACCESS_KEY oder RAVELRY_PERSONAL_KEY fehlt in der .env-Datei!")

BASE_URL  = "https://api.ravelry.com"
AUTH      = (ACCESS_KEY, PERSONAL_KEY)
TEST_DIR  = "test_downloads"
os.makedirs(TEST_DIR, exist_ok=True)


# ── Hilfsfunktionen ────────────────────────────────────────────────────────

def get(path: str, params: dict | None = None) -> dict:
    """GET gegen die Ravelry-API mit Auth."""
    r = requests.get(f"{BASE_URL}{path}", auth=AUTH, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def sanitize(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name)


def save_pdf(url: str, filename: str) -> tuple[bool, str]:
    """
    Lädt eine Datei von url nach TEST_DIR/{filename}.
    Gibt (True, pfad) oder (False, fehlermeldung) zurück.
    Kein auth= nötig – vorsignierte S3-URL.
    """
    path = os.path.join(TEST_DIR, sanitize(filename))
    if not path.lower().endswith(".pdf"):
        path += ".pdf"
    try:
        r = requests.get(url, stream=True, timeout=60)
        r.raise_for_status()
        chunks = r.iter_content(chunk_size=8192)
        first  = next(chunks, None)
        if not first:
            return False, "Datei leer (0 Bytes)"
        ct = r.headers.get("Content-Type", "")
        if not first.startswith(b"%PDF-") and "pdf" not in ct.lower():
            preview = first[:200].decode("utf-8", errors="ignore")
            return False, f"Kein PDF (Content-Type: {ct})\n    Vorschau: {preview!r}"
        with open(path, "wb") as f:
            f.write(first)
            for chunk in chunks:
                if chunk:
                    f.write(chunk)
        size_kb = os.path.getsize(path) // 1024
        return True, f"{path}  ({size_kb} KB)"
    except Exception as e:
        return False, str(e)


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

me = get("/current_user.json")["user"]["username"]
print(f"\n👤 Eingeloggt als: {me}")


# ══════════════════════════════════════════════════════════════════════════
# VARIANTE 1 – Kostenloses Ravelry-Pattern (ravelry_download + free)
# ══════════════════════════════════════════════════════════════════════════
section("1 · Kostenloses Ravelry-Download-Pattern")

data = get("/patterns/search.json", {
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

    detail = get(f"/patterns/{pid}.json")["pattern"]
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
        ok, msg = save_pdf(url, f"01_free_{sanitize(name)}.pdf")
        result("Variante 1 – Kostenloses Ravelry-Pattern", ok, msg)
    else:
        result("Variante 1", False, "Keine download_location.url gefunden.")
    time.sleep(0.3)


# ══════════════════════════════════════════════════════════════════════════
# VARIANTE 2 – Kostenpflichtiges Ravelry-Pattern (aus eigener Library)
# ══════════════════════════════════════════════════════════════════════════
section("2 · Kostenpflichtiges Ravelry-Pattern (Library)")

lib_data = get(f"/people/{me}/library/search.json", {
    "page_size": 100,
})
all_volumes = lib_data.get("volumes", [])
all_patterns_lib = lib_data.get("patterns", [])
paginator = lib_data.get("paginator", {})

print(f"  Library-Einträge (Seite 1): {len(all_volumes)} Volumes, "
      f"{len(all_patterns_lib)} Patterns")
print(f"  Paginierung: {paginator}")

# Unter den volumes: welche haben KEINE volume_attachments?
# Das könnten Einzelpattern-Wrapper sein → Pattern-Details prüfen
paid_pattern_found = False
for item in all_volumes:
    if item.get("volume_attachments"):
        continue  # das ist ein echtes Volume → Variante 4
    pid = item.get("id")
    if not pid:
        continue

    detail = get(f"/patterns/{pid}.json").get("pattern", {})
    if not detail.get("ravelry_download"):
        continue

    name = detail.get("name", f"pattern_{pid}")
    print(f"  Pattern: {name!r}  (ID {pid})")
    dump("Pattern-Felder (Auszug)", {
        "ravelry_download": detail.get("ravelry_download"),
        "free": detail.get("free"),
        "download_location": detail.get("download_location"),
    })

    loc = detail.get("download_location")
    if isinstance(loc, dict):
        loc = [loc]
    url = next((l["url"] for l in (loc or []) if l.get("url")), None)

    if url:
        ok, msg = save_pdf(url, f"02_paid_{sanitize(name)}.pdf")
        result("Variante 2 – Kostenpflichtiges Ravelry-Pattern", ok, msg)
    else:
        result("Variante 2", False, "Keine download_location.url gefunden.")
    paid_pattern_found = True
    time.sleep(0.3)
    break  # nur das erste

if not paid_pattern_found:
    result("Variante 2", False,
           "Kein kostenpflichtiges Einzelpattern in der Library gefunden\n"
           "   (alle Library-Einträge sind Volumes oder haben keine ravelry_download-Flag).")


# ══════════════════════════════════════════════════════════════════════════
# VARIANTE 3 – PDF aus der Library (library/search, erster Treffer gesamt)
# ══════════════════════════════════════════════════════════════════════════
section("3 · Erster Library-Eintrag überhaupt (library/search ohne Filter)")

# Wir schauen was als allererstes kommt, und zeigen alle Felder
first_item = (all_volumes + all_patterns_lib)[0] if (all_volumes or all_patterns_lib) else None

if not first_item:
    result("Variante 3", False, "Library ist leer.")
else:
    print(f"  Typ-Erkennung (Keys): {list(first_item.keys())}")
    dump("Erster Library-Eintrag (komplett)", first_item)

    # Versuchen, irgendwie an eine URL zu kommen
    url = None

    # a) Hat volume_attachments?
    for att in first_item.get("volume_attachments", []):
        if att.get("ravelry_download_url"):
            url = att["ravelry_download_url"]
            filename = att.get("filename", f"03_library_{first_item.get('id')}.pdf")
            break

    # b) Hat download_location?
    if not url:
        loc = first_item.get("download_location")
        if isinstance(loc, dict):
            loc = [loc]
        url = next((l["url"] for l in (loc or []) if l.get("url")), None)
        if url:
            filename = f"03_library_{sanitize(first_item.get('title', str(first_item.get('id'))))}.pdf"

    if url:
        ok, msg = save_pdf(url, filename)
        result("Variante 3 – Library-Eintrag", ok, msg)
    else:
        result("Variante 3", False, "Keine Download-URL in diesem Eintrag gefunden.")
    time.sleep(0.3)


# ══════════════════════════════════════════════════════════════════════════
# VARIANTE 4 – eBook / Volume (Buch mit PDF-Anhang)
# ══════════════════════════════════════════════════════════════════════════
section("4 · eBook / Volume (type=pdf)")

pdf_lib = get(f"/people/{me}/library/search.json", {
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

    vol_detail = get(f"/volumes/{vol_id}.json")["volume"]
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
        filename = att.get("filename") or f"04_ebook_{sanitize(vol_title)}.pdf"
        if url:
            ok, msg = save_pdf(url, f"04_ebook_{sanitize(filename)}")
            result("Variante 4 – eBook/Volume", ok, msg)
        else:
            result("Variante 4", False, "ravelry_download_url fehlt in attachment.")
    time.sleep(0.3)


# ══════════════════════════════════════════════════════════════════════════
# VARIANTE 5 – Collection / Pattern-Source (mehrere Pattern in einem Heft)
# ══════════════════════════════════════════════════════════════════════════
section("5 · Collection / Pattern-Source (pattern_sources/search)")

ps_data = get("/pattern_sources/search.json", {
    "query": "",
    "page_size": 5,
    "availability": "ravelry",   # nur Ravelry-Downloads
})
sources = ps_data.get("pattern_sources", [])
print(f"  Pattern-Sources gefunden: {len(sources)}")

collection_done = False
for src in sources:
    src_id   = src.get("id")
    src_name = src.get("name", f"source_{src_id}")
    print(f"  Prüfe Source: {src_name!r}  (ID {src_id})")

    src_detail = get(f"/pattern_sources/{src_id}.json").get("pattern_source", {})
    dump("Source-Felder (Auszug)", {
        "id": src_detail.get("id"),
        "name": src_detail.get("name"),
        "volume_id": src_detail.get("volume_id"),
        "free": src_detail.get("free"),
        "ravelry_download": src_detail.get("ravelry_download"),
    })

    vol_id = src_detail.get("volume_id")
    if vol_id:
        vol_detail = get(f"/volumes/{vol_id}.json").get("volume", {})
        attachments = vol_detail.get("volume_attachments", [])
        if attachments:
            att = attachments[0]
            url = att.get("ravelry_download_url")
            filename = att.get("filename") or f"05_collection_{sanitize(src_name)}.pdf"
            if url:
                ok, msg = save_pdf(url, f"05_collection_{sanitize(filename)}")
                result("Variante 5 – Collection (via Volume)", ok, msg)
                collection_done = True
                time.sleep(0.3)
                break

if not collection_done:
    # Fallback: erstes Pattern aus einer öffentlichen Collection laden
    coll_data = get("/patterns/search.json", {
        "availability": "ravelry",
        "page_size": 1,
        "sort": "favorites",
    })
    coll_patterns = coll_data.get("patterns", [])
    if coll_patterns:
        pid    = coll_patterns[0]["id"]
        detail = get(f"/patterns/{pid}.json")["pattern"]
        name   = detail.get("name", f"pattern_{pid}")
        src    = detail.get("pattern_source", {})
        print(f"\n  Fallback-Pattern: {name!r}, Quelle: {src.get('name')!r}")
        dump("Pattern Volumes/Download", {
            "pdf_in_library": detail.get("pdf_in_library"),
            "volumes_in_library": detail.get("volumes_in_library"),
            "ravelry_download": detail.get("ravelry_download"),
            "download_location": detail.get("download_location"),
        })
        result("Variante 5", False,
               "Keine Collection-PDF im eigenen Account → Felder ausgegeben.")
    else:
        result("Variante 5", False, "Keine Collection-Pattern gefunden.")


# ══════════════════════════════════════════════════════════════════════════
# VARIANTE 6 – Bundle (mehrere Pattern zusammen gekauft)
# ══════════════════════════════════════════════════════════════════════════
section("6 · Bundle (mehrere Pattern gemeinsam in Library)")

# Bundles sind auf Ravelry Favoriten-Sammlungen ODER
# Designer-Pakete. Beim Kauf landen Einzel-PDFs in der Library.
# Wir schauen, ob die Library mehrere Einträge hat, die zusammengehören
# (gleicher pattern_source / gleicher volume_id).

bundle_done = False

# Alle Library-Einträge holen (bis zu 3 Seiten)
all_lib = []
for pg in range(1, 4):
    page_data = get(f"/people/{me}/library/search.json", {"page_size": 100, "page": pg})
    batch = page_data.get("volumes", []) + page_data.get("patterns", [])
    all_lib.extend(batch)
    if pg >= page_data.get("paginator", {}).get("page_count", 1):
        break

# Pattern-Source-ID aus jedem Eintrag extrahieren
from collections import defaultdict
by_source: dict = defaultdict(list)
for item in all_lib:
    src_id = (item.get("pattern_source") or {}).get("id")
    if src_id:
        by_source[src_id].append(item)

# Eine Source mit >1 Einträgen = Bundle-Kandidat
bundle_src_id = next((sid for sid, items in by_source.items() if len(items) > 1), None)

if bundle_src_id:
    bundle_items = by_source[bundle_src_id]
    src_name = (bundle_items[0].get("pattern_source") or {}).get("name", str(bundle_src_id))
    print(f"  Bundle gefunden: {src_name!r}  ({len(bundle_items)} Einträge)")

    for item in bundle_items[:3]:  # max. 3 zeigen
        item_id    = item.get("id")
        item_title = item.get("title") or item.get("name", str(item_id))
        attachments = item.get("volume_attachments", [])

        if attachments:
            att = attachments[0]
            url = att.get("ravelry_download_url")
            filename = att.get("filename") or f"06_bundle_{sanitize(item_title)}.pdf"
            if url:
                ok, msg = save_pdf(url, f"06_bundle_{sanitize(filename)}")
                result(f"Variante 6 – Bundle-Teil: {item_title!r}", ok, msg)
                bundle_done = True
                time.sleep(0.3)
                break
        else:
            # Kein Attachment → als Pattern-Download probieren
            detail = get(f"/patterns/{item_id}.json").get("pattern", {})
            if detail.get("ravelry_download"):
                loc = detail.get("download_location")
                if isinstance(loc, dict):
                    loc = [loc]
                url = next((l["url"] for l in (loc or []) if l.get("url")), None)
                if url:
                    name = detail.get("name", str(item_id))
                    ok, msg = save_pdf(url, f"06_bundle_{sanitize(name)}.pdf")
                    result(f"Variante 6 – Bundle-Teil: {name!r}", ok, msg)
                    bundle_done = True
                    time.sleep(0.3)
                    break

if not bundle_done:
    # Fallback: User-eigene Bundles (Favoriten-Sammlungen)
    bundles_data = get(f"/people/{me}/bundles/list.json")
    bundles = bundles_data.get("bundles", [])
    print(f"\n  User-Bundles (Favoriten-Sammlungen): {len(bundles)}")
    if bundles:
        b = bundles[0]
        dump("Erstes User-Bundle", {
            "id": b.get("id"),
            "title": b.get("title"),
            "count": b.get("count"),
        })
    result("Variante 6", False,
           "Kein Download-Bundle in Library gefunden.\n"
           "   (Bundles sind Designer-Pakete; beim Kauf → Einzelpatterns in Library)")


# ══════════════════════════════════════════════════════════════════════════
# ZUSAMMENFASSUNG
# ══════════════════════════════════════════════════════════════════════════
print(f"\n{'═' * 60}")
print(f"  Downloads gespeichert in: {os.path.abspath(TEST_DIR)}/")
for f in sorted(os.listdir(TEST_DIR)):
    size = os.path.getsize(os.path.join(TEST_DIR, f)) // 1024
    print(f"    {f}  ({size} KB)")
print('═' * 60)
