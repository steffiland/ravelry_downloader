#!/usr/bin/env -S uv run
######!/usr/bin/env -S uv run --project .
# /// script
# dependencies = [
#   "requests",
#   "pandas",
#   "python-dotenv",
# ]
# ///

import os
import requests
import pandas as pd
from dotenv import load_dotenv

# .env-Datei laden
load_dotenv()

# Schlüssel aus den Umgebungsvariablen lesen
ACCESS_KEY = os.getenv("RAVELRY_ACCESS_KEY")
PERSONAL_KEY = os.getenv("RAVELRY_PERSONAL_KEY")

# Prüfen, ob die Keys vorhanden sind
if not ACCESS_KEY or not PERSONAL_KEY:
    raise ValueError("Fehler: RAVELRY_ACCESS_KEY oder RAVELRY_PERSONAL_KEY nicht in der .env-Datei gefunden!")

BASE_URL = "https://api.ravelry.com"
AUTH = (ACCESS_KEY, PERSONAL_KEY)


def get_current_username() -> str:
    """Ermittelt den Benutzernamen des API-Inhabers."""
    response = requests.get(f"{BASE_URL}/current_user.json", auth=AUTH)
    response.raise_for_status()
    return response.json()["user"]["username"]


def fetch_all_projects(username: str) -> pd.DataFrame:
    """Ruft alle Projekte eines Users ab (inkl. Paginierung) und gibt ein DataFrame zurück."""
    projects = []
    page = 1
    page_size = 50

    while True:
        url = f"{BASE_URL}/projects/{username}/list.json"
        params = {"page": page, "page_size": page_size}

        response = requests.get(url, auth=AUTH, params=params)
        response.raise_for_status()
        data = response.json()

        current_page_projects = data.get("projects", [])
        if not current_page_projects:
            break

        projects.extend(current_page_projects)

        # Prüfen, ob es noch weitere Seiten gibt
        paginator = data.get("paginator", {})
        if page >= paginator.get("page_count", 1):
            break

        page += 1

    # In Pandas DataFrame umwandeln
    df = pd.DataFrame(projects)
    return df


def fetch_all_stash(username: str) -> pd.DataFrame:
    """Ruft den kompletten Stash eines Users ab und gibt ein DataFrame zurück."""
    stash_items = []
    page = 1
    page_size = 50

    while True:
        url = f"{BASE_URL}/people/{username}/stash/list.json"
        params = {"page": page, "page_size": page_size}

        response = requests.get(url, auth=AUTH, params=params)
        response.raise_for_status()
        data = response.json()

        current_page_items = data.get("stash", [])
        if not current_page_items:
            break

        stash_items.extend(current_page_items)

        paginator = data.get("paginator", {})
        if page >= paginator.get("page_count", 1):
            break

        page += 1

    df = pd.DataFrame(stash_items)
    return df


if __name__ == "__main__":
    username = get_current_username()
    print(f"Eingeloggt als: {username}\n")

    # --- 1. Projekte abrufen ---
    print("Lade Projekte...")
    df_projects = fetch_all_projects(username)

    if not df_projects.empty:
        # Wichtige Spalten auswählen (falls vorhanden)
        cols = [
            "name",
            "status_name",
            "progress",
            "craft_name",
            "started",
            "completed",
        ]
        available_cols = [c for c in cols if c in df_projects.columns]

        print("\n--- Projekte Übersicht ---")
        print(df_projects[available_cols].head())

        # Beispiel-Auswertung: Projekte nach Status zählen
        if "status_name" in df_projects.columns:
            print("\nProjekte nach Status:")
            print(df_projects["status_name"].value_counts())

    # --- 2. Stash abrufen ---
    print("\nLade Stash...")
    df_stash = fetch_all_stash(username)

    if not df_stash.empty:
        cols_stash = [
            "name",
            "yarn_company_name",
            "location",
            "strands_per_skein",
        ]
        available_stash_cols = [c for c in cols_stash if c in df_stash.columns]

        print("\n--- Stash Übersicht ---")
        print(df_stash[available_stash_cols].head())

        # Optional: Als CSV/Excel exportieren
        # df_projects.to_csv("ravelry_projects.csv", index=False)
        # df_stash.to_csv("ravelry_stash.csv", index=False)

