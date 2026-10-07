"""
Pytest-Konfiguration und gemeinsame Fixtures für die Ravelry-Testsuite.

Scripts mit Bindestrich im Dateinamen (z.B. ravelry-downloader.py) sind keine
gültigen Python-Modulnamen und können daher nicht per `import` eingebunden
werden. Die `downloader`-Fixture lädt sie stattdessen über importlib.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # damit `import ravelry_common` funktioniert


def _load_script_module(filename: str, modname: str):
    """Lädt ein Script mit Bindestrich-Dateinamen als importierbares Modul.

    Der `if __name__ == "__main__":`-Guard in den Scripts verhindert, dass
    main() (= echte API-Calls, echte Downloads) beim Import ausgeführt wird,
    da __name__ hier auf `modname` steht statt auf "__main__".
    """
    spec = importlib.util.spec_from_file_location(modname, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[modname] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def downloader():
    """Lädt ravelry-downloader.py einmal pro Testsession als Modul."""
    return _load_script_module("ravelry-downloader.py", "ravelry_downloader_module")


@pytest.fixture
def isolated_download_dir(tmp_path, downloader, monkeypatch):
    """
    Isoliert DOWNLOAD_DIR / IGNORE_FILE / COLLECTION_SYNC_FILE /
    SKIPPED_REPORT_FILE / EXCLUDED_LOG_FILE in ein temporäres Verzeichnis,
    damit Tests niemals die echten Dateien unter ravelry_downloads/
    (insb. die echte ignore.txt) berühren. Setzt außerdem den modul-globalen
    excluded_this_run-Zustand zurück, damit Tests sich nicht gegenseitig
    über try_download()-Aufrufe hinweg beeinflussen.
    """
    download_dir = tmp_path / "ravelry_downloads"
    download_dir.mkdir()
    ignore_file = download_dir / "ignore.txt"
    sync_file = download_dir / ".collection_sync.json"
    skipped_report_file = download_dir / "skipped_non_downloadable.txt"
    excluded_log_file = download_dir / "excluded_by_ignore.txt"

    monkeypatch.setattr(downloader, "DOWNLOAD_DIR", str(download_dir))
    monkeypatch.setattr(downloader, "IGNORE_FILE", str(ignore_file))
    monkeypatch.setattr(downloader, "COLLECTION_SYNC_FILE", str(sync_file))
    monkeypatch.setattr(downloader, "SKIPPED_REPORT_FILE", str(skipped_report_file))
    monkeypatch.setattr(downloader, "EXCLUDED_LOG_FILE", str(excluded_log_file))
    downloader.excluded_this_run.clear()

    return download_dir
