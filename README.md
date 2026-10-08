# Ravelry Tools

Python scripts for downloading patterns and PDFs from your own Ravelry account.

---

## Requirements

- [uv](https://docs.astral.sh/uv/) installed (`uv 0.12+`)
- Python 3.12 (managed automatically by uv)
- A Ravelry account with [Pro/Developer access](https://www.ravelry.com/pro/developer)
- For browser login (paid downloads, see below): install the Playwright
  browser once (see setup step 3)

---

## Setup

### 1. Get API keys

Create an app at [ravelry.com/pro/developer](https://www.ravelry.com/pro/developer):
- Auth type: **Basic Auth: Personal Key**
- Produces two keys: **Access Key** (= username) and **Personal Key** (= password)

### 2. Create a `.env` file

```
RAVELRY_ACCESS_KEY=your_access_key
RAVELRY_PERSONAL_KEY=your_personal_key
```

The `.env` file lives in the project root and is excluded from commits via `.gitignore`.

### 3. Install the Playwright browser (one time)

Downloading paid content requires an actual browser login (see the
"Browser login" section below for details). For this, install the
Chromium binaries from Playwright once:

```bash
uv run --project . python3 -m playwright install chromium
```

On WSL/Linux, additional system libraries may be needed
(audio/Mesa/font/X11) for the browser to start in headful mode:

```bash
sudo uv run --project . python3 -m playwright install-deps chromium
```

---

## Running the scripts

All scripts are **self-contained and runnable** with `uv run` - they declare
their dependencies in the file header (`# /// script`), and uv installs
them automatically into a temporary venv. Shared logic (API access,
downloads, browser login) lives in `ravelry_common.py`, which is imported
by all scripts.

### Download test (`ravelry-test.py`)

Tests all pattern variants (free, paid, individual purchase, eBook,
collection, bundle) and downloads the first example of each. Useful for
debugging and exploring the API structure.

```bash
uv run ravelry-test.py
# or via the project environment:
uv run --project . ravelry-test.py
```

Downloads end up in `test_downloads/`.

### Full library download (`ravelry-downloader.py`)

Downloads all PDFs from your own Ravelry library (eBooks/collections +
individual patterns), with skip logic for files that already exist.

```bash
uv run ravelry-downloader.py
# or via the project environment:
uv run --project . ravelry-downloader.py
```

Downloads end up in `ravelry_downloads/`.

The downloader processes three types of library entries:

1. **eBooks/collections with their own PDF bundle** (`type=pdf` volumes)
2. **Individually purchased patterns** (own 1:1 volume per pattern)
3. **Reference collections** - collections that have NO PDF bundle of
   their own, but only reference multiple individually linked patterns
   (e.g. yarn manufacturer collections like Scheepjes "YARN - The After
   Party", but also old magazine issues added to the library purely for
   research purposes, without having been bought on Ravelry)

**Two separate control files with DIFFERENT logic:**

| File | Logic | Applies to |
|---|---|---|
| `ravelry_downloads/ignore.txt` | **EXCLUDE** - everything is downloaded except what's listed here as a filename fragment (e.g. `_NL.pdf`) | ALL downloads, including files within a reference collection activated via `collections.txt` |
| `ravelry_downloads/collections.txt` | **INCLUDE** - nothing is downloaded unless a collection is explicitly activated here | ONLY reference collections (variant 3) |

Both files are automatically created with example content on first run.

**`collections.txt` syntax** (a catalog for review, opt-in instead of opt-out):

```
collection:213142                 <- ACTIVE, will be downloaded
#collection:393415                 <- INACTIVE (default for new finds)
```

On every run, the script automatically adds newly found reference
collections as **inactive** (with a leading `#`) - this builds a
complete, searchable catalog of all collections ever found, without
anything being downloaded by accident. To activate, simply remove the
leading `#` before the line. The script remembers which IDs have already
been added to the catalog in `ravelry_downloads/.collection_sync.json`,
so a known collection doesn't get appended again on the next run -
regardless of whether you've since activated it or not.

**Processing order** (within each stage, in the order the Ravelry API
paginates the library - no custom sort order applied):

1. Volumes with their own PDF bundle (eBooks, collections with attachments)
2. Individually purchased patterns
3. Reference collections (only activated ones, members downloaded individually)
4. Transparency report for entries without a download path
5. Log of entries not downloaded

**Log files** (overwritten on every run, so they show the state of the
*last* run, not cumulative across multiple runs):

| File | Content |
|---|---|
| `ravelry_downloads/skipped_non_downloadable.txt` | Library entries without a recognizable download path (e.g. externally acquired single magazine issues or Etsy purchases that are in the library only for research purposes) |
| `ravelry_downloads/excluded_by_ignore.txt` | Files/collections that were NOT downloaded in this run (due to `ignore.txt` or missing opt-in in `collections.txt`) |

Both are pure logs, not a control mechanism - exclusions/opt-ins are
still controlled by `ignore.txt` or `collections.txt` directly.

> 🔗 `ravelry_downloads/` can (and for larger libraries, should) be a
> **symlink to a NAS directory** instead of living locally on disk -
> especially under WSL, where local disk usage feeds into the dynamically
> growing VHDX (see the warning below). `ensure_download_dir()` detects
> symlinks and aborts in a controlled way if the link target (NAS mount)
> is currently unreachable, instead of accidentally creating a new local
> folder. The `tests/` suite never touches `ravelry_downloads/` at all -
> it works exclusively in pytest's own `tmp_path` directories.

> ⚠️ For a large library (hundreds of entries, sometimes double-digit MB
> per PDF), a full run can require significant disk space. Under WSL, the
> virtual disk (VHDX) grows dynamically along with it and does **not**
> shrink automatically after deleting the files. If needed:
> `wsl --manage <Distro> --compact` (Windows 11) or `diskpart` +
> `compact vdisk`.

### View stash & projects (`ravelry.py`)

Prints a Pandas overview of your own projects and yarn stash.

```bash
uv run ravelry.py
```

---

## Tests

The logic that doesn't depend on network/browser access (ignore filter,
collection sync, filename sanitization, PDF signature check) is covered
by `pytest` under `tests/`. Tests run entirely offline with synthetic
fixtures - no real API calls, no browser, no downloads.

```bash
uv run --project . pytest -v
```

| Test file | Covers |
|---|---|
| `test_ignore_logic.py` | `ignore.txt` parsing (EXCLUDE) and `collections.txt` parsing (INCLUDE), inline comments |
| `test_collection_sync.py` | Reference collection detection, catalog sync (inactive entries), idempotency |
| `test_categorization.py` | Categorization of all library entry shapes, transparency report |
| `test_excluded_log.py` | Log of entries not downloaded |
| `test_ravelry_common.py` | Filename sanitization, PDF detection, cookie validation |

For every change to `ravelry-downloader.py` or `ravelry_common.py`, these
tests should pass before the next real run - they catch logic errors
(e.g. in the `ignore.txt` parser) without having to touch your own
library or download PDFs.

**Important: the tests use exclusively synthetic fixtures** (hardcoded
example dicts, e.g. in `test_categorization.py` the real titles from a
live analysis of the library). They make **no** real API calls. This
means:

- If your real Ravelry library changes (new patterns, new collections,
  deleted entries), all tests stay green unchanged - they don't react to
  that automatically, since they never talk to the real data.
- The tests protect against **logic errors** in the code (e.g. the bug
  found where inline comments in `ignore.txt` weren't being stripped
  correctly), but not against Ravelry delivering a **new, previously
  unknown data shape** in the future that isn't covered by any of the
  five categories in `categorize_item()`.
- If a new construct shows up in the real library that doesn't currently
  fit, it would end up as `orphan` or `single_pattern_source` and become
  visible in the `skipped_non_downloadable.txt` report (never silently
  disappear) - but a test for it would have to be added manually once
  such a case actually occurs (the same way `test_categorization.py` came
  about after the live analysis).

---

## Browser login (for paid downloads)

Ravelry separates two auth systems:

- **REST API** (`api.ravelry.com`): Basic Auth with the API keys from
  `.env`. Works for all `GET` queries and for **free** pattern downloads
  (`/dls/{id}/{code}` URLs redirect directly to a pre-signed S3 URL).
- **File download** (`www.ravelry.com`): For **all other** PDFs
  (purchased individual patterns, eBooks, collections, bundle parts), a
  logged-in **browser session** (cookie login) is required. The API keys
  are not accepted here - without a valid session you end up on the login
  page instead of the PDF.

Both scripts (`ravelry-test.py`, `ravelry-downloader.py`) handle this automatically:

1. A download attempt returns HTML (login page) instead of a PDF.
2. The script then automatically opens a **visible** Chromium window
   (Playwright) with the Ravelry login page.
3. You log in there **manually** (username/password, 2FA if needed) - the
   script waits for up to 5 minutes.
4. After a successful login, the session cookies are saved locally
   (`.ravelry_session.json`) and reused for all further downloads in this
   **and subsequent** runs, until the session expires.

```python
# ravelry_common.py - central function
ensure_browser_login(force: bool = False) -> dict  # returns cookies as a dict
clear_browser_session()                            # deletes the saved session
```

> 🔒 `.ravelry_session.json` contains login cookies and is excluded from
> commits via `.gitignore`. Never share or commit it!

**Login troubleshooting:**
- Browser doesn't open / fails to start → install the Playwright browser +
  system deps (see setup step 3).
- Login hangs / times out after 5 minutes → restart the script, deleting
  `.ravelry_session.json` first if needed.
- Downloads suddenly fail after a password change → the old session is
  invalid; delete `.ravelry_session.json`, the next run will prompt for a
  fresh login.

---

## Alternative invocation via the `uv` project environment

The project also has a local `uv` environment (`.venv`). To use it:

```bash
# Install / update dependencies
uv sync

# Run the script in the project environment
uv run --project . ravelry-downloader.py
```

> Difference: `uv run script.py` (without `--project`) uses an isolated,
> throwaway venv from the script header. `uv run --project .` uses the
> persistent project venv from
> `pyproject.toml` - useful when additional packages are installed
> locally, or when Playwright browser binaries have already been
> installed for this venv.

---

## Project structure

```
.
├── .env                     # API keys (do not commit!)
├── .ravelry_session.json    # Browser login cookies (generated, do not commit!)
├── .python-version          # Python 3.12 (for uv)
├── pyproject.toml           # Project definition
├── uv.lock                  # Locked dependencies
│
├── ravelry_common.py        # Shared helper: API, downloads, browser login
├── ravelry-test.py          # API test: download the first PDF of every variant
├── ravelry-downloader.py    # Full library download
├── ravelry.py                # Stash & projects as a DataFrame
│
├── tests/                    # pytest suite (offline, no real API calls)
│   ├── conftest.py
│   ├── test_ignore_logic.py
│   ├── test_collection_sync.py
│   ├── test_categorization.py
│   ├── test_excluded_log.py
│   └── test_ravelry_common.py
│
├── docs/
│   └── ravelry-api-kb.md   # API documentation / knowledge base
│
├── ravelry_downloads/       # Downloader target folder (created automatically, may be a NAS symlink)
│   ├── ignore.txt           # EXCLUDE: filename filter (created on first run)
│   ├── collections.txt     # INCLUDE: collection opt-in catalog (created on first run)
│   ├── .collection_sync.json  # Remembers IDs already added to the catalog
│   ├── skipped_non_downloadable.txt  # Log: entries without a download path
│   └── excluded_by_ignore.txt        # Log: entries not downloaded
└── test_downloads/          # Test script target folder (created automatically)
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `pyenv: version '3.12' is not installed` | `uv python install 3.12` |
| `401 Unauthorized` | Check the keys in `.env`; personal key ≠ password |
| Download doesn't return a PDF | The API response is printed in the terminal - check `Content-Type` and the preview |
| `symbol lookup error` when starting the browser | Missing system deps: `sudo uv run --project . python3 -m playwright install-deps chromium` |
| Browser starts, but no window is visible | On WSL: WSLg must be active (`echo $DISPLAY` should show `:0` or similar) |
| Login timeout after 5 minutes | Restart the script; if the problem persists, delete `.ravelry_session.json` |
| `SSL` error | `uv run --no-verify-ssl ravelry-downloader.py` (corporate proxy) |
