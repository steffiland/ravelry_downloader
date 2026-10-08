#!/usr/bin/env -S uv run
######!/usr/bin/env -S uv run --project .
# /// script
# dependencies = [
#   "requests",
#   "pandas",
#   "python-dotenv",
# ]
# ///

import pandas as pd

from ravelry_common import api_get, get_current_username


def fetch_all_projects(username: str) -> pd.DataFrame:
    """Fetches all of a user's projects (including pagination) and returns a DataFrame."""
    projects = []
    page = 1
    page_size = 50

    while True:
        data = api_get(f"/projects/{username}/list.json", {"page": page, "page_size": page_size})

        current_page_projects = data.get("projects", [])
        if not current_page_projects:
            break

        projects.extend(current_page_projects)

        # Check whether there are more pages
        paginator = data.get("paginator", {})
        if page >= paginator.get("page_count", 1):
            break

        page += 1

    # Convert to a Pandas DataFrame
    df = pd.DataFrame(projects)
    return df


def fetch_all_stash(username: str) -> pd.DataFrame:
    """Fetches a user's complete stash and returns a DataFrame."""
    stash_items = []
    page = 1
    page_size = 50

    while True:
        data = api_get(f"/people/{username}/stash/list.json", {"page": page, "page_size": page_size})

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
    print(f"Logged in as: {username}\n")

    # --- 1. Fetch projects ---
    print("Loading projects...")
    df_projects = fetch_all_projects(username)

    if not df_projects.empty:
        # Select important columns (if present)
        cols = [
            "name",
            "status_name",
            "progress",
            "craft_name",
            "started",
            "completed",
        ]
        available_cols = [c for c in cols if c in df_projects.columns]

        print("\n--- Projects overview ---")
        print(df_projects[available_cols].head())

        # Example analysis: count projects by status
        if "status_name" in df_projects.columns:
            print("\nProjects by status:")
            print(df_projects["status_name"].value_counts())

    # --- 2. Fetch stash ---
    print("\nLoading stash...")
    df_stash = fetch_all_stash(username)

    if not df_stash.empty:
        cols_stash = [
            "name",
            "yarn_company_name",
            "location",
            "strands_per_skein",
        ]
        available_stash_cols = [c for c in cols_stash if c in df_stash.columns]

        print("\n--- Stash overview ---")
        print(df_stash[available_stash_cols].head())

        # Optional: export as CSV/Excel
        # df_projects.to_csv("ravelry_projects.csv", index=False)
        # df_stash.to_csv("ravelry_stash.csv", index=False)
