"""
Ravelry Common Helper
======================
Gemeinsam genutzte Funktionen für alle ravelry-*.py Scripts:

  - REST-API-Zugriff (Basic Auth mit ACCESS_KEY/PERSONAL_KEY)
  - PDF-Downloads inkl. Validierung (Signatur-/Content-Type-Check)
  - Browser-gestützter Ravelry-Login via Playwright, für Downloads die
    eine eingeloggte Browser-Session statt API-Keys benötigen
    (kostenpflichtige Pattern/eBooks/Collections/Bundles, siehe
    docs/ravelry-api-kb.md Abschnitt 10/11)

Session-Cookies werden nach erfolgreichem Login unter
.ravelry_session.json zwischengespeichert (siehe .gitignore), damit nicht
bei jedem Lauf neu eingeloggt werden muss.

Dieses Modul ist KEIN eigenständiges Script – es wird von den anderen
ravelry-*.py Dateien importiert.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

ACCESS_KEY   = os.getenv("RAVELRY_ACCESS_KEY")
PERSONAL_KEY = os.getenv("RAVELRY_PERSONAL_KEY")

if not ACCESS_KEY or not PERSONAL_KEY:
    sys.exit("❌ RAVELRY_ACCESS_KEY oder RAVELRY_PERSONAL_KEY fehlt in der .env-Datei!")

BASE_URL = "https://api.ravelry.com"
AUTH     = (ACCESS_KEY, PERSONAL_KEY)

SESSION_FILE = Path(__file__).parent / ".ravelry_session.json"
LOGIN_URL    = "https://www.ravelry.com/account/login"


# ── REST-API ────────────────────────────────────────────────────────────────

def api_get(path: str, params: dict | None = None) -> dict:
    """GET gegen die Ravelry-REST-API mit Basic Auth (ACCESS_KEY/PERSONAL_KEY)."""
    r = requests.get(f"{BASE_URL}{path}", auth=AUTH, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def get_current_username() -> str:
    """Ermittelt den Benutzernamen des API-Inhabers."""
    return api_get("/current_user.json")["user"]["username"]


# ── Dateinamen / Downloads ───────────────────────────────────────────────────

def sanitize_filename(filename: str) -> str:
    """Bereinigt Dateinamen von Zeichen, die Dateisysteme nicht mögen."""
    return re.sub(r'[\\/*?:"<>|]', "_", filename)


def _is_pdf_response(content_type: str, first_chunk: bytes) -> bool:
    return first_chunk.startswith(b"%PDF-") or "pdf" in content_type.lower()


# Direkte Datei-Download-Links auf einer Ravelry-"Datei wählen"-Zwischenseite,
# z.B. <a href="https://www.ravelry.com/dl/scheepjes/827394?filename=....pdf">
_DL_LINK_RE = re.compile(r'href="(https?://www\.ravelry\.com/dl/[^"]+)"')


def _extract_file_chooser_url(html: str) -> str | None:
    """
    Extrahiert eine Direkt-Download-URL aus einer Ravelry-"Datei wählen"-
    Zwischenseite.

    Hintergrund: `download_location.url` (bzw. die daraus abgeleitete
    `/dls/{id}/{code}`-URL) liefert bei einem Pattern mit NUR EINER Datei
    direkt das PDF. Hat das Pattern aber mehrere Dateien (typischerweise
    Übersetzungen/Sprachvarianten – sehr häufig bei Referenz-Collections wie
    Scheepjes "YARN - The After Party"), liefert dieselbe URL stattdessen eine
    HTML-Seite mit je einem `/dl/{company}/{id}?filename=...`-Link pro Datei.
    Das sieht für die Content-Type-Prüfung wie eine fehlgeschlagene
    Login-Weiterleitung aus, ist aber eine normale Zwischenseite und braucht
    KEINEN Login – die Links sind auch ohne Session sichtbar.

    Bevorzugt wird eine Datei, deren Dateiname auf Englisch hindeutet (US/UK/
    ENGLISH), sonst wird einfach die erste gefundene Datei genommen. Gibt
    None zurück, wenn die Seite keine solchen Links enthält (z.B. eine
    echte Login-Seite).
    """
    links = []
    for link in _DL_LINK_RE.findall(html):
        link = link.replace("&amp;", "&").replace("http://", "https://", 1)
        if link not in links:
            links.append(link)
    if not links:
        return None

    for link in links:
        filename = link.rsplit("filename=", 1)[-1].upper()
        if any(tag in filename for tag in ("_US_", "_UK_", "ENGLISH")):
            return link
    return links[0]


def download_pdf(
    url: str,
    target_path: str,
    cookies: dict | None = None,
    _follow_chooser: bool = True,
) -> tuple[bool, str]:
    """
    Lädt eine Datei von url nach target_path herunter und validiert, dass es
    sich um ein PDF handelt (Signatur-Check + Content-Type).

    cookies: optionale Browser-Session-Cookies (für kostenpflichtige
    Downloads, die /account/login statt eines PDFs liefern würden ohne
    gültige Session – siehe ensure_browser_login()).

    _follow_chooser: intern genutzt, um EINMALIG einer Ravelry-"Datei
    wählen"-Zwischenseite zu folgen (siehe _extract_file_chooser_url). Nicht
    von außen setzen.

    Gibt (True, infotext) oder (False, fehlertext) zurück.
    """
    if not target_path.lower().endswith(".pdf"):
        target_path += ".pdf"

    try:
        r = requests.get(url, stream=True, timeout=60, cookies=cookies)
        r.raise_for_status()
        chunks = r.iter_content(chunk_size=8192)
        first = next(chunks, None)
        if not first:
            return False, "Datei leer (0 Bytes)"

        content_type = r.headers.get("Content-Type", "")
        if not _is_pdf_response(content_type, first):
            if _follow_chooser and "html" in content_type.lower():
                body = first + b"".join(chunks)
                html = body.decode("utf-8", errors="ignore")
                chooser_url = _extract_file_chooser_url(html)
                if chooser_url:
                    return download_pdf(
                        chooser_url, target_path, cookies=cookies, _follow_chooser=False
                    )
            preview = first[:200].decode("utf-8", errors="ignore")
            return False, f"Kein PDF (Content-Type: {content_type})\n    Vorschau: {preview!r}"

        with open(target_path, "wb") as f:
            f.write(first)
            for chunk in chunks:
                if chunk:
                    f.write(chunk)

        size_kb = os.path.getsize(target_path) // 1024
        return True, f"{target_path}  ({size_kb} KB)"
    except Exception as e:
        return False, str(e)


# ── Browser-Login (Playwright) ──────────────────────────────────────────────
#
# Kostenpflichtige Downloads laufen über /download/{id}/checkout-URLs, die
# eine eingeloggte Browser-Session (Cookie-Login) erwarten. Die REST-API-Keys
# (Basic Auth gegen api.ravelry.com) werden dort NICHT akzeptiert.
#
# ensure_browser_login() öffnet bei Bedarf einen sichtbaren Chromium-Browser,
# lässt den Nutzer sich manuell einloggen (2FA-fähig, keine Passwort-Eingabe
# im Script), und speichert anschließend die Session-Cookies lokal ab, damit
# nachfolgende Downloads/Läufe sie wiederverwenden können.

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
    """Grobe Prüfung: sind überhaupt Ravelry-Cookies da und nicht abgelaufen?"""
    if not cookies:
        return False
    now = time.time()
    ravelry_cookies = [c for c in cookies if "ravelry.com" in c.get("domain", "")]
    if not ravelry_cookies:
        return False
    # Mindestens ein Cookie ohne Ablauf oder mit Ablauf in der Zukunft
    return any(c.get("expires", -1) == -1 or c.get("expires", 0) > now for c in ravelry_cookies)


def _cookies_to_requests_dict(cookies: list[dict]) -> dict:
    return {c["name"]: c["value"] for c in cookies if "ravelry.com" in c.get("domain", "")}


def _verify_session(cookies: list[dict]) -> bool:
    """Prüft per echtem Request, ob die Cookies tatsächlich eingeloggt sind."""
    try:
        r = requests.get(
            "https://www.ravelry.com/account/login",
            cookies=_cookies_to_requests_dict(cookies),
            allow_redirects=False,
            timeout=15,
        )
        # Wer bereits eingeloggt ist, wird von /account/login weggeleitet (302)
        # statt die Login-Seite (200) zu bekommen.
        return r.status_code in (301, 302, 303)
    except requests.RequestException:
        return False


def ensure_browser_login(force: bool = False) -> dict:
    """
    Stellt eine gültige Ravelry-Browser-Session sicher und gibt die Cookies
    als requests-kompatibles dict zurück ({name: value}).

    Ablauf:
      1. Falls eine gecachte, noch gültige Session existiert (und force=False),
         wird sie direkt zurückgegeben – kein Browser nötig.
      2. Sonst wird ein sichtbarer Chromium-Browser gestartet, die
         Ravelry-Login-Seite geöffnet und auf den manuellen Login gewartet
         (der Nutzer gibt Username/Passwort/2FA selbst im Browserfenster ein).
      3. Nach erfolgreichem Login werden die Cookies gespeichert und
         zurückgegeben.

    Erfordert das 'playwright'-Package und installierte Browser-Binaries
    (einmalig: `uv run --project . python3 -m playwright install chromium`).
    """
    if not force:
        cached = _load_cached_cookies()
        if cached and _cookies_look_valid(cached) and _verify_session(cached):
            print("🔐 Vorhandene Browser-Session ist noch gültig – kein Login nötig.")
            return _cookies_to_requests_dict(cached)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit(
            "❌ Für den Browser-Login wird das 'playwright'-Package benötigt.\n"
            "   Installieren mit:  uv add playwright\n"
            "   Browser-Binaries:  uv run --project . python3 -m playwright install chromium"
        )

    print("\n🌐 Öffne Browser für den Ravelry-Login …")
    print("   Bitte im Browserfenster einloggen (Username, Passwort, ggf. 2FA).")
    print("   Das Script wartet automatisch, bis der Login abgeschlossen ist.\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(LOGIN_URL, wait_until="networkidle")

        # Warten, bis wir die Login-Seite verlassen haben (= eingeloggt).
        # Timeout bewusst hoch (5 Minuten) für 2FA / langsames Tippen.
        try:
            page.wait_for_url(lambda url: "/account/login" not in url, timeout=300_000)
        except Exception:
            browser.close()
            sys.exit("❌ Login-Timeout (5 Minuten) – kein erfolgreicher Login erkannt.")

        cookies = context.cookies()
        browser.close()

    if not _cookies_look_valid(cookies):
        sys.exit("❌ Nach dem Login wurden keine gültigen Ravelry-Cookies gefunden.")

    _save_cookies(cookies)
    print(f"✅ Login erfolgreich. Session gespeichert in {SESSION_FILE.name}\n")
    return _cookies_to_requests_dict(cookies)


def clear_browser_session() -> None:
    """Löscht die gecachte Browser-Session (z.B. bei Logout-Problemen)."""
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()
        print(f"🗑️  Session-Datei {SESSION_FILE.name} gelöscht.")


def download_with_login_fallback(
    url: str,
    target_path: str,
    browser_cookies: dict | None,
) -> tuple[bool, str, dict | None]:
    """
    Lädt ein PDF herunter. Falls die Antwort kein PDF ist (HTML-Login-Seite)
    UND noch keine Browser-Cookies übergeben wurden, wird automatisch
    ensure_browser_login() aufgerufen und der Download einmal wiederholt.

    Gibt (ok, info, cookies) zurück – cookies ggf. neu erzeugt, damit der
    Aufrufer sie für weitere Downloads im selben Lauf wiederverwenden kann.
    """
    ok, msg = download_pdf(url, target_path, cookies=browser_cookies)
    if ok or browser_cookies is not None:
        return ok, msg, browser_cookies

    # Kein PDF und noch kein Login versucht -> evtl. braucht's eine Session
    if "Kein PDF" in msg:
        print("   ℹ️  Kein PDF ohne Login erhalten – starte Browser-Login …")
        browser_cookies = ensure_browser_login()
        ok, msg = download_pdf(url, target_path, cookies=browser_cookies)
        return ok, msg, browser_cookies

    return ok, msg, browser_cookies
