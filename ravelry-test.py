#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "requests",
#   "python-dotenv",
#   "playwright",
# ]
# ///

"""
Ravelry API - Download Test
============================
Tests whether a PDF download works for each pattern variant, by
downloading the FIRST available example for each.

Variants:
  1. Free Ravelry pattern         (ravelry_download=true, free=true)
  2. Paid Ravelry pattern         (ravelry_download=true, free=false, in library)
  3. Individually purchased pattern from the library (via library/search)
  4. eBook / volume from the library  (volume_attachments)
  5. Collection                       (a volume with patterns_count > 1)
  6. Bundle                           (multiple individual patterns, same purchase timestamp)

Downloads end up in: test_downloads/

PAID DOWNLOADS (variants 2-6):
---------------------------------------------
Their URLs (/download/{id}/checkout) require a logged-in browser session
instead of the REST API keys. If a download attempt returns an HTML login
page instead of a PDF, this script automatically opens a visible browser
(Playwright) for manual login - see ravelry_common.ensure_browser_login().
The session is then cached locally (.ravelry_session.json), so later runs
don't need to log in again.
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

# Browser cookies are fetched lazily (only when needed) and then reused
# for the rest of the run, so there's no need to log in again per variant.
browser_cookies: dict | None = None


# ── Helper functions ───────────────────────────────────────────────────────

def save_pdf(url: str, filename: str) -> tuple[bool, str]:
    """Downloads a PDF, with automatic browser-login fallback."""
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
    """Compact JSON output for debugging purposes."""
    print(f"\n  ↳ {label}:")
    print("    " + json.dumps(data, indent=2, ensure_ascii=False)
          .replace("\n", "\n    ")[:600])


# ── Determine username ──────────────────────────────────────────────────────

me = get_current_username()
print(f"\n👤 Logged in as: {me}")


# ══════════════════════════════════════════════════════════════════════════
# VARIANT 1 - Free Ravelry pattern (ravelry_download + free)
# ══════════════════════════════════════════════════════════════════════════
section("1 · Free Ravelry download pattern")

data = api_get("/patterns/search.json", {
    "availability": "free+ravelry",  # free AND directly on Ravelry
    "page_size": 1,
    "sort": "favorites",
})
patterns_free = data.get("patterns", [])

if not patterns_free:
    result("Variant 1", False, "No free Ravelry download pattern found.")
else:
    pid  = patterns_free[0]["id"]
    name = patterns_free[0].get("name", f"pattern_{pid}")
    print(f"  Pattern: {name!r}  (ID {pid})")

    detail = api_get(f"/patterns/{pid}.json")["pattern"]
    dump("Pattern fields (excerpt)", {
        "ravelry_download": detail.get("ravelry_download"),
        "free": detail.get("free"),
        "downloadable": detail.get("downloadable"),
        "pdf_url": detail.get("pdf_url"),
        "download_location": detail.get("download_location"),
    })

    loc = detail.get("download_location")
    # download_location can be a dict or a list
    if isinstance(loc, dict):
        loc = [loc]
    url = next((l["url"] for l in (loc or []) if l.get("url")), None)

    if url:
        ok, msg = save_pdf(url, f"01_free_{sanitize_filename(name)}.pdf")
        result("Variant 1 - Free Ravelry pattern", ok, msg)
    else:
        result("Variant 1", False, "No download_location.url found.")
    time.sleep(0.3)


# ══════════════════════════════════════════════════════════════════════════
# VARIANT 2 - Paid Ravelry pattern (from your own library)
# ══════════════════════════════════════════════════════════════════════════
section("2 · Paid Ravelry pattern (library)")

# IMPORTANT: library/search.json ALWAYS returns "volume" objects - even for
# individually purchased patterns (Ravelry internally creates a 1:1 volume
# for that). The relevant fields are:
#   id                 -> volume ID (for /volumes/{id}.json)
#   pattern_id         -> real pattern ID (for /patterns/{id}.json), or null
#   pattern_source_id  -> set for collections/issues, otherwise null
#   patterns_count     -> >1 means a collection
#   has_downloads      -> whether any PDFs are attached at all
lib_data = api_get(f"/people/{me}/library/search.json", {"page_size": 100})
all_volumes = lib_data.get("volumes", [])
paginator = lib_data.get("paginator", {})

print(f"  Library entries (page 1): {len(all_volumes)} volumes "
      f"(total: {paginator.get('results')})")

# Individual pattern = patterns_count == 1 AND pattern_id set
paid_pattern_found = False
for item in all_volumes:
    pid = item.get("pattern_id")
    if not pid or item.get("patterns_count", 1) != 1:
        continue  # not an individual pattern entry (but a collection or similar)

    detail = api_get(f"/patterns/{pid}.json").get("pattern", {})
    if not detail.get("ravelry_download") or detail.get("free"):
        continue  # we're explicitly looking for a PAID pattern

    name = detail.get("name", f"pattern_{pid}")
    print(f"  Pattern: {name!r}  (pattern ID {pid}, volume ID {item.get('id')})")
    dump("Pattern fields (excerpt)", {
        "ravelry_download": detail.get("ravelry_download"),
        "free": detail.get("free"),
        "pdf_in_library": detail.get("pdf_in_library"),
        "volumes_in_library": detail.get("volumes_in_library"),
        "download_location": detail.get("download_location"),
    })

    # IMPORTANT: download_location.url is a PURCHASE/CHECKOUT URL (for
    # buying a pattern), NOT a download URL for already purchased
    # content! If the pattern is already in the library
    # (pdf_in_library=true), the PDF download has to go through the
    # associated volume (as in variants 3/4): volumes_in_library ->
    # /volumes/{id}.json -> volume_attachments[].ravelry_download_url.
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
        result("Variant 2 - Paid Ravelry pattern", ok, msg)
    else:
        result("Variant 2", False,
               "Pattern found with neither volumes_in_library nor a download URL.")
    paid_pattern_found = True
    time.sleep(0.3)
    break  # only the first one

if not paid_pattern_found:
    result("Variant 2", False,
           "No paid individual pattern found in the library.")


# ══════════════════════════════════════════════════════════════════════════
# VARIANT 3 - PDF from the library (library/search, first result overall)
# ══════════════════════════════════════════════════════════════════════════
section("3 · First library entry overall (library/search without a filter)")

# The summary objects from library/search contain NO volume_attachments -
# those only appear in the details under /volumes/{id}.json.
first_item = all_volumes[0] if all_volumes else None

if not first_item:
    result("Variant 3", False, "Library is empty.")
else:
    print(f"  Summary keys: {list(first_item.keys())}")
    dump("First library entry (summary)", first_item)

    vol_id = first_item.get("id")
    vol_detail = api_get(f"/volumes/{vol_id}.json").get("volume", {})
    attachments = vol_detail.get("volume_attachments", [])
    dump("Volume details: volume_attachments (filenames)",
         [a.get("filename") for a in attachments])

    url, filename = None, None
    if attachments:
        att = attachments[0]
        url = att.get("ravelry_download_url")
        filename = att.get("filename") or f"03_library_{vol_id}.pdf"

    if url:
        ok, msg = save_pdf(url, f"03_library_{sanitize_filename(filename)}")
        result("Variant 3 - Library entry", ok, msg)
    else:
        result("Variant 3", False, "No download URL found in this entry.")
    time.sleep(0.3)


# ══════════════════════════════════════════════════════════════════════════
# VARIANT 4 - eBook / Volume (book with a PDF attachment)
# ══════════════════════════════════════════════════════════════════════════
section("4 · eBook / Volume (type=pdf)")

pdf_lib = api_get(f"/people/{me}/library/search.json", {
    "page_size": 1,
    "type": "pdf",
})
pdf_volumes = pdf_lib.get("volumes", [])

if not pdf_volumes:
    result("Variant 4", False, "No volumes found in the library.")
else:
    vol_id    = pdf_volumes[0]["id"]
    vol_title = pdf_volumes[0].get("title", f"Volume_{vol_id}")
    print(f"  Volume: {vol_title!r}  (ID {vol_id})")

    vol_detail = api_get(f"/volumes/{vol_id}.json")["volume"]
    attachments = vol_detail.get("volume_attachments", [])

    dump("Volume fields (excerpt)", {
        "id": vol_detail.get("id"),
        "title": vol_detail.get("title"),
        "volume_attachments": [
            {k: v for k, v in a.items() if k != "ravelry_download_url"}
            for a in attachments
        ],
    })

    if not attachments:
        result("Variant 4", False, "Volume has no PDF attachments.")
    else:
        att = attachments[0]
        url = att.get("ravelry_download_url")
        filename = att.get("filename") or f"04_ebook_{sanitize_filename(vol_title)}.pdf"
        if url:
            ok, msg = save_pdf(url, f"04_ebook_{sanitize_filename(filename)}")
            result("Variant 4 - eBook/Volume", ok, msg)
        else:
            result("Variant 4", False, "ravelry_download_url missing from attachment.")
    time.sleep(0.3)


# ══════════════════════════════════════════════════════════════════════════
# VARIANT 5 - Collection (multiple patterns in one issue/eBook, own library)
# ══════════════════════════════════════════════════════════════════════════
section("5 · Collection (patterns_count > 1, own library)")

# A collection is recognized in your own library by patterns_count > 1 AND
# has_downloads=True. pattern_sources/search.json does return collections,
# but has NO volume_id field - so it's not directly linked to its own PDF.
# Hence: search via your own library (where the download is guaranteed).
collection_item = next(
    (v for v in all_volumes
     if v.get("patterns_count", 1) > 1 and v.get("has_downloads")),
    None,
)

if not collection_item:
    result("Variant 5", False,
           "No collection (patterns_count>1) with downloads found in the library.")
else:
    vol_id = collection_item.get("id")
    title  = collection_item.get("title", f"Collection_{vol_id}")
    print(f"  Collection: {title!r}  (volume ID {vol_id}, "
          f"{collection_item.get('patterns_count')} patterns)")

    vol_detail  = api_get(f"/volumes/{vol_id}.json").get("volume", {})
    attachments = vol_detail.get("volume_attachments", [])
    dump("Collection attachments (filenames)",
         [a.get("filename") for a in attachments])

    if not attachments:
        result("Variant 5", False, "Collection volume has no PDF attachments.")
    else:
        att = attachments[0]
        url = att.get("ravelry_download_url")
        filename = att.get("filename") or f"05_collection_{sanitize_filename(title)}.pdf"
        if url:
            ok, msg = save_pdf(url, f"05_collection_{sanitize_filename(filename)}")
            result("Variant 5 - Collection", ok, msg)
        else:
            result("Variant 5", False, "ravelry_download_url missing from attachment.")
    time.sleep(0.3)


# ══════════════════════════════════════════════════════════════════════════
# VARIANT 6 - Bundle (multiple individual patterns purchased together)
# ══════════════════════════════════════════════════════════════════════════
section("6 · Bundle (multiple individual patterns in the same purchase)")

# A bundle purchase (e.g. a designer package with multiple patterns)
# creates its OWN volume per pattern with its own pattern_id, but all with
# the same created_at timestamp (= same checkout). patterns_count is 1 for
# each individual entry - that's what distinguishes it from a "collection"
# (variant 5, ONE volume with patterns_count > 1).
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
    result("Variant 6", False,
           "No group of individual patterns with an identical purchase timestamp found.")
else:
    print(f"  Bundle found: {len(bundle_group)} pattern(s) with timestamp "
          f"{bundle_group[0].get('created_at')}")
    dump("Bundle members", [
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
        result(f"Variant 6 - Bundle part: {first.get('title')!r}", ok, msg)
    else:
        result("Variant 6", False, "First bundle pattern has no PDF attachment.")
    time.sleep(0.3)


# ══════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════
print(f"\n{'═' * 60}")
print(f"  Downloads saved to: {os.path.abspath(TEST_DIR)}/")
for f in sorted(os.listdir(TEST_DIR)):
    size = os.path.getsize(os.path.join(TEST_DIR, f)) // 1024
    print(f"    {f}  ({size} KB)")
print('═' * 60)
