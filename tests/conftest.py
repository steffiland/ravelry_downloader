"""
Pytest configuration and shared fixtures for the Ravelry test suite.

Scripts with a hyphen in the filename (e.g. ravelry-downloader.py) are not
valid Python module names and therefore can't be included via `import`.
The `downloader` fixture loads them instead via importlib.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # so that `import ravelry_common` works


def _load_script_module(filename: str, modname: str):
    """Loads a script with a hyphenated filename as an importable module.

    The `if __name__ == "__main__":` guard in the scripts prevents main()
    (= real API calls, real downloads) from running on import, since
    __name__ is set to `modname` here instead of "__main__".
    """
    spec = importlib.util.spec_from_file_location(modname, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[modname] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def downloader():
    """Loads ravelry-downloader.py once per test session as a module."""
    return _load_script_module("ravelry-downloader.py", "ravelry_downloader_module")


@pytest.fixture
def isolated_download_dir(tmp_path, downloader, monkeypatch):
    """
    Isolates DOWNLOAD_DIR / IGNORE_FILE / COLLECTION_SYNC_FILE /
    SKIPPED_REPORT_FILE / EXCLUDED_LOG_FILE in a temporary directory, so
    that tests never touch the real files under ravelry_downloads/ (in
    particular the real ignore.txt). Also resets the module-global
    excluded_this_run state, so tests don't affect each other across
    try_download() calls.
    """
    download_dir = tmp_path / "ravelry_downloads"
    download_dir.mkdir()
    ignore_file = download_dir / "ignore.txt"
    collections_file = download_dir / "collections.txt"
    sync_file = download_dir / ".collection_sync.json"
    skipped_report_file = download_dir / "skipped_non_downloadable.txt"
    excluded_log_file = download_dir / "excluded_by_ignore.txt"

    monkeypatch.setattr(downloader, "DOWNLOAD_DIR", str(download_dir))
    monkeypatch.setattr(downloader, "IGNORE_FILE", str(ignore_file))
    monkeypatch.setattr(downloader, "COLLECTIONS_FILE", str(collections_file))
    monkeypatch.setattr(downloader, "COLLECTION_SYNC_FILE", str(sync_file))
    monkeypatch.setattr(downloader, "SKIPPED_REPORT_FILE", str(skipped_report_file))
    monkeypatch.setattr(downloader, "EXCLUDED_LOG_FILE", str(excluded_log_file))
    downloader.excluded_this_run.clear()

    return download_dir
