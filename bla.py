#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "requests",
#   "python-dotenv",
# ]
# ///

import os
import re
import time
import requests
from dotenv import load_dotenv

load_dotenv()

ACCESS_KEY = os.getenv("RAVELRY_ACCESS_KEY")
PERSONAL_KEY = os.getenv("RAVELRY_PERSONAL_KEY")
COOKIES = os.getenv("RAVELRY_SESSION_COOKIE")

if not ACCESS_KEY or not PERSONAL_KEY:
    raise ValueError("Error: RAVELRY_ACCESS_KEY or RAVELRY_PERSONAL_KEY is missing!")

BASE_URL = "https://api.ravelry.com"
AUTH = (ACCESS_KEY, PERSONAL_KEY)
DOWNLOAD_DIR = "ravelry_downloads"
IGNORE_FILE = os.path.join(DOWNLOAD_DIR, "ignore.txt")


def sanitize_filename(filename: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", filename)


def get_current_username() -> str:
    response = requests.get(f"{BASE_URL}/current_user.json", auth=AUTH)
    response.raise_for_status()
    return response.json()["user"]["username"]


def load_ignore_patterns(ignore_filepath: str) -> list[str]:
    if not os.path.exists(ignore_filepath):
        os.makedirs(os.path.dirname(ignore_filepath), exist_ok=True)
        with open(ignore_filepath, "w", encoding="utf-8") as f:
            f.write("# Ignore patterns (e.g. _NL.pdf)\n")
        return []

    patterns = []
    with open(ignore_filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line.lower())
    return patterns


def is_ignored(filename: str, ignore_patterns: list[str]) -> bool:
    filename_lower = filename.lower()
    return any(p in filename_lower for p in ignore_patterns)


def fetch_library_volumes(username: str) -> list:
    volumes = []
    page = 1
    page_size = 50

    print("Loading library overview...")
    while True:
        url = f"{BASE_URL}/people/{username}/library/search.json"
        params = {"page": page, "page_size": page_size, "type": "pdf"}
        res = requests.get(url, auth=AUTH, params=params)
        res.raise_for_status()

        data = res.json()
        current_volumes = data.get("volumes", [])
        if not current_volumes:
            break

        volumes.extend(current_volumes)
        paginator = data.get("paginator", {})
        if page >= paginator.get("page_count", 1):
            break
        page += 1

    print(f"Found a total of {len(volumes)} digital entries in the library.\n")
    return volumes


def get_file_url_from_api(attachment_id: int) -> str | None:
    """Queries the attachment details directly via the API to get the real S3 link."""
    url = f"{BASE_URL}/attachments/{attachment_id}.json"
    res = requests.get(url, auth=AUTH)
    if res.status_code == 200:
        att_data = res.json().get("attachment", {})
        # file_url is the direct S3 URL
        return att_data.get("file_url") or att_data.get("url")
    return None


def download_file(direct_url: str, target_path: str):
    """Downloads the file from S3 (WITHOUT Ravelry Basic Auth, since S3 rejects the auth header)."""
    res = requests.get(direct_url, stream=True)
    res.raise_for_status()

    content_type = res.headers.get("Content-Type", "")
    chunks = res.iter_content(chunk_size=8192)
    first_chunk = next(chunks, None)

    if not first_chunk:
        raise ValueError("File is empty (0 bytes).")

    # Check for an actual PDF header
    if not first_chunk.startswith(b"%PDF-") and "application/pdf" not in content_type.lower():
        preview = first_chunk[:300].decode("utf-8", errors="ignore")
        raise ValueError(f"Response is not a PDF (Content-Type: {content_type}). Preview:\n{preview.strip()}")

    with open(target_path, "wb") as f:
        f.write(first_chunk)
        for chunk in chunks:
            if chunk:
                f.write(chunk)


def process_library_downloads(username: str, volumes: list):
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    ignore_patterns = load_ignore_patterns(IGNORE_FILE)

    downloaded_count = 0
    skipped_ignore_count = 0

    for index, vol_summary in enumerate(volumes, start=1):
        vol_id = vol_summary.get("id")
        title = vol_summary.get("title") or f"Volume_{vol_id}"
        print(f"[{index}/{len(volumes)}] Checking: {title}")

        vol_url = f"{BASE_URL}/volumes/{vol_id}.json"
        res = requests.get(vol_url, auth=AUTH)
        if res.status_code != 200:
            print(f"  ⚠️ Could not load details (HTTP {res.status_code})")
            continue

        vol_data = res.json().get("volume", {})
        attachments = vol_data.get("volume_attachments", [])

        for att in attachments:
            att_id = att.get("id")
            file_name = att.get("filename") or f"{sanitize_filename(title)}.pdf"
            clean_file_name = sanitize_filename(file_name)

            if not clean_file_name.lower().endswith(".pdf"):
                clean_file_name += ".pdf"

            if is_ignored(clean_file_name, ignore_patterns):
                print(f"  🚫 Skipped (filtered by ignore.txt): {clean_file_name}")
                skipped_ignore_count += 1
                continue

            target_path = os.path.join(DOWNLOAD_DIR, clean_file_name)

            if os.path.exists(target_path):
                print(f"  ➜ Skipped (already present): {clean_file_name}")
                continue

            try:
                # Get the real S3 link via the attachment API (file_url)
                direct_url = att.get("file_url")
                if not direct_url and att_id:
                    direct_url = get_file_url_from_api(att_id)

                if not direct_url:
                    print(f"  ⚠️ No direct file link available for: {clean_file_name}")
                    continue

                print(f"  ⬇️ Downloading: {clean_file_name} ...")
                download_file(direct_url, target_path)
                downloaded_count += 1
                time.sleep(0.3)

            except Exception as e:
                print(f"  ❌ Error downloading {clean_file_name}: {e}")

    print(f"\nDone! Downloaded {downloaded_count} new PDF(s).")


if __name__ == "__main__":
    username = get_current_username()
    print(f"Logged in as: {username}\n")
    volumes = fetch_library_volumes(username)
    process_library_downloads(username, volumes)
