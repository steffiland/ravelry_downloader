# Ravelry API – Knowledge Base

> Stand: Oktober 2026  
> Basis-URL: `https://api.ravelry.com`

---

## 1. Authentifizierung

Ravelry unterstützt drei Auth-Methoden:

| Methode | Wann | Keys |
|---|---|---|
| **Basic Auth (read-only)** | Öffentliche Katalogdaten, kein Login nötig | `ACCESS_KEY` als Username, `PERSONAL_KEY` als Password |
| **Basic Auth (personal)** | Zugriff auf eigene Bibliothek, Käufe, Stash etc. | `ACCESS_KEY` + `PERSONAL_KEY` (aus Ravelry Pro) |
| **OAuth 2.0** | Fremde User-Daten (App für andere Nutzer) | `ACCESS_KEY` + `SECRET_KEY` + Callback-URL |

Für den eigenen Account reicht **Basic Auth mit Personal Key**:
```python
AUTH = (ACCESS_KEY, PERSONAL_KEY)
requests.get(url, auth=AUTH)
```

Keys holen: https://www.ravelry.com/pro/developer → App anlegen → „Basic Auth: Personal Key"

---

## 2. Aktueller User

```
GET /current_user.json
```
**Response-Felder (user):**
- `id`, `username`, `email`
- `photo_url`, `small_photo_url`

```python
res = requests.get("https://api.ravelry.com/current_user.json", auth=AUTH)
username = res.json()["user"]["username"]
```

---

## 3. Bibliothek (Library)

Das ist das Herzstück für PDF-Downloads.

### 3.1 Library Search

```
GET /people/{username}/library/search.json
```

**Query-Parameter:**

| Parameter | Werte | Beschreibung |
|---|---|---|
| `page` | int | Seite |
| `page_size` | int (max. 100) | Einträge pro Seite |
| `type` | `pdf`, `pattern`, `ravelry` | Typ-Filter (s.u.) |
| `query` | string | Freitextsuche |
| `sort` | `added`, `title`, `author` | Sortierung |

**Wichtig: `type`-Werte:**

| Wert | Was wird zurückgegeben |
|---|---|
| `pdf` | **Volumes** – Bücher, Magazine, Collections mit eigenem PDF-Anhang (`volume_attachments`) |
| `pattern` | Einzeln gekaufte Pattern (ravelry_download, externe PDF-Links) |
| `ravelry` | Pattern, direkt auf Ravelry als Download gekauft |
| *(kein Filter)* | Alles kombiniert |

**Response-Struktur:**
```json
{
  "volumes": [...],
  "paginator": {
    "page": 1,
    "page_count": 5,
    "page_size": 50,
    "results": 240
  }
}
```

### 3.2 Volumes (Bücher/Magazine/Collections mit PDF)

**Volume-Summary aus Library Search:**
```json
{
  "id": 12345,
  "title": "Mein Strickbuch",
  "permalink": "mein-strickbuch",
  "pattern_author": { "id": 999, "name": "..." }
}
```

**Volume-Details abrufen:**
```
GET /volumes/{volume_id}.json
```

**Response-Struktur:**
```json
{
  "volume": {
    "id": 12345,
    "title": "Mein Strickbuch",
    "volume_attachments": [
      {
        "id": 111,
        "filename": "mein-strickbuch_DE.pdf",
        "content_type": "application/pdf",
        "ravelry_download_url": "https://downloads.ravelry.com/...",
        "file_size": 5242880
      }
    ],
    "patterns": [...],
    "pattern_source": {...}
  }
}
```

**PDF herunterladen:**
```python
# KEIN API-auth= mitgeben – aber eine eingeloggte Browser-Session (Cookies)
# ist nötig, siehe Abschnitt 10.1!
response = requests.get(
    volume["volume_attachments"][0]["ravelry_download_url"],
    cookies=browser_cookies,
    stream=True,
)
```

---

## 4. Pattern-Downloads (einzeln gekauft)

### 4.1 Pattern-Details abrufen

```
GET /patterns/{pattern_id}.json
```

**Relevante Felder für Downloads:**

| Feld | Typ | Bedeutung |
|---|---|---|
| `ravelry_download` | bool | True = direkt auf Ravelry kaufbar/gekauft |
| `pdf_in_library` | bool | True = PDF bereits in eigener Bibliothek vorhanden |
| `volumes_in_library` | list | Volume-IDs, in denen das Pattern in der eigenen Bibliothek liegt |
| `download_location` | list | Download-Infos (s.u.) |
| `downloadable` | bool | True = überhaupt als Download verfügbar |

**`download_location`-Struktur:**
```json
{
  "download_location": [
    {
      "url": "https://downloads.ravelry.com/...",
      "type": "ravelry",
      "free": false
    }
  ]
}
```

> **Hinweis (korrigiert nach Live-Test):** `download_location[].url` ist eine
> **Kauf-/Checkout-URL** (`/purchase/...` bzw. `/download/{id}/checkout`), KEINE
> direkte Download-URL für bereits gekaufte Inhalte! Sie leitet auf die
> Warenkorb-/Checkout-Seite, nicht auf das PDF. Für ein Pattern, das schon in der
> eigenen Library ist (`pdf_in_library: true`), muss der Download stattdessen über
> `volumes_in_library` → `/volumes/{id}.json` → `volume_attachments[].ravelry_download_url`
> erfolgen (siehe Abschnitt 8). Diese URL braucht ebenfalls eine eingeloggte
> Browser-Session (siehe Abschnitt 10.1).

### 4.2 Pattern-Suche in der eigenen Bibliothek

```
GET /people/{username}/library/search.json?type=pattern
```

Gibt Pattern zurück, die in der Bibliothek sind (als einzeln gekaufte Ravelry-Downloads).

**Response-Struktur (ohne type=pdf):**
```json
{
  "volumes": [...],
  "patterns": [
    {
      "id": 67890,
      "name": "Mein Lieblingsmuster",
      "permalink": "mein-lieblingsmuster",
      "ravelry_download": true,
      "pdf_url": "",
      "download_location": {
        "url": "https://downloads.ravelry.com/...",
        "type": "ravelry",
        "free": false
      }
    }
  ]
}
```

---

## 5. Collections / Bundles

Auf Ravelry gibt es zwei Typen:

### 5.1 Designer-Bundles (bei Kauf: einzelne Patterns)

Wenn ein Designer mehrere Patterns zu einem Bundle bündelt, werden beim Kauf alle enthaltenen Patterns **einzeln** in die Bibliothek eingetragen. Jedes Pattern erscheint dann als `ravelry_download: true` in der Library.  
→ Werden durch Library-Suche mit `type=pattern` / `type=ravelry` gefunden.

### 5.2 User-eigene Bundles (Favoriten-Sammlungen)

```
GET /people/{username}/bundles/list.json
GET /people/{username}/bundles/{bundle_id}.json
POST /people/{username}/bundles/create.json
```

Das sind benutzerdefinierte Sammlungen (wie Pinterest-Boards) – keine Kaufobjekte, keine Downloads.

---

## 6. Alle wichtigen API-Endpunkte (Übersicht)

### Patterns

| Endpunkt | Methode | Beschreibung |
|---|---|---|
| `/patterns/search.json` | GET | Globale Pattern-Suche |
| `/patterns/{id}.json` | GET | Pattern-Details (inkl. download_location) |
| `/patterns.json` | GET | Mehrere Patterns auf einmal (IDs als Param) |
| `/patterns/{id}/comments.json` | GET | Kommentare zu einem Pattern |
| `/patterns/{id}/projects.json` | GET | Projekte, die dieses Pattern verwenden |
| `/pattern_sources/{id}.json` | GET | Quellbuch/-magazin Details |
| `/pattern_sources/search.json` | GET | Quellbücher suchen |
| `/pattern_sources/{id}/patterns.json` | GET | Patterns einer Quelle |
| `/pattern_categories.json` | GET | Alle Pattern-Kategorien |

**Wichtige Suchfilter für `/patterns/search.json`:**

| Parameter | Werte | Beispiel |
|---|---|---|
| `availability` | `free`, `ravelry`, `purchase` | `availability=+ravelry` (nur Ravelry-Downloads) |
| `craft` | `knitting`, `crochet` | |
| `fit` | `adult`, `baby`, `child` | |
| `pc` | Pattern-Kategorien | `sweater`, `hat`, `shawl` |
| `sort` | `projects`, `favorites`, `date` | |
| `page`, `page_size` | | |

### Projects (Projekte)

| Endpunkt | Methode | Beschreibung |
|---|---|---|
| `/projects/{username}/list.json` | GET | Alle Projekte eines Users |
| `/projects/{username}/{id}.json` | GET | Projekt-Details |
| `/projects/search.json` | GET | Globale Projekt-Suche |
| `/projects/{username}/create.json` | POST | Neues Projekt anlegen |
| `/projects/{username}/{id}.json` | POST | Projekt aktualisieren |
| `/projects/{username}/{id}.json` | DELETE | Projekt löschen |

### Stash (Garnvorrat)

| Endpunkt | Methode | Beschreibung |
|---|---|---|
| `/people/{username}/stash/list.json` | GET | Stash-Liste |
| `/people/{username}/stash/{id}.json` | GET | Stash-Eintrag Details |
| `/people/{username}/stash/create.json` | POST | Neuen Stash-Eintrag anlegen |
| `/people/{username}/stash/{id}.json` | POST | Stash-Eintrag aktualisieren |
| `/people/{username}/stash/{id}.json` | DELETE | Löschen |
| `/people/{username}/stash/unified/list.json` | GET | Vereinheitlichte Stash-Liste |
| `/stash/search.json` | GET | Globale Stash-Suche |

### Yarns (Garne)

| Endpunkt | Methode | Beschreibung |
|---|---|---|
| `/yarns/search.json` | GET | Garne suchen |
| `/yarns/{id}.json` | GET | Garn-Details |
| `/yarns.json` | GET | Mehrere Garne (IDs als Param) |
| `/yarn_weights.json` | GET | Alle Garngewichte (Lace, Fingering, DK, ...) |

### Queue (Warteschlange)

| Endpunkt | Methode | Beschreibung |
|---|---|---|
| `/people/{username}/queue/list.json` | GET | Queue auflisten |
| `/people/{username}/queue/{id}.json` | GET | Queue-Eintrag Details |
| `/people/{username}/queue/create.json` | POST | Eintrag anlegen |
| `/people/{username}/queue/{id}/update.json` | POST | Eintrag aktualisieren |
| `/people/{username}/queue/{id}/reposition.json` | POST | Reihenfolge ändern |
| `/people/{username}/queue/{id}.json` | DELETE | Löschen |

### Favorites (Favoriten)

| Endpunkt | Methode | Beschreibung |
|---|---|---|
| `/people/{username}/favorites/list.json` | GET | Favoritenliste |
| `/people/{username}/favorites/{id}.json` | GET | Favoriten-Details |
| `/people/{username}/favorites/create.json` | POST | Anlegen |
| `/people/{username}/favorites/{id}.json` | POST | Aktualisieren |
| `/people/{username}/favorites/{id}.json` | DELETE | Löschen |
| `/people/{username}/favorites/{id}/add_to_bundle.json` | POST | Zu Bundle hinzufügen |
| `/people/{username}/favorites/{id}/remove_from_bundle.json` | POST | Aus Bundle entfernen |

### People / Nutzer

| Endpunkt | Methode | Beschreibung |
|---|---|---|
| `/current_user.json` | GET | Eigener User |
| `/people/{username}.json` | GET | User-Details |
| `/people/{username}.json` | POST | User-Daten aktualisieren |

### Needles (Nadeln)

| Endpunkt | Methode | Beschreibung |
|---|---|---|
| `/people/{username}/needles/list.json` | GET | Nadel-Sammlung |
| `/needles/sizes.json` | GET | Alle Nadelgrößen |
| `/needles/types.json` | GET | Alle Nadeltypen |

### Shops

| Endpunkt | Methode | Beschreibung |
|---|---|---|
| `/shops/search.json` | GET | Shops suchen |
| `/shops/{id}.json` | GET | Shop-Details |

### Volumes / Library

| Endpunkt | Methode | Beschreibung |
|---|---|---|
| `/people/{username}/library/search.json` | GET | Bibliothek durchsuchen |
| `/volumes/{id}.json` | GET | Volume-Details (inkl. Attachments) |
| `/volumes/create.json` | POST | Volume anlegen |
| `/volumes/{id}.json` | DELETE | Volume löschen |

### Sonstiges

| Endpunkt | Methode | Beschreibung |
|---|---|---|
| `/color_families.json` | GET | Farbfamilien |
| `/yarn_weights.json` | GET | Garngewichte |
| `/groups/search.json` | GET | Gruppen suchen |
| `/forums/sets.json` | GET | Forum-Kategorien |
| `/forums/{id}/topics.json` | GET | Themen in einem Forum |
| `/messages/list.json` | GET | Nachrichten |
| `/comments/create.json` | POST | Kommentar erstellen |

---

## 7. Paginierung

Alle Listen-Endpunkte liefern `paginator`:
```json
{
  "paginator": {
    "page": 1,
    "page_count": 10,
    "page_size": 50,
    "results": 497
  }
}
```

Standard-Iteration:
```python
while page <= data["paginator"]["page_count"]:
    page += 1
```

---

## 8. PDF-Download-Workflow (komplett, live-verifiziert Okt. 2026)

**Zentrale Erkenntnis:** JEDER Library-Eintrag – egal ob eBook, Collection,
Einzelpattern oder Bundle-Teil – ist technisch ein **Volume**-Objekt. Der
PDF-Download läuft für alle Varianten über denselben Mechanismus:

```
library/search.json  (type=pdf ODER ohne Filter)
    └─> volumes[]  (Summary: id, pattern_id, pattern_source_id, patterns_count, has_downloads)
         └─> /volumes/{id}.json
               └─> volume_attachments[].ravelry_download_url
                     └─> Download MIT Browser-Session-Cookie (siehe 10.1)
```

Unterscheidung der Volume-Typen anhand der Summary-Felder:

| Typ | Erkennungsmerkmal |
|---|---|
| **eBook/Buch** | `pattern_id` gesetzt, `patterns_count == 1`, meist mehrere `volume_attachments` (z.B. NL/US-Version + Chart) |
| **Einzelpattern** | identisch zum eBook-Fall – Ravelry legt für jeden Pattern-Kauf intern ein 1:1-Volume an |
| **Collection** | `pattern_source_id` gesetzt, `patterns_count > 1`, EIN Volume mit mehreren Attachments (je 1 pro enthaltenem Pattern) |
| **Bundle** | mehrere Volumes mit `patterns_count == 1`, aber identischem `created_at`-Zeitstempel (= derselbe Checkout) |

### 8.1 download_location.url ist KEINE Download-URL

`pattern.download_location[].url` (z.B. `http://www.ravelry.com/purchase/.../123`
oder `/download/{id}/checkout`) ist eine **Kauf-/Checkout-URL**. Sie führt zum
Warenkorb, nicht zum PDF – auch nicht mit gültiger Browser-Session. Ist das
Pattern bereits gekauft (`pattern.pdf_in_library: true`), muss der Download
stattdessen über `pattern.volumes_in_library[0]` → `/volumes/{id}.json` laufen.

### 8.2 Pattern mit externem PDF (z.B. von der Designer-Website)

```
/patterns/{id}.json
    └─> pdf_url  (externe URL, nicht immer funktionsfähig)
    └─> download_location[].url  (type="web", "external", etc.)
```

> Diese können nicht automatisch heruntergeladen werden – die Designer-Website braucht ggf. eigene Authentifizierung.

---

## 9. Wichtige Datenstrukturen

### Pattern (gekürzt)

```json
{
  "id": 67890,
  "name": "Socken Muster",
  "permalink": "socken-muster",
  "free": false,
  "price": "5.00",
  "currency": "EUR",
  "ravelry_download": true,
  "downloadable": true,
  "pdf_in_library": false,
  "volumes_in_library": [],
  "download_location": [
    {
      "url": "https://downloads.ravelry.com/...",
      "type": "ravelry",
      "free": false
    }
  ],
  "pattern_author": { "id": 99, "name": "Designer Name", "permalink": "designer" },
  "craft": { "name": "Knitting" },
  "pattern_categories": [{ "name": "Socks" }],
  "yarn_weight": { "name": "Fingering" },
  "gauge": 32.0,
  "gauge_divisor": 4,
  "rating_average": 4.7,
  "favorites_count": 1200,
  "projects_count": 500
}
```

### Volume (gekürzt)

```json
{
  "id": 12345,
  "title": "Mein Strickbuch",
  "volume_attachments": [
    {
      "id": 111,
      "filename": "MeinStrickbuch_DE.pdf",
      "content_type": "application/pdf",
      "ravelry_download_url": "https://downloads.ravelry.com/...",
      "file_size": 5242880
    },
    {
      "id": 112,
      "filename": "MeinStrickbuch_EN.pdf",
      "content_type": "application/pdf",
      "ravelry_download_url": "https://downloads.ravelry.com/...",
      "file_size": 4800000
    }
  ],
  "pattern_source": {
    "id": 555,
    "name": "Mein Strickbuch",
    "author": "Designer Name"
  }
}
```

### Stash-Eintrag (gekürzt)

```json
{
  "id": 44444,
  "name": "Merino Blau",
  "yarn_company_name": "Lang Yarns",
  "yarn_name": "Merino 120",
  "colorway_name": "Indigo",
  "location": "Kiste 3",
  "strands_per_skein": 1,
  "grams_per_skein": 100,
  "yards_per_skein": 130,
  "skeins": 3.5
}
```

---

## 10. Rate Limits & Best Practices

- Kein offiziell dokumentiertes Rate-Limit, aber **0.3s Pause** zwischen Requests empfohlen
- Max. `page_size = 100` (manche Endpunkte weniger)
- Bei REST-API-Calls (`api.ravelry.com`) immer `auth=AUTH` (Basic Auth mit den API-Keys) setzen

### 10.1 Zwei getrennte Auth-Systeme bei Downloads (wichtig!)

Live-getestet (Oktober 2026) mit echten gekauften/hinzugefügten Library-Inhalten:

| Download-Typ | URL-Muster | Benötigte Auth |
|---|---|---|
| **Kostenloses Pattern** | `/dls/{id}/{code}` | Keine – leitet direkt auf eine zeitlich begrenzte, vorsignierte S3-URL weiter |
| **Alles andere** (`volume_attachments[].ravelry_download_url`) | `/download/{id}/checkout` | **Eingeloggte Browser-Session** (Cookies) – API-Keys werden NICHT akzeptiert |

Ohne gültige Session liefert `/download/{id}/checkout` eine HTML-Login-Seite
(`<title>Ravelry</title>` bzw. `<title>Ravelry: Checking out...</title>`)
statt des PDFs – erkennbar am `Content-Type: text/html` und fehlender
`%PDF-`-Signatur im Response-Body.

**Praktische Lösung:** Browser-Login per [Playwright](https://playwright.dev/python/)
automatisieren – ein sichtbares Chromium-Fenster öffnen, Nutzer loggt sich manuell
ein (2FA-fähig), danach `context.cookies()` abgreifen und bei allen folgenden
`requests.get(url, cookies=...)`-Aufrufen mitschicken. Session-Cookies halten
typischerweise mehrere Tage bis Wochen und können lokal zwischengespeichert werden,
um nicht bei jedem Lauf neu einzuloggen. Implementiert in `ravelry_common.py`
(`ensure_browser_login()`).

---

## 11. Nicht-öffentliche / Dokumentationslücken

Die offizielle Ravelry-API-Doku ist nur nach Login zugänglich. Live-verifiziert
(Oktober 2026, siehe Abschnitt 8 und 10.1):

- ✅ **Geklärt:** `library/search.json` liefert IMMER `volumes[]` zurück (kein
  separates `patterns[]`-Array) – auch für Einzelpattern und Bundle-Teile.
  Relevante Felder: `id`, `pattern_id`, `pattern_source_id`, `patterns_count`,
  `has_downloads`, `created_at`.
- ✅ **Geklärt:** `download_location[].url` ist eine Kauf-URL, nicht die
  PDF-Download-URL (siehe 8.1).
- ✅ **Geklärt:** `volume_attachments[].ravelry_download_url` erfordert eine
  eingeloggte Browser-Session, nicht die REST-API-Keys (siehe 10.1).

Weiterhin unklar / kann sich ändern:

- Exakte Ablaufzeit der Browser-Session-Cookies
- Ob/wie sich das Verhalten bei OAuth2-Apps (statt Personal Key) unterscheidet
- Genaue `type`-Werte für `library/search.json` jenseits von `pdf`
