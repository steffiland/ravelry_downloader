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
# KEIN auth= mitgeben! Die URL ist bereits signiert (S3/CDN).
response = requests.get(volume["volume_attachments"][0]["ravelry_download_url"], stream=True)
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

> **Hinweis:** `download_location[].url` für `type=ravelry` ist die direkte Download-URL für ein auf Ravelry gekauftes Pattern. Auch hier kein `auth=` benötigt – die URL ist bereits signiert.

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

## 8. PDF-Download-Workflow (komplett)

### 8.1 Volumes (Bücher/Magazine/Collections)

```
library/search.json?type=pdf
    └─> Volumes-Liste
         └─> /volumes/{id}.json
               └─> volume_attachments[].ravelry_download_url
                     └─> Direkter S3-Download (kein auth benötigt)
```

### 8.2 Einzeln gekaufte Ravelry-Pattern

```
library/search.json (kein type-Filter oder type=ravelry)
    └─> patterns[] mit ravelry_download: true
         └─> download_location[].url  (type="ravelry")
               └─> Direkter S3-Download (kein auth benötigt)
```

### 8.3 Pattern mit externem PDF (z.B. vom Designer-Website)

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
- Download-URLs sind **zeitlich begrenzte, vorsignierte S3-Links** – nicht cachen, immer frisch holen
- Die Download-URLs (`ravelry_download_url`, `download_location[].url`) brauchen **kein** `auth=`-Header
- Bei API-Calls immer `auth=AUTH` setzen

---

## 11. Nicht-öffentliche / Dokumentationslücken

Die offizielle Ravelry-API-Doku ist nur nach Login zugänglich. Folgende Dinge wurden durch Community-Reverse-Engineering ermittelt und können sich ändern:

- Genaue `type`-Werte für `library/search.json`
- Ob `patterns`-Array im Library-Response tatsächlich erscheint (muss live verifiziert werden)
- Download-URL-Format (S3 vs. eigener Proxy)
- Ablaufzeit der vorsignierten URLs
