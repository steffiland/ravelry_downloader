"""
Ravelry Common Helper
======================
Shared functions used by all ravelry-*.py scripts:

  - REST API access (Basic Auth with ACCESS_KEY/PERSONAL_KEY)
  - PDF downloads including validation (signature/content-type check)
  - Browser-based Ravelry login via Playwright, for downloads that
    require a logged-in browser session instead of API keys
    (paid patterns/eBooks/collections/bundles, see
    docs/ravelry-api-kb.md section 10/11)

Session cookies are cached in .ravelry_session.json after a successful
login (see .gitignore), so you don't have to log in again on every run.

This module is NOT a standalone script - it is imported by the other
ravelry-*.py files.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote

import requests
from dotenv import load_dotenv

load_dotenv()

ACCESS_KEY   = os.getenv("RAVELRY_ACCESS_KEY")
PERSONAL_KEY = os.getenv("RAVELRY_PERSONAL_KEY")

if not ACCESS_KEY or not PERSONAL_KEY:
    sys.exit("❌ RAVELRY_ACCESS_KEY or RAVELRY_PERSONAL_KEY is missing from the .env file!")

BASE_URL = "https://api.ravelry.com"
AUTH     = (ACCESS_KEY, PERSONAL_KEY)

SESSION_FILE = Path(__file__).parent / ".ravelry_session.json"
LOGIN_URL    = "https://www.ravelry.com/account/login"


# ── REST API ────────────────────────────────────────────────────────────────

def api_get(path: str, params: dict | None = None) -> dict:
    """GET against the Ravelry REST API with Basic Auth (ACCESS_KEY/PERSONAL_KEY)."""
    r = requests.get(f"{BASE_URL}{path}", auth=AUTH, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def get_current_username() -> str:
    """Determines the username of the API key owner."""
    return api_get("/current_user.json")["user"]["username"]


# ── Filenames / Downloads ────────────────────────────────────────────────────

def sanitize_filename(filename: str) -> str:
    """Strips characters from a filename that filesystems don't like."""
    return re.sub(r'[\\/*?:"<>|]', "_", filename)


def _is_pdf_response(content_type: str, first_chunk: bytes) -> bool:
    return first_chunk.startswith(b"%PDF-") or "pdf" in content_type.lower()


# Direct file download links on a Ravelry "choose file" intermediate page,
# e.g. <a href="https://www.ravelry.com/dl/scheepjes/827394?filename=....pdf">
_DL_LINK_RE = re.compile(r'href="(https?://www\.ravelry\.com/dl/[^"]+)"')


def _parse_chooser_links(html: str) -> list[tuple[str, str]]:
    """
    Parses a Ravelry "choose file" intermediate page and returns a list of
    (filename, download_url) tuples - one per file found, in the order they
    appear on the page. filename is the REAL Ravelry filename (from the
    `filename=` query parameter, URL-decoded, e.g.
    "30.__NL__Alto_Mare_Wrap.pdf") - so that downstream callers can apply the
    usual ignore.txt filtering (is_ignored) per file, instead of hardcoding
    a preference for any particular variant in the code.

    Background: `download_location.url` (or the derived `/dls/{id}/{code}`
    URL) returns the PDF directly for a pattern with ONLY ONE file. But if
    the pattern has multiple files, the same URL instead returns an HTML page
    with one `/dl/{company}/{id}?filename=...` link per file. "Multiple
    files" is NOT limited to language translations (which are the most
    common case for reference collections like Scheepjes "YARN - The After
    Party") - there are also, for example, "Easy Read" versions, knitting
    charts as a separate file, or print-friendly variants. This function
    doesn't distinguish between variant types; it simply collects ALL files
    found. Which of them actually get downloaded is decided by ignore.txt
    on the caller side.

    This can look like a failed login redirect from the content-type check's
    point of view, but it's a normal intermediate page and requires NO
    login - the links are visible even without a session.

    Returns an empty list if the page contains no such links (e.g. an
    actual login page).
    """
    files: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for link in _DL_LINK_RE.findall(html):
        link = link.replace("&amp;", "&").replace("http://", "https://", 1)
        if link in seen_urls:
            continue
        seen_urls.add(link)
        if "filename=" not in link:
            continue
        filename = unquote(link.rsplit("filename=", 1)[-1])
        files.append((filename, link))
    return files


def fetch_file_variants(url: str, cookies: dict | None = None) -> list[tuple[str, str]] | None:
    """
    Checks whether `url` (typically a Ravelry `/dls/{id}/{code}` URL) returns
    a multi-file "choose file" intermediate page, and if so, returns a list
    of (filename, download_url) tuples - one per file variant, with the
    REAL Ravelry filename. "Variant" here doesn't just mean language
    translations, but any kind of extra file Ravelry offers on the chooser
    page (e.g. an "Easy Read" version, a knitting chart, or a print-friendly
    edition). This lets the selection be controlled via ignore.txt, just
    like any other download, instead of hardcoding a preference for a
    variant in the code.

    Returns None if `url` already returns a PDF directly (pattern with only
    one file) or isn't a recognizable chooser page (e.g. an actual login
    page) - the caller should then use the normal single-file download path
    (download_pdf).
    """
    try:
        r = requests.get(url, timeout=30, cookies=cookies)
        r.raise_for_status()
    except requests.RequestException:
        return None

    content_type = r.headers.get("Content-Type", "")
    if _is_pdf_response(content_type, r.content[:16]):
        return None
    if "html" not in content_type.lower():
        return None

    files = _parse_chooser_links(r.text)
    return files or None


def download_pdf(url: str, target_path: str, cookies: dict | None = None) -> tuple[bool, str]:
    """
    Downloads a file from url to target_path and validates that it is
    actually a PDF (signature check + content-type).

    cookies: optional browser session cookies (for paid downloads, which
    would return /account/login instead of a PDF without a valid session -
    see ensure_browser_login()).

    Note: if `url` instead returns a Ravelry "choose file" intermediate page
    (multiple file variants, see fetch_file_variants()), this call fails
    with "No PDF" - that is intentional. Variant selection goes through
    fetch_file_variants() plus the normal ignore.txt filtering on the
    caller side, not here.

    Returns (True, info_text) or (False, error_text).
    """
    if not target_path.lower().endswith(".pdf"):
        target_path += ".pdf"

    try:
        r = requests.get(url, stream=True, timeout=60, cookies=cookies)
        r.raise_for_status()
        chunks = r.iter_content(chunk_size=8192)
        first = next(chunks, None)
        if not first:
            return False, "File is empty (0 bytes)"

        content_type = r.headers.get("Content-Type", "")
        if not _is_pdf_response(content_type, first):
            preview = first[:200].decode("utf-8", errors="ignore")
            return False, f"Not a PDF (Content-Type: {content_type})\n    Preview: {preview!r}"

        with open(target_path, "wb") as f:
            f.write(first)
            for chunk in chunks:
                if chunk:
                    f.write(chunk)

        size_kb = os.path.getsize(target_path) // 1024
        return True, f"{target_path}  ({size_kb} KB)"
    except Exception as e:
        return False, str(e)


# ── Browser login (Playwright) ───────────────────────────────────────────────
#
# Paid downloads go through /download/{id}/checkout URLs, which expect a
# logged-in browser session (cookie login). The REST API keys (Basic Auth
# against api.ravelry.com) are NOT accepted there.
#
# ensure_browser_login() opens a visible Chromium browser when needed, lets
# the user log in manually (2FA-capable, no password entry in the script),
# and then saves the session cookies locally so subsequent downloads/runs
# can reuse them.

def _load_cached_cookies() -> list[dict] | None:
    if not SESSION_FILE.exists():
        return None
    try:
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        return data.get("cookies")
    except (json.JSONDecodeError, OSError):
        return None


def _save_cookies(cookies: list[dict]) -> None:
    SESSION_FILE.write_text(json.dumps({"cookies": cookies}, indent=2), encoding="utf-8")


def _cookies_look_valid(cookies: list[dict]) -> bool:
    """Rough check: are there any Ravelry cookies at all, and are they not expired?"""
    if not cookies:
        return False
    now = time.time()
    ravelry_cookies = [c for c in cookies if "ravelry.com" in c.get("domain", "")]
    if not ravelry_cookies:
        return False
    # At least one cookie with no expiry or with an expiry in the future
    return any(c.get("expires", -1) == -1 or c.get("expires", 0) > now for c in ravelry_cookies)


def _cookies_to_requests_dict(cookies: list[dict]) -> dict:
    return {c["name"]: c["value"] for c in cookies if "ravelry.com" in c.get("domain", "")}


def _verify_session(cookies: list[dict]) -> bool:
    """Checks with an actual request whether the cookies are really logged in."""
    try:
        r = requests.get(
            "https://www.ravelry.com/account/login",
            cookies=_cookies_to_requests_dict(cookies),
            allow_redirects=False,
            timeout=15,
        )
        # Anyone already logged in gets redirected away from /account/login (302)
        # instead of getting the login page (200).
        return r.status_code in (301, 302, 303)
    except requests.RequestException:
        return False


def ensure_browser_login(force: bool = False) -> dict:
    """
    Ensures a valid Ravelry browser session and returns the cookies as a
    requests-compatible dict ({name: value}).

    Flow:
      1. If a cached, still-valid session exists (and force=False), it is
         returned directly - no browser needed.
      2. Otherwise, a visible Chromium browser is launched, the Ravelry
         login page is opened, and the script waits for the manual login
         (the user enters username/password/2FA themselves in the browser
         window).
      3. After a successful login, the cookies are saved and returned.

    Requires the 'playwright' package and installed browser binaries
    (one-time setup: `uv run --project . python3 -m playwright install chromium`).
    """
    if not force:
        cached = _load_cached_cookies()
        if cached and _cookies_look_valid(cached) and _verify_session(cached):
            print("🔐 Existing browser session is still valid - no login needed.")
            return _cookies_to_requests_dict(cached)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit(
            "❌ The 'playwright' package is required for browser login.\n"
            "   Install with:      uv add playwright\n"
            "   Browser binaries:  uv run --project . python3 -m playwright install chromium"
        )

    print("\n🌐 Opening browser for Ravelry login …")
    print("   Please log in in the browser window (username, password, 2FA if needed).")
    print("   The script will automatically wait until the login is complete.\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(LOGIN_URL, wait_until="networkidle")

        # Wait until we've left the login page (= logged in).
        # Timeout is intentionally high (5 minutes) for 2FA / slow typing.
        try:
            page.wait_for_url(lambda url: "/account/login" not in url, timeout=300_000)
        except Exception:
            browser.close()
            sys.exit("❌ Login timeout (5 minutes) - no successful login detected.")

        cookies = context.cookies()
        browser.close()

    if not _cookies_look_valid(cookies):
        sys.exit("❌ No valid Ravelry cookies found after login.")

    _save_cookies(cookies)
    print(f"✅ Login successful. Session saved to {SESSION_FILE.name}\n")
    return _cookies_to_requests_dict(cookies)


def clear_browser_session() -> None:
    """Deletes the cached browser session (e.g. in case of logout issues)."""
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()
        print(f"🗑️  Session file {SESSION_FILE.name} deleted.")


def download_with_login_fallback(
    url: str,
    target_path: str,
    browser_cookies: dict | None,
) -> tuple[bool, str, dict | None]:
    """
    Downloads a PDF. If the response isn't a PDF (HTML login page) AND no
    browser cookies have been passed in yet, ensure_browser_login() is
    called automatically and the download is retried once.

    Returns (ok, info, cookies) - cookies may be newly created so the
    caller can reuse them for further downloads within the same run.
    """
    ok, msg = download_pdf(url, target_path, cookies=browser_cookies)
    if ok or browser_cookies is not None:
        return ok, msg, browser_cookies

    # Not a PDF and no login attempted yet -> might need a session
    if "Not a PDF" in msg:
        print("   ℹ️  Didn't get a PDF without login - starting browser login …")
        browser_cookies = ensure_browser_login()
        ok, msg = download_pdf(url, target_path, cookies=browser_cookies)
        return ok, msg, browser_cookies

    return ok, msg, browser_cookies
