# Ravelry Tools

Python-Scripts zum Herunterladen von Patterns und PDFs aus dem eigenen Ravelry-Account.

---

## Voraussetzungen

- [uv](https://docs.astral.sh/uv/) installiert (`uv 0.12+`)
- Python 3.12 (wird von uv automatisch verwaltet)
- Ravelry-Account mit [Pro/Developer-Zugang](https://www.ravelry.com/pro/developer)
- Für Browser-Login (kostenpflichtige Downloads, siehe unten): Playwright-Browser
  einmalig installieren (siehe Setup Schritt 3)

---

## Setup

### 1. API-Keys holen

Auf [ravelry.com/pro/developer](https://www.ravelry.com/pro/developer) eine App anlegen:
- Auth-Typ: **Basic Auth: Personal Key**
- Ergibt zwei Keys: **Access Key** (= Username) und **Personal Key** (= Password)

### 2. `.env`-Datei anlegen

```
RAVELRY_ACCESS_KEY=dein_access_key
RAVELRY_PERSONAL_KEY=dein_personal_key
```

Die `.env` liegt im Projektroot und ist über `.gitignore` vom Commit ausgeschlossen.

### 3. Playwright-Browser installieren (einmalig)

Für Downloads kostenpflichtiger Inhalte wird ein echter Browser-Login benötigt
(Details siehe Abschnitt „Browser-Login" unten). Dafür einmalig die
Chromium-Binaries von Playwright installieren:

```bash
uv run --project . python3 -m playwright install chromium
```

Unter WSL/Linux werden ggf. zusätzliche System-Bibliotheken benötigt
(Audio/Mesa/Font/X11), die der Browser zum headful-Start braucht:

```bash
sudo uv run --project . python3 -m playwright install-deps chromium
```

---

## Scripts ausführen

Alle Scripts sind **selbstständig ausführbar** mit `uv run` – sie deklarieren ihre
Abhängigkeiten im Datei-Header (`# /// script`), uv installiert diese automatisch
in ein temporäres Venv. Gemeinsame Logik (API-Zugriff, Downloads, Browser-Login)
liegt in `ravelry_common.py`, das von allen Scripts importiert wird.

### Download-Test (`ravelry-test.py`)

Testet alle Pattern-Varianten (kostenlos, kostenpflichtig, Einzelkauf, eBook,
Collection, Bundle) und lädt jeweils das erste Exemplar herunter. Nützlich zum
Debuggen und Erkunden der API-Struktur.

```bash
uv run ravelry-test.py
# oder über die Projekt-Umgebung:
uv run --project . ravelry-test.py
```

Downloads landen in `test_downloads/`.

### Vollständiger Bibliotheks-Download (`ravelry-downloader.py`)

Lädt alle PDFs aus der eigenen Ravelry-Bibliothek herunter (eBooks/Collections +
Einzelpattern), mit Skip-Logik für bereits vorhandene Dateien.

```bash
uv run ravelry-downloader.py
# oder über die Projekt-Umgebung:
uv run --project . ravelry-downloader.py
```

Downloads landen in `ravelry_downloads/`.

Der Downloader verarbeitet drei Arten von Library-Einträgen:

1. **eBooks/Collections mit eigenem PDF-Bundle** (`type=pdf`-Volumes)
2. **Einzeln gekaufte Pattern** (eigenes 1:1-Volume pro Pattern)
3. **Referenz-Collections** – Collections, die selbst KEIN PDF-Bundle haben,
   sondern nur auf mehrere einzeln verlinkte Pattern verweisen (z. B.
   Yarn-Hersteller-Sammlungen wie Scheepjes „YARN – The After Party", aber auch
   alte Zeitschriften-Ausgaben, die man z. B. nur zur Recherche in die Library
   aufgenommen hat, ohne sie bei Ravelry gekauft zu haben)

**Zwei getrennte Steuer-Dateien mit UNTERSCHIEDLICHER Logik:**

| Datei | Logik | Gilt für |
|---|---|---|
| `ravelry_downloads/ignore.txt` | **EXCLUDE** – alles wird geladen, außer was hier als Dateinamen-Fragment steht (z. B. `_NL.pdf`) | ALLE Downloads, auch Dateien innerhalb einer per `collections.txt` aktivierten Referenz-Collection |
| `ravelry_downloads/collections.txt` | **INCLUDE** – nichts wird geladen, außer eine Collection ist hier explizit aktiviert | NUR Referenz-Collections (Variante 3) |

Beide Dateien werden beim ersten Start automatisch mit Beispiel-Inhalt angelegt.

**`collections.txt`-Syntax** (Katalog zum Review, Opt-in statt Opt-out):

```
collection:213142                 <- AKTIV, wird heruntergeladen
#collection:393415                 <- INAKTIV (Standard für neue Funde)
```

Bei jedem Lauf trägt das Script neu gefundene Referenz-Collections automatisch
**inaktiv** (mit führendem `#`) ein – so entsteht eine vollständige, durchsuchbare
Katalogliste aller jemals gefundenen Collections, ohne dass versehentlich etwas
heruntergeladen wird. Zum Aktivieren einfach das führende `#` vor der Zeile
entfernen. Welche IDs schon einmal in den Katalog eingetragen wurden, merkt sich
das Script in `ravelry_downloads/.collection_sync.json`, damit eine bekannte
Collection beim nächsten Lauf nicht erneut angehängt wird – unabhängig davon,
ob du sie inzwischen aktiviert hast oder nicht.

**Verarbeitungsreihenfolge** (innerhalb jeder Stufe in der Reihenfolge, wie die
Ravelry-API die Library paginiert zurückgibt – keine eigene Sortierung):

1. Volumes mit eigenem PDF-Bundle (eBooks, Collections mit Attachments)
2. Einzeln gekaufte Pattern
3. Referenz-Collections (nur aktivierte, Mitglieder werden einzeln nachgeladen)
4. Transparenz-Report für Einträge ohne Download-Pfad
5. Log der nicht heruntergeladenen Einträge

**Log-Dateien** (werden bei jedem Lauf überschrieben, zeigen also den Stand des
*letzten* Laufs, nicht kumulativ über mehrere Läufe):

| Datei | Inhalt |
|---|---|
| `ravelry_downloads/skipped_non_downloadable.txt` | Library-Einträge ohne erkennbaren Download-Pfad (z. B. extern erworbene Zeitschriften-Einzelhefte oder Etsy-Käufe, die nur zur Recherche in der Library stehen) |
| `ravelry_downloads/excluded_by_ignore.txt` | Dateien/Collections, die in diesem Lauf NICHT heruntergeladen wurden (per `ignore.txt` oder fehlender Freigabe in `collections.txt`) |

Beide sind reine Logs, kein Steuer-Mechanismus – Ausschlüsse/Freigaben selbst
steuern weiterhin `ignore.txt` bzw. `collections.txt`.

> 🔗 `ravelry_downloads/` kann (und sollte bei größeren Bibliotheken) ein
> **Symlink auf ein NAS-Verzeichnis** sein, statt lokal auf der Platte zu
> liegen – gerade unter WSL, wo lokaler Speicherverbrauch in die dynamisch
> wachsende VHDX einfließt (siehe Warnhinweis unten). `ensure_download_dir()`
> erkennt Symlinks und bricht kontrolliert ab, falls das Linkziel (NAS-Mount)
> gerade nicht erreichbar ist, statt versehentlich einen neuen lokalen Ordner
> anzulegen. Die `tests/`-Suite berührt `ravelry_downloads/` grundsätzlich
> nicht – sie arbeitet ausschließlich in pytest-eigenen `tmp_path`-Verzeichnissen.

> ⚠️ Bei einer großen Bibliothek (hunderte Einträge, teils zweistellige MB pro PDF)
> kann ein kompletter Lauf viel Speicherplatz brauchen. Unter WSL wächst die virtuelle
> Festplatte (VHDX) dabei dynamisch mit und schrumpft nach dem Löschen der Dateien
> **nicht automatisch** wieder. Bei Bedarf: `wsl --manage <Distro> --compact`
> (Windows 11) oder `diskpart` + `compact vdisk`.

### Stash & Projekte anzeigen (`ravelry.py`)

Gibt eine Pandas-Übersicht der eigenen Projekte und Garnvorräte aus.

```bash
uv run ravelry.py
```

---

## Tests

Die Logik ohne Netzwerk-/Browser-Abhängigkeit (Ignore-Filter, Collection-Sync,
Dateinamen-Bereinigung, PDF-Signaturprüfung) ist mit `pytest` abgedeckt unter
`tests/`. Tests laufen vollständig offline mit synthetischen Fixtures – keine
echten API-Calls, kein Browser, keine Downloads.

```bash
uv run --project . pytest -v
```

| Testdatei | Deckt ab |
|---|---|
| `test_ignore_logic.py` | `ignore.txt`-Parsing (EXCLUDE) und `collections.txt`-Parsing (INCLUDE), Inline-Kommentare |
| `test_collection_sync.py` | Referenz-Collection-Erkennung, Katalog-Sync (inaktive Einträge), Idempotenz |
| `test_categorization.py` | Kategorisierung aller Library-Eintrags-Formen, Transparenz-Report |
| `test_excluded_log.py` | Log der nicht heruntergeladenen Einträge |
| `test_ravelry_common.py` | Dateinamen-Bereinigung, PDF-Erkennung, Cookie-Validierung |

Bei jeder Änderung an `ravelry-downloader.py` oder `ravelry_common.py` sollten
diese Tests vor dem nächsten echten Lauf grün sein – sie fangen Logikfehler
(z. B. im `ignore.txt`-Parser) ab, ohne dafür die eigene Bibliothek anfassen
oder PDFs herunterladen zu müssen.

**Wichtig: Die Tests nutzen ausschließlich synthetische Fixtures** (fest
einprogrammierte Beispiel-Dicts, z. B. in `test_categorization.py` die echten
Titel aus einer Live-Analyse der Library). Sie machen **keine** echten
API-Calls. Das bedeutet:

- Ändert sich deine echte Ravelry-Bibliothek (neue Pattern, neue Collections,
  gelöschte Einträge), bleiben alle Tests unverändert grün – sie reagieren
  nicht automatisch darauf, weil sie nie mit den echten Daten sprechen.
- Die Tests schützen vor **Logikfehlern** im Code (z. B. dem gefundenen Bug,
  bei dem Inline-Kommentare in `ignore.txt` nicht korrekt abgeschnitten
  wurden), nicht aber davor, dass Ravelry künftig eine **neue, bisher
  unbekannte Daten-Form** liefert, die durch keine der fünf Kategorien in
  `categorize_item()` abgedeckt ist.
- Taucht ein neues Konstrukt in der echten Library auf, das aktuell nicht
  passt, würde es als `orphan` oder `single_pattern_source` landen und im
  `skipped_non_downloadable.txt`-Report sichtbar werden (nie lautlos
  verschwinden) – aber ein Test dafür müsste erst manuell nachgezogen werden,
  sobald ein solcher Fall real auftritt (so wie `test_categorization.py` nach
  der Live-Analyse entstanden ist).

---

## Browser-Login (für kostenpflichtige Downloads)

Ravelry trennt zwei Auth-Systeme:

- **REST-API** (`api.ravelry.com`): Basic Auth mit den API-Keys aus `.env`.
  Funktioniert für alle `GET`-Abfragen und für **kostenlose** Pattern-Downloads
  (`/dls/{id}/{code}`-URLs leiten direkt auf eine vorsignierte S3-URL weiter).
- **Datei-Download** (`www.ravelry.com`): Für **alle anderen** PDFs (gekaufte
  Einzelpattern, eBooks, Collections, Bundle-Teile) wird eine eingeloggte
  **Browser-Session** (Cookie-Login) verlangt. Die API-Keys werden hier nicht
  akzeptiert – ohne gültige Session landet man auf der Login-Seite statt beim PDF.

Beide Scripts (`ravelry-test.py`, `ravelry-downloader.py`) behandeln das automatisch:

1. Ein Download-Versuch liefert HTML (Login-Seite) statt eines PDFs.
2. Das Script öffnet daraufhin automatisch ein **sichtbares** Chromium-Fenster
   (Playwright) mit der Ravelry-Login-Seite.
3. Du loggst dich dort **manuell** ein (Username/Passwort, ggf. 2FA) – das Script
   wartet bis zu 5 Minuten darauf.
4. Nach erfolgreichem Login werden die Session-Cookies lokal gespeichert
   (`.ravelry_session.json`) und für alle weiteren Downloads in diesem **und
   folgenden** Läufen wiederverwendet, bis die Session abläuft.

```python
# ravelry_common.py – zentrale Funktion
ensure_browser_login(force: bool = False) -> dict  # gibt Cookies als dict zurück
clear_browser_session()                            # löscht die gespeicherte Session
```

> 🔒 `.ravelry_session.json` enthält Login-Cookies und ist über `.gitignore`
> vom Commit ausgeschlossen. Niemals teilen oder committen!

**Troubleshooting Login:**
- Browser öffnet sich nicht / Fehler beim Start → Playwright-Browser + System-Deps
  installieren (siehe Setup Schritt 3).
- Login hängt / Timeout nach 5 Minuten → Script erneut starten, ggf.
  `.ravelry_session.json` vorher löschen.
- Nach Passwortänderung schlagen Downloads plötzlich fehl → alte Session ist
  ungültig; `.ravelry_session.json` löschen, nächster Lauf fragt neu nach Login.

---

## Alternativer Aufruf via `uv`-Projektumgebung

Das Projekt hat außerdem eine lokale `uv`-Umgebung (`.venv`). Diese nutzen:

```bash
# Abhängigkeiten installieren / aktualisieren
uv sync

# Script in der Projektumgebung ausführen
uv run --project . ravelry-downloader.py
```

> Unterschied: `uv run script.py` (ohne `--project`) nutzt ein isoliertes Wegwerf-Venv
> aus dem Script-Header. `uv run --project .` nutzt das persistente Projekt-Venv aus
> `pyproject.toml` – sinnvoll wenn zusätzliche Pakete lokal installiert sind oder wenn
> Playwright-Browser-Binaries bereits für dieses Venv installiert wurden.

---

## Projektstruktur

```
.
├── .env                     # API-Keys (nicht committen!)
├── .ravelry_session.json    # Browser-Login-Cookies (wird erzeugt, nicht committen!)
├── .python-version          # Python 3.12 (für uv)
├── pyproject.toml           # Projektdefinition
├── uv.lock                  # Gesperrte Abhängigkeiten
│
├── ravelry_common.py        # Gemeinsamer Helper: API, Downloads, Browser-Login
├── ravelry-test.py          # API-Test: erste PDFs aller Varianten herunterladen
├── ravelry-downloader.py    # Vollständiger Bibliotheks-Download
├── ravelry.py                # Stash & Projekte als DataFrame
│
├── tests/                    # pytest-Suite (offline, keine echten API-Calls)
│   ├── conftest.py
│   ├── test_ignore_logic.py
│   ├── test_collection_sync.py
│   ├── test_categorization.py
│   ├── test_excluded_log.py
│   └── test_ravelry_common.py
│
├── docs/
│   └── ravelry-api-kb.md   # API-Dokumentation / Knowledge Base
│
├── ravelry_downloads/       # Zielordner Downloader (wird angelegt, ggf. NAS-Symlink)
│   ├── ignore.txt           # EXCLUDE: Dateinamen-Filter (wird beim ersten Start angelegt)
│   ├── collections.txt     # INCLUDE: Collection-Freigabe-Katalog (wird beim ersten Start angelegt)
│   ├── .collection_sync.json  # Merkt sich bereits in den Katalog eingetragene IDs
│   ├── skipped_non_downloadable.txt  # Log: Einträge ohne Download-Pfad
│   └── excluded_by_ignore.txt        # Log: nicht heruntergeladene Einträge
└── test_downloads/          # Zielordner Test-Script (wird angelegt)
```

---

## Fehlersuche

| Problem | Lösung |
|---|---|
| `pyenv: version '3.12' is not installed` | `uv python install 3.12` |
| `401 Unauthorized` | Keys in `.env` prüfen; Personal Key ≠ Password |
| Download ergibt kein PDF | API-Response wird im Terminal ausgegeben – `Content-Type` und Vorschau prüfen |
| `symbol lookup error` beim Browser-Start | System-Deps fehlen: `sudo uv run --project . python3 -m playwright install-deps chromium` |
| Browser startet, aber kein Fenster sichtbar | Unter WSL: WSLg muss aktiv sein (`echo $DISPLAY` sollte `:0` o.ä. zeigen) |
| Login-Timeout nach 5 Minuten | Script neu starten; bei dauerhaften Problemen `.ravelry_session.json` löschen |
| `SSL`-Fehler | `uv run --no-verify-ssl ravelry-downloader.py` (Firmen-Proxy) |
