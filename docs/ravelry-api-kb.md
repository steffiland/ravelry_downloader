# Ravelry API - Knowledge Base

> As of: October 2026  
> Base URL: `https://api.ravelry.com`

---

## 1. Authentication

Ravelry supports three auth methods:

| Method | When | Keys |
|---|---|---|
| **Basic Auth (read-only)** | Public catalog data, no login needed | `ACCESS_KEY` as username, `PERSONAL_KEY` as password |
| **Basic Auth (personal)** | Access to your own library, purchases, stash etc. | `ACCESS_KEY` + `PERSONAL_KEY` (from Ravelry Pro) |
| **OAuth 2.0** | Other users' data (app for other users) | `ACCESS_KEY` + `SECRET_KEY` + callback URL |

For your own account, **Basic Auth with a personal key** is enough:
```python
AUTH = (ACCESS_KEY, PERSONAL_KEY)
requests.get(url, auth=AUTH)
```

Get keys: https://www.ravelry.com/pro/developer → create an app → "Basic Auth: Personal Key"

---

## 2. Current user

```
GET /current_user.json
```
**Response fields (user):**
- `id`, `username`, `email`
- `photo_url`, `small_photo_url`

```python
res = requests.get("https://api.ravelry.com/current_user.json", auth=AUTH)
username = res.json()["user"]["username"]
```

---

## 3. Library

This is the core piece for PDF downloads.

### 3.1 Library Search

```
GET /people/{username}/library/search.json
```

**Query parameters:**

| Parameter | Values | Description |
|---|---|---|
| `page` | int | Page |
| `page_size` | int (max. 100) | Entries per page |
| `type` | `pdf`, `pattern`, `ravelry` | Type filter (see below) |
| `query` | string | Free-text search |
| `sort` | `added`, `title`, `author` | Sort order |

**Important: `type` values:**

| Value | What's returned |
|---|---|
| `pdf` | **Volumes** - books, magazines, collections with their own PDF attachment (`volume_attachments`) |
| `pattern` | Individually purchased patterns (ravelry_download, external PDF links) |
| `ravelry` | Patterns purchased directly on Ravelry as a download |
| *(no filter)* | Everything combined |

**Response structure:**
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

### 3.2 Volumes (books/magazines/collections with a PDF)

**Volume summary from library search:**
```json
{
  "id": 12345,
  "title": "My Knitting Book",
  "permalink": "my-knitting-book",
  "pattern_author": { "id": 999, "name": "..." }
}
```

**Fetch volume details:**
```
GET /volumes/{volume_id}.json
```

**Response structure:**
```json
{
  "volume": {
    "id": 12345,
    "title": "My Knitting Book",
    "volume_attachments": [
      {
        "id": 111,
        "filename": "my-knitting-book_DE.pdf",
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

**Download the PDF:**
```python
# DON'T pass API auth= - but a logged-in browser session (cookies) IS
# needed, see section 10.1!
response = requests.get(
    volume["volume_attachments"][0]["ravelry_download_url"],
    cookies=browser_cookies,
    stream=True,
)
```

---

## 4. Pattern downloads (individually purchased)

### 4.1 Fetch pattern details

```
GET /patterns/{pattern_id}.json
```

**Relevant fields for downloads:**

| Field | Type | Meaning |
|---|---|---|
| `ravelry_download` | bool | True = purchasable/purchased directly on Ravelry |
| `pdf_in_library` | bool | True = PDF already present in your own library |
| `volumes_in_library` | list | Volume IDs under which the pattern sits in your own library |
| `download_location` | list | Download info (see below) |
| `downloadable` | bool | True = available as a download at all |

**`download_location` structure:**
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

> **Note (corrected after live testing):** `download_location[].url` is a
> **purchase/checkout URL** (`/purchase/...` or `/download/{id}/checkout`), NOT
> a direct download URL for already purchased content! It redirects to the
> cart/checkout page, not to the PDF. For a pattern that's already in your
> own library (`pdf_in_library: true`), the download must instead go through
> `volumes_in_library` → `/volumes/{id}.json` → `volume_attachments[].ravelry_download_url`
> (see section 8). This URL also requires a logged-in browser session (see
> section 10.1).

### 4.2 Pattern search in your own library

```
GET /people/{username}/library/search.json?type=pattern
```

Returns patterns that are in the library (as individually purchased Ravelry downloads).

**Response structure (without type=pdf):**
```json
{
  "volumes": [...],
  "patterns": [
    {
      "id": 67890,
      "name": "My Favorite Pattern",
      "permalink": "my-favorite-pattern",
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

Ravelry has two types:

### 5.1 Designer bundles (purchase results in individual patterns)

When a designer bundles multiple patterns into one bundle, all contained patterns are added to the library **individually** on purchase. Each pattern then shows up as `ravelry_download: true` in the library.  
→ Found via library search with `type=pattern` / `type=ravelry`.

### 5.2 User-owned bundles (favorites collections)

```
GET /people/{username}/bundles/list.json
GET /people/{username}/bundles/{bundle_id}.json
POST /people/{username}/bundles/create.json
```

These are user-defined collections (like Pinterest boards) - not purchase objects, no downloads.

---

## 6. All important API endpoints (overview)

### Patterns

| Endpoint | Method | Description |
|---|---|---|
| `/patterns/search.json` | GET | Global pattern search |
| `/patterns/{id}.json` | GET | Pattern details (incl. download_location) |
| `/patterns.json` | GET | Multiple patterns at once (IDs as a param) |
| `/patterns/{id}/comments.json` | GET | Comments on a pattern |
| `/patterns/{id}/projects.json` | GET | Projects that use this pattern |
| `/pattern_sources/{id}.json` | GET | Source book/magazine details |
| `/pattern_sources/search.json` | GET | Search source books |
| `/pattern_sources/{id}/patterns.json` | GET | Patterns from a source |
| `/pattern_categories.json` | GET | All pattern categories |

**Important search filters for `/patterns/search.json`:**

| Parameter | Values | Example |
|---|---|---|
| `availability` | `free`, `ravelry`, `purchase` | `availability=+ravelry` (Ravelry downloads only) |
| `craft` | `knitting`, `crochet` | |
| `fit` | `adult`, `baby`, `child` | |
| `pc` | Pattern categories | `sweater`, `hat`, `shawl` |
| `sort` | `projects`, `favorites`, `date` | |
| `page`, `page_size` | | |

### Projects

| Endpoint | Method | Description |
|---|---|---|
| `/projects/{username}/list.json` | GET | All of a user's projects |
| `/projects/{username}/{id}.json` | GET | Project details |
| `/projects/search.json` | GET | Global project search |
| `/projects/{username}/create.json` | POST | Create a new project |
| `/projects/{username}/{id}.json` | POST | Update a project |
| `/projects/{username}/{id}.json` | DELETE | Delete a project |

### Stash (yarn stash)

| Endpoint | Method | Description |
|---|---|---|
| `/people/{username}/stash/list.json` | GET | Stash list |
| `/people/{username}/stash/{id}.json` | GET | Stash entry details |
| `/people/{username}/stash/create.json` | POST | Create a new stash entry |
| `/people/{username}/stash/{id}.json` | POST | Update a stash entry |
| `/people/{username}/stash/{id}.json` | DELETE | Delete |
| `/people/{username}/stash/unified/list.json` | GET | Unified stash list |
| `/stash/search.json` | GET | Global stash search |

### Yarns

| Endpoint | Method | Description |
|---|---|---|
| `/yarns/search.json` | GET | Search yarns |
| `/yarns/{id}.json` | GET | Yarn details |
| `/yarns.json` | GET | Multiple yarns (IDs as a param) |
| `/yarn_weights.json` | GET | All yarn weights (Lace, Fingering, DK, ...) |

### Queue

| Endpoint | Method | Description |
|---|---|---|
| `/people/{username}/queue/list.json` | GET | List the queue |
| `/people/{username}/queue/{id}.json` | GET | Queue entry details |
| `/people/{username}/queue/create.json` | POST | Create an entry |
| `/people/{username}/queue/{id}/update.json` | POST | Update an entry |
| `/people/{username}/queue/{id}/reposition.json` | POST | Change order |
| `/people/{username}/queue/{id}.json` | DELETE | Delete |

### Favorites

| Endpoint | Method | Description |
|---|---|---|
| `/people/{username}/favorites/list.json` | GET | Favorites list |
| `/people/{username}/favorites/{id}.json` | GET | Favorite details |
| `/people/{username}/favorites/create.json` | POST | Create |
| `/people/{username}/favorites/{id}.json` | POST | Update |
| `/people/{username}/favorites/{id}.json` | DELETE | Delete |
| `/people/{username}/favorites/{id}/add_to_bundle.json` | POST | Add to bundle |
| `/people/{username}/favorites/{id}/remove_from_bundle.json` | POST | Remove from bundle |

### People / Users

| Endpoint | Method | Description |
|---|---|---|
| `/current_user.json` | GET | Your own user |
| `/people/{username}.json` | GET | User details |
| `/people/{username}.json` | POST | Update user data |

### Needles

| Endpoint | Method | Description |
|---|---|---|
| `/people/{username}/needles/list.json` | GET | Needle collection |
| `/needles/sizes.json` | GET | All needle sizes |
| `/needles/types.json` | GET | All needle types |

### Shops

| Endpoint | Method | Description |
|---|---|---|
| `/shops/search.json` | GET | Search shops |
| `/shops/{id}.json` | GET | Shop details |

### Volumes / Library

| Endpoint | Method | Description |
|---|---|---|
| `/people/{username}/library/search.json` | GET | Search the library |
| `/volumes/{id}.json` | GET | Volume details (incl. attachments) |
| `/volumes/create.json` | POST | Create a volume |
| `/volumes/{id}.json` | DELETE | Delete a volume |

### Other

| Endpoint | Method | Description |
|---|---|---|
| `/color_families.json` | GET | Color families |
| `/yarn_weights.json` | GET | Yarn weights |
| `/groups/search.json` | GET | Search groups |
| `/forums/sets.json` | GET | Forum categories |
| `/forums/{id}/topics.json` | GET | Topics in a forum |
| `/messages/list.json` | GET | Messages |
| `/comments/create.json` | POST | Create a comment |

---

## 7. Pagination

All list endpoints return a `paginator`:
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

Standard iteration:
```python
while page <= data["paginator"]["page_count"]:
    page += 1
```

---

## 8. PDF download workflow (complete, live-verified Oct. 2026)

**Core insight:** EVERY library entry - whether an eBook, collection,
individual pattern, or bundle part - is technically a **Volume** object.
The PDF download works the same way for all variants:

```
library/search.json  (type=pdf OR no filter)
    └─> volumes[]  (summary: id, pattern_id, pattern_source_id, patterns_count, has_downloads)
         └─> /volumes/{id}.json
               └─> volume_attachments[].ravelry_download_url
                     └─> download WITH browser session cookie (see 10.1)
```

Distinguishing volume types based on the summary fields:

| Type | Identifying feature |
|---|---|
| **eBook/book** | `pattern_id` set, `patterns_count == 1`, usually several `volume_attachments` (e.g. NL/US version + chart) |
| **Individual pattern** | identical to the eBook case - Ravelry internally creates a 1:1 volume for every pattern purchase |
| **Collection** | `pattern_source_id` set, `patterns_count > 1`, ONE volume with multiple attachments (1 per contained pattern) |
| **Bundle** | multiple volumes with `patterns_count == 1`, but an identical `created_at` timestamp (= same checkout) |

### 8.1 download_location.url is NOT a download URL

`pattern.download_location[].url` (e.g. `http://www.ravelry.com/purchase/.../123`
or `/download/{id}/checkout`) is a **purchase/checkout URL**. It leads to
the cart, not to the PDF - even with a valid browser session. If the
pattern has already been purchased (`pattern.pdf_in_library: true`), the
download must instead go through `pattern.volumes_in_library[0]` →
`/volumes/{id}.json`.

### 8.2 Pattern with an external PDF (e.g. from the designer's website)

```
/patterns/{id}.json
    └─> pdf_url  (external URL, not always functional)
    └─> download_location[].url  (type="web", "external", etc.)
```

> These can't be downloaded automatically - the designer's website may require its own authentication.

---

## 9. Important data structures

### Pattern (shortened)

```json
{
  "id": 67890,
  "name": "Sock Pattern",
  "permalink": "sock-pattern",
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

### Volume (shortened)

```json
{
  "id": 12345,
  "title": "My Knitting Book",
  "volume_attachments": [
    {
      "id": 111,
      "filename": "MyKnittingBook_DE.pdf",
      "content_type": "application/pdf",
      "ravelry_download_url": "https://downloads.ravelry.com/...",
      "file_size": 5242880
    },
    {
      "id": 112,
      "filename": "MyKnittingBook_EN.pdf",
      "content_type": "application/pdf",
      "ravelry_download_url": "https://downloads.ravelry.com/...",
      "file_size": 4800000
    }
  ],
  "pattern_source": {
    "id": 555,
    "name": "My Knitting Book",
    "author": "Designer Name"
  }
}
```

### Stash entry (shortened)

```json
{
  "id": 44444,
  "name": "Merino Blue",
  "yarn_company_name": "Lang Yarns",
  "yarn_name": "Merino 120",
  "colorway_name": "Indigo",
  "location": "Box 3",
  "strands_per_skein": 1,
  "grams_per_skein": 100,
  "yards_per_skein": 130,
  "skeins": 3.5
}
```

---

## 10. Rate limits & best practices

- No officially documented rate limit, but a **0.3s pause** between requests is recommended
- Max. `page_size = 100` (some endpoints less)
- For REST API calls (`api.ravelry.com`), always set `auth=AUTH` (Basic Auth with the API keys)

### 10.1 Two separate auth systems for downloads (important!)

Live-tested (October 2026) with real purchased/added library content:

| Download type | URL pattern | Auth required |
|---|---|---|
| **Free pattern** | `/dls/{id}/{code}` | None - redirects directly to a time-limited, pre-signed S3 URL |
| **Everything else** (`volume_attachments[].ravelry_download_url`) | `/download/{id}/checkout` | **Logged-in browser session** (cookies) - API keys are NOT accepted |

Without a valid session, `/download/{id}/checkout` returns an HTML login
page (`<title>Ravelry</title>` or `<title>Ravelry: Checking out...</title>`)
instead of the PDF - recognizable by the `Content-Type: text/html` and the
missing `%PDF-` signature in the response body.

**Practical solution:** automate browser login via [Playwright](https://playwright.dev/python/) -
open a visible Chromium window, the user logs in manually (2FA-capable),
then grab `context.cookies()` and pass them along with all subsequent
`requests.get(url, cookies=...)` calls. Session cookies typically last
several days to weeks and can be cached locally, so you don't need to log
in again on every run. Implemented in `ravelry_common.py`
(`ensure_browser_login()`).

---

## 11. Non-public / documentation gaps

The official Ravelry API docs are only accessible after logging in.
Live-verified (October 2026, see sections 8 and 10.1):

- ✅ **Clarified:** `library/search.json` ALWAYS returns `volumes[]` (no
  separate `patterns[]` array) - even for individual patterns and bundle
  parts. Relevant fields: `id`, `pattern_id`, `pattern_source_id`,
  `patterns_count`, `has_downloads`, `created_at`.
- ✅ **Clarified:** `download_location[].url` is a purchase URL, not the
  PDF download URL (see 8.1).
- ✅ **Clarified:** `volume_attachments[].ravelry_download_url` requires a
  logged-in browser session, not the REST API keys (see 10.1).

Still unclear / may change:

- Exact expiry time of the browser session cookies
- Whether/how behavior differs for OAuth2 apps (instead of a personal key)
- Exact `type` values for `library/search.json` beyond `pdf`
