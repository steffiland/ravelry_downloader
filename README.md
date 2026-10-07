# Ravelry Tools

Python-Scripts zum Herunterladen von Patterns und PDFs aus dem eigenen Ravelry-Account.

---

## Voraussetzungen

- [uv](https://docs.astral.sh/uv/) installiert (`uv 0.12+`)
- Python 3.12 (wird von uv automatisch verwaltet)
- Ravelry-Account mit [Pro/Developer-Zugang](https://www.ravelry.com/pro/developer)

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

---

## Scripts ausführen

Alle Scripts sind **selbstständig ausführbar** mit `uv run` – sie deklarieren ihre
Abhängigkeiten im Datei-Header (`# /// script`), uv installiert diese automatisch
in ein temporäres Venv.

### Download-Test (`ravelry-test.py`)

Testet alle Pattern-Varianten (kostenlos, kostenpflichtig, eBook, Collection, Bundle)
und lädt jeweils das erste Exemplar herunter. Nützlich zum Debuggen und Erkunden der
API-Struktur.

```bash
uv run ravelry-test.py
# oder über die Projekt-Umgebung:
uv run --project . ravelry-test.py
```

Downloads landen in `test_downloads/`.

> **Bekannte Einschränkung:** Nur **kostenlose** Downloads (Variante 1) funktionieren
> mit den API-Keys. Deren URLs (`/dls/{id}/{code}`) leiten direkt auf eine vorsignierte
> S3-URL weiter. **Kostenpflichtige** Downloads (Varianten 2–6: Einzelpattern, eBooks,
> Collections, Bundles) laufen über `/download/{id}/checkout`-URLs, die eine
> eingeloggte **Browser-Session** verlangen – die REST-API-Keys (Basic Auth gegen
> `api.ravelry.com`) werden dort nicht akzeptiert, man landet auf der Login-Seite.
> Das Script gibt den API-Response pro Variante zur Analyse aus, bricht aber mit
> einem klaren Fehler ab, wenn statt eines PDFs eine HTML-Login-Seite zurückkommt.
> Für automatisierte Downloads kostenpflichtiger Inhalte wäre ein zusätzlicher
> Cookie-basierter Login-Flow nötig (nicht Teil dieses Scripts).

### Vollständiger Bibliotheks-Download (`ravelry-downloader.py`)

Lädt alle PDFs aus der eigenen Ravelry-Bibliothek herunter (Volumes + Einzelpattern),
mit Skip-Logik für bereits vorhandene Dateien.

```bash
uv run ravelry-downloader.py
```

Downloads landen in `ravelry_downloads/`.  
Beim ersten Start wird dort `ignore.txt` erstellt – darin können Dateinamen-Fragmente
eingetragen werden, die übersprungen werden sollen (z. B. `_NL.pdf` für niederländische
Versionen).

> Gilt dieselbe Einschränkung wie oben: Kostenpflichtige PDFs lassen sich mit reinen
> API-Keys aktuell **nicht** herunterladen (Redirect auf Login-Seite). Nur kostenlose
> Ravelry-Downloads werden erfolgreich gespeichert; bei allen anderen protokolliert
> das Script einen Fehler statt eine ungültige Datei zu schreiben.

### Stash & Projekte anzeigen (`ravelry.py`)

Gibt eine Pandas-Übersicht der eigenen Projekte und Garnvorräte aus.

```bash
uv run ravelry.py
```

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
> `pyproject.toml` – sinnvoll wenn zusätzliche Pakete lokal installiert sind.

---

## Projektstruktur

```
.
├── .env                    # API-Keys (nicht committen!)
├── .python-version         # Python 3.12 (für uv)
├── pyproject.toml          # Projektdefinition
├── uv.lock                 # Gesperrte Abhängigkeiten
│
├── ravelry-test.py         # API-Test: erste PDFs aller Varianten herunterladen
├── ravelry-downloader.py   # Vollständiger Bibliotheks-Download
├── ravelry.py              # Stash & Projekte als DataFrame
│
├── docs/
│   └── ravelry-api-kb.md  # API-Dokumentation / Knowledge Base
│
├── ravelry_downloads/      # Zielordner Downloader (wird angelegt)
│   └── ignore.txt          # Ausschlussliste (wird beim ersten Start angelegt)
└── test_downloads/         # Zielordner Test-Script (wird angelegt)
```

---

## Fehlersuche

| Problem | Lösung |
|---|---|
| `pyenv: version '3.12' is not installed` | `uv python install 3.12` |
| `401 Unauthorized` | Keys in `.env` prüfen; Personal Key ≠ Password |
| Download ergibt kein PDF | API-Response wird im Terminal ausgegeben – `Content-Type` und Vorschau prüfen |
| `SSL`-Fehler | `uv run --no-verify-ssl ravelry-downloader.py` (Firmen-Proxy) |
