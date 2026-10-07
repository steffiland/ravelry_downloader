#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "requests",
#   "python-dotenv",
# ]
# ///

import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

ACCESS_KEY = os.getenv("RAVELRY_ACCESS_KEY")
PERSONAL_KEY = os.getenv("RAVELRY_PERSONAL_KEY")
BASE_URL = "https://api.ravelry.com"
AUTH = (ACCESS_KEY, PERSONAL_KEY)

# 1. Ersten PDF-Eintrag aus der Bibliothek holen
res = requests.get(f"{BASE_URL}/people/username/library/search.json?type=pdf&page_size=1", auth=AUTH)
vol_id = res.json()["volumes"][0]["id"]

# 2. Details abrufen
vol_res = requests.get(f"{BASE_URL}/volumes/{vol_id}.json", auth=AUTH)
data = vol_res.json()

print("--- KEYS IN VOLUME ---")
print(list(data.get("volume", {}).keys()))

print("\n--- VOLLSTÄNDIGE VOLUME DETAILS ---")
print(json.dumps(data, indent=2))

