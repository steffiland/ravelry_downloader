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
Downloads all PDFs from your own Ravelry library:

  1. Volumes (books, magazines, collections with their own PDF bundle):
     → library/search.json?type=pdf → volumes[].volume_attachments[].ravelry_download_url

  2. Individually purchased Ravelry patterns:
     → library/search.json (no type filter) → items with pattern_id, patterns_count==1
       → /patterns/{id}.json → volumes_in_library → volume_attachments[].ravelry_download_url

  3. Reference collections (patterns_count > 1, but has_downloads=False):
     These are collections WITHOUT their own bundled PDF - the members are
     instead individually linked patterns (usually free Ravelry downloads,
     e.g. Scheepjes "YARN - The After Party"). These are listed via
     /pattern_sources/{id}/patterns.json and downloaded individually.

CONTROLLED BY TWO SEPARATE FILES (with different logic!):

  ravelry_downloads/ignore.txt - EXCLUDE logic, applies to ALL downloads
    One line = substring filter against the target FILENAME. Everything is
    downloaded EXCEPT what's listed here (e.g. '_NL.pdf' for Dutch
    versions). Applies everywhere - including files within a reference
    collection activated via collections.txt.

  ravelry_downloads/collections.txt - INCLUDE logic, only for variant 3
    One line = 'collection:<id-or-partial-title>'. Only ACTIVE (not
    commented out) lines enable the download of that collection:
      collection:213142                 <- ACTIVE, will be downloaded
      #collection:213142                 <- INACTIVE (default for new finds)
    To activate, simply remove the leading '#'. Newly found collections
    are automatically appended as INACTIVE on every run, so this file
    always builds a complete, searchable catalog of ALL reference
    collections ever found, for review - without anything being
    downloaded by accident. The script remembers which IDs have already
    been added to the catalog in ravelry_downloads/.collection_sync.json,
    so a collection that is already known doesn't get appended again on
    the next run (regardless of whether you left it activated or
    deactivated).

PROCESSING ORDER (main()):
  Step 1: Volumes with their own PDF bundle (process_volumes)
  Step 2: Individually purchased patterns (process_individual_patterns)
  Step 3: Reference collections, members downloaded individually (process_reference_collections)
  Step 4: Transparency report for items without a download path (report_unhandled_items)
  Step 5: Log of entries filtered by ignore.txt (write_excluded_log)
  Within each stage, processing follows the order in which the Ravelry API
  paginates the library entries (this script doesn't apply its own sort
  order).

LOG FILES (overwritten on EVERY run, so they show the state of the last
run, not a cumulative history across multiple runs):
  - ravelry_downloads/skipped_non_downloadable.txt
    Library entries without a recognizable download path (step 4).
  - ravelry_downloads/excluded_by_ignore.txt
    Files/collections that were NOT downloaded in THIS run due to
    ignore.txt or collections.txt (step 5). A pure log, not a control
    mechanism - edit ignore.txt/collections.txt directly to change
    behavior.

PAID DOWNLOADS:
----------------
Their URLs require a logged-in browser session instead of the REST API
keys. If a download attempt returns an HTML login page instead of a PDF,
this script automatically opens a visible browser (Playwright) for manual
login - see ravelry_common.ensure_browser_login(). The session is then
cached locally (.ravelry_session.json), so later runs don't need to log
in again.
"""

import argparse
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

# Log files (overwritten on EVERY run, so they always show the state of
# the last run - not a control mechanism, just transparency):
#   - SKIPPED_REPORT_FILE: library entries without a recognizable download
#     path (see report_unhandled_items())
#   - EXCLUDED_LOG_FILE:   files/collections that were NOT downloaded in
#     this run (via ignore.txt OR collections.txt)
SKIPPED_REPORT_FILE = os.path.join(DOWNLOAD_DIR, "skipped_non_downloadable.txt")
EXCLUDED_LOG_FILE   = os.path.join(DOWNLOAD_DIR, "excluded_by_ignore.txt")

# Browser cookies are fetched lazily (only when needed) and then reused for
# the rest of the run, so there's no need to log in again for every file.
browser_cookies: dict | None = None

# Dry-run mode (--dry-run): try_download() then performs NO real download
# (no network GET on the PDF URL, no browser login), and only reports
# whether the file would be downloaded OR filtered by ignore.txt. All other
# steps (querying the library, evaluating ignore.txt/collections.txt,
# fetching the real filenames from the Ravelry "choose file" page for
# multi-file patterns) run unchanged, so the preview shows exactly the
# filenames that ignore.txt actually gets to see - for a safe review of
# your own ignore.txt.
dry_run: bool = False

# Collects all filenames/titles not downloaded in this run, written out at
# the end of main() as EXCLUDED_LOG_FILE (see write_excluded_log()).
# Module-global state, analogous to browser_cookies.
excluded_this_run: list[str] = []


# ---------------------------------------------------------------------------
# ignore.txt - filename filter (EXCLUDE logic, applies to ALL downloads)
# ---------------------------------------------------------------------------

def load_ignore_patterns(ignore_filepath: str) -> list[str]:
    """
    Loads filename ignore patterns from ignore.txt.
    Creates an example file if none exists yet.

    EXCLUDE logic: one line = substring filter against the target
    FILENAME. Everything is downloaded EXCEPT what's listed here. Applies
    to EVERY download (volumes, individual patterns, AND files within a
    reference collection activated via collections.txt).
    """
    if not os.path.exists(ignore_filepath):
        os.makedirs(os.path.dirname(ignore_filepath), exist_ok=True)
        default_content = (
            "# List filenames or name fragments here that should NOT be\n"
            "# downloaded. Lines starting with '#' are comments.\n"
            "# Applies to ALL downloads, including within activated collections\n"
            "# (see collections.txt).\n"
            "#\n"
            "# Examples for language exclusions:\n"
            "# _NL.pdf\n"
            "# _FR.pdf\n"
            "# _ES.pdf\n"
            "# _IT.pdf\n"
            "# _RU.pdf\n"
        )
        with open(ignore_filepath, "w", encoding="utf-8") as f:
            f.write(default_content)
        print(f"ℹ️  New ignore file created: '{ignore_filepath}'")
        return []

    filename_patterns = []
    with open(ignore_filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Strip inline comments
            line_without_comment = line.split("#", 1)[0].strip()
            if line_without_comment:
                filename_patterns.append(line_without_comment.lower())

    if filename_patterns:
        print(f"ℹ️  Loaded {len(filename_patterns)} filename ignore pattern(s) from '{ignore_filepath}'.")
    return filename_patterns


def is_ignored(filename: str, ignore_patterns: list[str]) -> bool:
    """Checks whether a filename matches any of the ignore patterns."""
    filename_lower = filename.lower()
    return any(p in filename_lower for p in ignore_patterns)


# ---------------------------------------------------------------------------
# collections.txt - reference collection opt-in (INCLUDE logic)
# ---------------------------------------------------------------------------

def load_collection_includes(collections_filepath: str) -> list[str]:
    """
    Loads the list of ACTIVE collection opt-ins from collections.txt.
    Creates an example file if none exists yet.

    INCLUDE logic: the default is to NOT download. Only an ACTIVE line
    (without a leading '#') enables the download of that collection:
      collection:213142                 <- ACTIVE, will be downloaded
      #collection:213142                 <- INACTIVE (default for new finds)
    <id-or-partial-title> = pattern_source_id OR part of the title.
    """
    if not os.path.exists(collections_filepath):
        os.makedirs(os.path.dirname(collections_filepath), exist_ok=True)
        default_content = (
            "# Reference collections (patterns_count>1 without their own PDF\n"
            "# bundle, e.g. Scheepjes 'YARN - The After Party') are collected\n"
            "# here as a catalog. The default is to NOT download (INCLUDE\n"
            "# logic) - only an ACTIVE line (without a leading '#') enables\n"
            "# the download:\n"
            "#\n"
            "#   collection:213142                 <- ACTIVE, will be downloaded\n"
            "#   #collection:213142                 <- inactive (default)\n"
            "#\n"
            "# To activate, simply remove the leading '#' before the line.\n"
            "# <value> = pattern_source_id OR part of the title, e.g.:\n"
            "#   collection:Yarn - The After Party\n"
        )
        with open(collections_filepath, "w", encoding="utf-8") as f:
            f.write(default_content)
        print(f"ℹ️  New collections file created: '{collections_filepath}'")
        return []

    collection_includes = []
    with open(collections_filepath, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue

            # Strip the leading '#' to distinguish ACTIVE ('collection:...')
            # from INACTIVE ('#collection:...'). Lines that don't start with
            # 'collection:' AFTER stripping are pure comments.
            stripped_hash = line.lstrip("#").strip()
            if not stripped_hash.lower().startswith("collection:"):
                continue  # pure comment

            is_active = not line.startswith("#")
            if not is_active:
                continue

            # Strip inline comment: 'collection:213142  # Title'
            value = stripped_hash.split(":", 1)[1]
            value = value.split("#", 1)[0].strip().lower()
            if value:
                collection_includes.append(value)

    if collection_includes:
        print(f"ℹ️  Loaded {len(collection_includes)} active collection opt-in(s) from "
              f"'{collections_filepath}'.")
    return collection_includes


def is_collection_included(collection_item: dict, collection_includes: list[str]) -> bool:
    """
    Checks whether a reference collection has been enabled for download
    via an ACTIVE 'collection:<id-or-title>' line in collections.txt
    (INCLUDE logic: the default is to NOT download, only explicitly
    activated collections are downloaded).
    """
    src_id = str(collection_item.get("pattern_source_id", "")).lower()
    title  = (collection_item.get("title") or "").lower()
    return any(incl == src_id or incl in title for incl in collection_includes)


def load_synced_collection_ids() -> set[int]:
    """Loads the set of pattern_source_ids that have already been
    automatically added to collections.txt once before (see
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
    Automatically appends NEW reference collections (never seen before) as
    INACTIVE '#collection:<id>  # <title> (<n> patterns)' lines to
    collections.txt. This builds a complete, searchable catalog list for
    review, without anything being downloaded by accident. To activate,
    simply remove the leading '#'.

    IDs already added to the catalog are remembered in COLLECTION_SYNC_FILE,
    so a known collection doesn't get appended again on the next run -
    regardless of whether you've since activated or left it deactivated.
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
        f"# {c.get('title', 'Untitled')} ({c.get('patterns_count', '?')} patterns)"
        for c in new_ones
    ]
    header = (
        f"\n# --- Automatically added on {time.strftime('%Y-%m-%d %H:%M')} "
        f"({len(new_ones)} new reference collection(s)) ---\n"
        "# Inactive by default. Remove the leading '#' to make the "
        "collection WILL be downloaded.\n"
    )
    with open(COLLECTIONS_FILE, "a", encoding="utf-8") as f:
        f.write(header + "\n".join(lines) + "\n")

    already_synced.update(c["pattern_source_id"] for c in new_ones)
    save_synced_collection_ids(already_synced)

    print(f"ℹ️  Added {len(new_ones)} new reference collection(s) automatically (inactive) to "
          f"'{COLLECTIONS_FILE}'.")


# ---------------------------------------------------------------------------
# General helper functions
# ---------------------------------------------------------------------------

def ensure_download_dir():
    """Ensures the download directory exists (symlink-safe)."""
    if os.path.islink(DOWNLOAD_DIR):
        real_target = os.path.realpath(DOWNLOAD_DIR)
        if not os.path.exists(real_target):
            raise FileNotFoundError(
                f"Symlink '{DOWNLOAD_DIR}' points to a non-existent folder: '{real_target}'"
            )
    else:
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def try_download(url: str, filename: str, label: str, ignore_patterns: list[str]) -> str:
    """
    Central download helper with automatic browser-login fallback.
    Returns: 'downloaded', 'skipped_exists', 'skipped_ignore', 'error'

    is_ignored() (ignore.txt) is checked here for EVERY download, including
    files within a reference collection activated via collections.txt -
    the two mechanisms are independent and both apply.

    In dry-run mode (see module-global `dry_run`), NOTHING is downloaded
    (no network GET, no browser login) - it only reports whether the file
    would be downloaded OR filtered by ignore.txt. 'downloaded' in dry-run
    mode thus means "would be downloaded", not "was downloaded".
    """
    global browser_cookies

    clean_name = sanitize_filename(filename)
    if not clean_name.lower().endswith(".pdf"):
        clean_name += ".pdf"

    if is_ignored(clean_name, ignore_patterns):
        print(f"  🚫 {'Would filter' if dry_run else 'Filtered'} (ignore.txt): {clean_name}")
        excluded_this_run.append(f"{clean_name}  (file filter, {label})")
        return "skipped_ignore"

    target_path = os.path.join(DOWNLOAD_DIR, clean_name)
    if os.path.exists(target_path):
        print(f"  ➜  Already present: {clean_name}")
        return "skipped_exists"

    if dry_run:
        print(f"  ✅ Would download ({label}): {clean_name}")
        return "downloaded"

    print(f"  ⬇️  Downloading ({label}): {clean_name}")
    ok, msg, browser_cookies = download_with_login_fallback(url, target_path, browser_cookies)
    if ok:
        time.sleep(0.3)
        return "downloaded"
    else:
        print(f"  ❌ Error: {msg}")
        return "error"


# ---------------------------------------------------------------------------
# 1. VOLUMES (books, magazines, collections with their own PDF attachment)
# ---------------------------------------------------------------------------

def fetch_library_volumes(username: str) -> list:
    """Fetches all volume entries from the library (type=pdf)."""
    volumes = []
    page = 1
    print("📚 Loading library (volumes/books) …")
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

    print(f"  → Found {len(volumes)} volume(s).\n")
    return volumes


def process_volumes(volumes: list, ignore_patterns: list[str]) -> dict:
    """Processes volumes and downloads their associated PDFs."""
    stats = {"downloaded": 0, "skipped_exists": 0, "skipped_ignore": 0, "error": 0}

    for idx, vol_summary in enumerate(volumes, start=1):
        vol_id = vol_summary.get("id")
        title  = vol_summary.get("title") or f"Volume_{vol_id}"
        print(f"[{idx}/{len(volumes)}] Volume: {title}")

        try:
            vol_data = api_get(f"/volumes/{vol_id}.json").get("volume", {})
        except Exception as e:
            print(f"  ⚠️  Could not load details ({e})")
            continue

        attachments = vol_data.get("volume_attachments", [])

        if not attachments:
            print("  ℹ️  No PDF attachments.")
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
# 2. INDIVIDUALLY PURCHASED PATTERNS (ravelry_download)
# ---------------------------------------------------------------------------

def fetch_library_patterns(username: str) -> list:
    """
    Fetches all library entries (without a type filter), to filter out
    individual patterns from them (patterns_count == 1, pattern_id set).
    """
    all_items = []
    page = 1
    print("🧶 Loading library (individual patterns) …")
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

    print(f"  → {len(all_items)} total entries in the library.\n")
    return all_items


def get_pattern_download_url(pattern_id: int) -> tuple[str | None, str | None]:
    """
    Gets the download URL for an already purchased individual pattern.

    IMPORTANT: pattern.download_location.url is a PURCHASE/CHECKOUT URL
    (for buying), NOT a download URL for already purchased content! If the
    pattern is already in the library (pdf_in_library=true), the PDF
    download goes through the associated volume: volumes_in_library ->
    /volumes/{id}.json -> volume_attachments[].ravelry_download_url.

    Returns (url, filename), or (None, None) if no download is available.
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
    Filters out individual patterns from the library items (patterns_count
    == 1, pattern_id set) and downloads their PDFs. Volumes with their own
    volume_attachments were already handled in process_volumes.
    """
    stats = {"downloaded": 0, "skipped_exists": 0, "skipped_ignore": 0, "error": 0}

    candidates = sorted({
        item["pattern_id"]
        for item in items
        if item.get("pattern_id") and item.get("patterns_count", 1) == 1
    })

    print(f"  → {len(candidates)} possible individual pattern(s) to check.\n")

    for idx, pid in enumerate(candidates, start=1):
        print(f"[{idx}/{len(candidates)}] Checking pattern ID {pid} …")
        url, filename = get_pattern_download_url(pid)
        if not url:
            print("  ℹ️  No Ravelry download available.")
            continue
        result = try_download(url, filename, "Pattern", ignore_patterns)
        stats[result] = stats.get(result, 0) + 1

    return stats


# ---------------------------------------------------------------------------
# 3. REFERENCE COLLECTIONS (patterns_count > 1, but has_downloads=False)
# ---------------------------------------------------------------------------
#
# Some collections don't bundle their own PDF, but instead only reference
# multiple individually linked patterns (often free Ravelry downloads, e.g.
# yarn manufacturer collections like Scheepjes "YARN - The After Party").
# Such collections are listed via /pattern_sources/{id}/patterns.json;
# each contained pattern is then treated like a normal individual pattern
# (same download path as in variant 2).

def find_reference_collections(items: list) -> list[dict]:
    """Filters out library items that are reference collections
    (patterns_count>1, has_downloads=False) - i.e. they have NO own PDF
    bundle."""
    return [
        item for item in items
        if item.get("patterns_count", 1) > 1 and not item.get("has_downloads")
    ]


# ---------------------------------------------------------------------------
# 4. UNHANDLED ENTRIES (transparency report, no download attempt)
# ---------------------------------------------------------------------------
#
# Not every library entry fits into one of the three download schemes
# above. Observed cases include:
#   - 'single_pattern_source': pattern_source_id set, patterns_count==1,
#     but NO pattern_id (e.g. single magazine issues like "Star Book
#     No. 169" or "Filati Häkeln 02"). Verified via a live query: the
#     linked pattern has neither ravelry_download nor download_location
#     -> not technically downloadable.
#   - 'orphan': neither pattern_id nor pattern_source_id set (e.g.
#     "Noctiluca Dress", a pattern purchased on Etsy, or "Crochet Every
#     Way Stitch Dictionary", a pure reference work with no individual
#     PDF).
#
# These items are confirmed to be externally acquired and INTENTIONALLY
# NOT downloaded (serve only as a searchable reference in the library, see
# docs/ravelry-api-kb.md). Instead of silently swallowing them, they are
# explicitly detected and logged/reported here, so that nothing
# "disappears" without being traceable.

def categorize_item(item: dict) -> str:
    """
    Assigns a library entry to exactly one category:
      - 'volume_bundle'         : has_downloads=True -> own PDF bundle
                                   (handled by process_volumes)
      - 'individual_pattern'    : pattern_id set, patterns_count==1,
                                   has_downloads=False (process_individual_patterns)
      - 'reference_collection'  : patterns_count>1, has_downloads=False
                                   (process_reference_collections)
      - 'single_pattern_source' : pattern_source_id set, patterns_count==1,
                                   no pattern_id -> usually externally
                                   acquired single magazine issues, not
                                   downloadable
      - 'orphan'                : neither pattern_id nor pattern_source_id ->
                                   usually externally acquired
                                   patterns/books, in the library only for
                                   research purposes
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
    """Items that land in NONE of the three download paths
    (single_pattern_source, orphan) - deliberately not downloaded, see the
    module comment above."""
    return [
        item for item in items
        if categorize_item(item) in ("single_pattern_source", "orphan")
    ]


def report_unhandled_items(items: list) -> None:
    """
    Logs all unhandled items (see find_unhandled_items) and writes the
    complete list to a report file under DOWNLOAD_DIR. Downloads NOTHING -
    pure transparency, so nothing silently disappears.
    """
    unhandled = find_unhandled_items(items)
    if not unhandled:
        return

    print(f"\nℹ️  {len(unhandled)} library entry/entries without a download path "
          f"(typically externally acquired, in the library for research purposes only):")
    for item in unhandled[:10]:
        print(f"    - {item.get('title', 'Untitled')!r}")
    if len(unhandled) > 10:
        print(f"    … and {len(unhandled) - 10} more (see the report file for the full list).")

    try:
        with open(SKIPPED_REPORT_FILE, "w", encoding="utf-8") as f:
            f.write(
                "# Library entries without a recognizable Ravelry download path.\n"
                "# This file is overwritten on every run - a pure report,\n"
                "# NOT a control mechanism (unlike ignore.txt/collections.txt).\n"
                "# Typically externally acquired patterns/magazines that were\n"
                "# only added to the library for research purposes.\n\n"
            )
            for item in unhandled:
                f.write(f"{item.get('title', 'Untitled')}\n")
        print(f"    → Full list: {SKIPPED_REPORT_FILE}")
    except OSError as e:
        print(f"    ⚠️  Could not write report: {e}")


def write_excluded_log() -> None:
    """
    Writes all entries not downloaded in this run (either via ignore.txt OR
    due to missing opt-in in collections.txt) to EXCLUDED_LOG_FILE.
    Overwritten on EVERY run - so it only shows what was actively filtered
    in the LAST run (not cumulative across multiple runs).
    """
    if not excluded_this_run:
        return

    try:
        with open(EXCLUDED_LOG_FILE, "w", encoding="utf-8") as f:
            f.write(
                "# Entries not downloaded (last run).\n"
                "# This file is overwritten on every run - a pure log,\n"
                "# edit ignore.txt or collections.txt directly to change behavior.\n\n"
            )
            for entry in excluded_this_run:
                f.write(f"{entry}\n")
        print(f"\nℹ️  Logged {len(excluded_this_run)} entries not downloaded: "
              f"{EXCLUDED_LOG_FILE}")
    except OSError as e:
        print(f"⚠️  Could not write excluded log: {e}")


def process_reference_collections(
    collections: list[dict],
    ignore_patterns: list[str],
    collection_includes: list[str],
) -> dict:
    """
    For each reference collection ACTIVATED via collections.txt, downloads
    all contained patterns individually (as long as they offer
    ravelry_download, e.g. are free). Collections that aren't activated are
    skipped and added to the excluded log.
    """
    stats = {"downloaded": 0, "skipped_exists": 0, "skipped_ignore": 0, "error": 0}

    for col in collections:
        src_id = col.get("pattern_source_id")
        title  = col.get("title") or f"Collection_{src_id}"

        if not is_collection_included(col, collection_includes):
            print(f"🚫 Collection not activated (collections.txt): {title!r} (source_id={src_id})")
            excluded_this_run.append(
                f"{title}  (collection not activated, source_id={src_id}, "
                f"{col.get('patterns_count', '?')} patterns)"
            )
            continue

        print(f"\n📖 Reference collection: {title!r}  ({col.get('patterns_count')} patterns, "
              f"source_id={src_id})")

        # Fetch all patterns from this source (paginated)
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

        print(f"  → Found {len(src_patterns)} pattern(s) in this collection.")

        for idx, p in enumerate(src_patterns, start=1):
            pid = p.get("id")
            name = p.get("name", f"pattern_{pid}")
            print(f"  [{idx}/{len(src_patterns)}] {name!r} …")

            # Fetch full pattern details (the summary from pattern_sources
            # has no download_location/ravelry_download field)
            try:
                detail = api_get(f"/patterns/{pid}.json").get("pattern", {})
            except Exception as e:
                print(f"    ⚠️  Could not load details ({e})")
                stats["error"] += 1
                continue

            if not detail.get("ravelry_download"):
                print("    ℹ️  No Ravelry download available (external source).")
                continue

            # Already purchased/in library? -> download via volume (like variant 2)
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
                    print("    ℹ️  No download URL found.")
                    continue
                result = try_download(url, filename, "Collection-Pattern", ignore_patterns)
                stats[result] = stats.get(result, 0) + 1
                continue

            # Not in library, but ravelry_download=true -> usually free,
            # download_location.url is then the direct /dls/ download link.
            loc = detail.get("download_location")
            if isinstance(loc, dict):
                loc = [loc]
            url = next((l["url"] for l in (loc or []) if l.get("url")), None)

            if not url:
                print("    ℹ️  No download URL found.")
                continue

            # A pattern with MULTIPLE files returns a "choose file" page
            # instead of a PDF for the /dls/ URL, with one link per file.
            # This isn't limited to language translations (which are very
            # common for reference collections like Scheepjes "YARN - The
            # After Party"), but also includes, e.g., "Easy Read" versions,
            # separate knitting charts, or print-friendly editions. Each of
            # these files is downloaded individually via try_download(), so
            # that ignore.txt (which already maintains quite a few language
            # exclusions like _NL.pdf/_FR.pdf/_KR.pdf and can be extended
            # with other variant exclusions as needed) applies here just
            # like for any other download - NO preference hardcoded in the
            # code.
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

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Downloads all PDFs from your own Ravelry library."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Simulates the run without downloading anything (no network "
            "GET on PDF URLs, no browser login). For each file, only shows "
            "whether it would be downloaded or filtered by ignore.txt - for "
            "a safe review of your own ignore.txt. collections.txt is NOT "
            "modified in this mode (new collections are not added "
            "automatically); the report files "
            "skipped_non_downloadable.txt/excluded_by_ignore.txt are still "
            "written, since they are pure logs with no control effect."
        ),
    )
    return parser.parse_args()


def main():
    global dry_run
    args = parse_args()
    dry_run = args.dry_run

    excluded_this_run.clear()  # the log should only show the current run
    ensure_download_dir()
    ignore_patterns = load_ignore_patterns(IGNORE_FILE)
    username = get_current_username()
    print(f"👤 Logged in as: {username}")
    if dry_run:
        print("🧪 DRY RUN: NOTHING will be downloaded, only simulated.\n")
    else:
        print()

    total_stats = {"downloaded": 0, "skipped_exists": 0, "skipped_ignore": 0, "error": 0}

    # --- Step 1: Volumes (eBooks, collections with their own PDF bundle) ---
    volumes = fetch_library_volumes(username)
    if volumes:
        stats = process_volumes(volumes, ignore_patterns)
        for k, v in stats.items():
            total_stats[k] += v
        print()

    # --- Step 2: Individually purchased patterns ---
    all_items = fetch_library_patterns(username)
    if all_items:
        stats = process_individual_patterns(all_items, ignore_patterns)
        for k, v in stats.items():
            total_stats[k] += v

    # --- Step 3: Reference collections (without their own PDF bundle) ---
    if all_items:
        reference_collections = find_reference_collections(all_items)
        if reference_collections:
            print(f"\n📚 Found {len(reference_collections)} reference collection(s) "
                  f"(without their own PDF bundle, members individually linked).")

            # Automatically add new collections (inactive) to collections.txt,
            # then re-read the opt-in list (now includes the fresh entries).
            # In dry-run mode, collections.txt is NOT modified (that would be
            # a real mutation of a manually maintained control file) - a
            # newly found, still unknown collection then simply shows up as
            # "not activated" in the preview, instead of being added
            # automatically.
            if not dry_run:
                sync_new_reference_collections(reference_collections)
            collection_includes = load_collection_includes(COLLECTIONS_FILE)

            stats = process_reference_collections(
                reference_collections, ignore_patterns, collection_includes
            )
            for k, v in stats.items():
                total_stats[k] += v

    # --- Step 4: Transparency report for unprocessable entries ---
    if all_items:
        report_unhandled_items(all_items)

    # --- Step 5: Log of entries not downloaded ---
    write_excluded_log()

    # --- Summary ---
    print("\n" + "=" * 50)
    print("✅ DRY RUN DONE (nothing was downloaded)" if dry_run else "✅ DONE")
    label_downloaded = "Would download" if dry_run else "Newly downloaded"
    label_ignored = "Would filter" if dry_run else "Not downloaded"
    print(f"  ⬇️  {label_downloaded:22}: {total_stats['downloaded']}")
    print(f"  ➜   Already present   : {total_stats['skipped_exists']}")
    print(f"  🚫  {label_ignored:22}: {total_stats['skipped_ignore']}")
    print(f"  ❌  Errors             : {total_stats['error']}")
    print("=" * 50)


if __name__ == "__main__":
    main()
