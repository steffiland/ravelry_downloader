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
Beim ersten Start wird dort `ignore.txt` erstellt – darin können Dateinamen-Fragmente
eingetragen werden, die übersprungen werden sollen (z. B. `_NL.pdf` für niederländische
Versionen).

Der Downloader verarbeitet drei Arten von Library-Einträgen:

1. **eBooks/Collections mit eigenem PDF-Bundle** (`type=pdf`-Volumes)
2. **Einzeln gekaufte Pattern** (eigenes 1:1-Volume pro Pattern)
3. **Referenz-Collections** – Collections, die selbst KEIN PDF-Bundle haben,
   sondern nur auf mehrere einzeln verlinkte Pattern verweisen (z. B.
   Yarn-Hersteller-Sammlungen wie Scheepjes „YARN – The After Party", aber auch
   alte Zeitschriften-Ausgaben, die man z. B. nur zur Recherche in die Library
   aufgenommen hat, ohne sie bei Ravelry gekauft zu haben)

> **Variante 3 (Referenz-Collections) nutzt einen Opt-out-Mechanismus:**
> Bei jedem Lauf trägt das Script neu gefundene Referenz-Collections automatisch
> als `collection:<id>  # <Titel> (<n> Pattern)` in `ignore.txt` ein – sie werden
> also standardmäßig **nicht** herunterladen. Willst du eine bestimmte Collection
> doch laden (z. B. weil sie wie „YARN – The After Party" tatsächlich kostenlose
> Ravelry-Downloads enthält), lösche einfach ihre Zeile aus `ignore.txt`.
> Welche IDs bereits automatisch eingetragen wurden, merkt sich das Script in
> `ravelry_downloads/.collection_sync.json` – eine von dir gelöschte Zeile wird
> dadurch beim nächsten Lauf **nicht** wieder automatisch hinzugefügt.
>
> Das ist besonders relevant, wenn Patterns/Zeitschriften, die man anderweitig
> gekauft und nur zu Recherchezwecken in die Library aufgenommen hat (um Ravelry
> als durchsuchbare "Single Source of Truth" für die eigene Mustersammlung zu
> nutzen), nicht versehentlich zu hunderten API-Calls für nicht-downloadbare
> Inhalte führen sollen.

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
├── docs/
│   └── ravelry-api-kb.md   # API-Dokumentation / Knowledge Base
│
├── ravelry_downloads/       # Zielordner Downloader (wird angelegt)
│   └── ignore.txt           # Ausschlussliste (wird beim ersten Start angelegt)
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
