"""
Tests für das Log der nicht heruntergeladenen Einträge
(write_excluded_log(), EXCLUDED_LOG_FILE) in ravelry-downloader.py.

Deckt ab:
  - try_download() trägt per ignore.txt gefilterte Dateien ins Log ein
  - process_reference_collections() trägt per collections.txt NICHT
    aktivierte Collections ins Log ein (INCLUDE-Logik: ohne Freigabe wird
    nicht geladen)
  - das Log wird bei jedem main()-Lauf überschrieben (nicht kumulativ)
  - ohne Ausschlüsse in diesem Lauf wird KEINE Log-Datei angelegt
"""

from __future__ import annotations


IGNORED_COLLECTION = {
    "id": 592424159,
    "pattern_id": None,
    "pattern_source_id": 213142,
    "title": "YARN - The After Party",
    "patterns_count": 147,
    "has_downloads": False,
}


class TestTryDownloadLogsExcludedFiles:
    def test_filtered_filename_is_recorded(self, downloader, isolated_download_dir):
        downloader.try_download(
            url="https://example.invalid/some.pdf",
            filename="Muster_NL.pdf",
            label="Pattern",
            ignore_patterns=["_nl.pdf"],
        )

        assert len(downloader.excluded_this_run) == 1
        assert "Muster_NL.pdf" in downloader.excluded_this_run[0]
        assert "Pattern" in downloader.excluded_this_run[0]

    def test_non_filtered_download_is_not_recorded(self, downloader, isolated_download_dir, monkeypatch):
        """Ein Download, der NICHT per ignore.txt gefiltert wird, darf nicht
        im Excluded-Log auftauchen (unabhängig davon ob er erfolgreich ist)."""
        # download_with_login_fallback mocken, damit kein echter Netzwerkcall passiert
        monkeypatch.setattr(
            downloader, "download_with_login_fallback",
            lambda url, path, cookies: (True, "ok", cookies),
        )

        downloader.try_download(
            url="https://example.invalid/some.pdf",
            filename="Muster_US.pdf",
            label="Pattern",
            ignore_patterns=["_nl.pdf"],
        )

        assert downloader.excluded_this_run == []


class TestProcessReferenceCollectionsLogsExcluded:
    def test_not_included_collection_is_recorded(self, downloader, isolated_download_dir):
        """INCLUDE-Logik: eine Collection, die NICHT in collection_includes
        steht, wird nicht geladen und landet im Excluded-Log."""
        downloader.process_reference_collections(
            collections=[IGNORED_COLLECTION],
            ignore_patterns=[],
            collection_includes=[],  # nichts aktiviert
        )

        assert len(downloader.excluded_this_run) == 1
        assert "YARN - The After Party" in downloader.excluded_this_run[0]
        assert "213142" in downloader.excluded_this_run[0]


class TestWriteExcludedLog:
    def test_writes_log_file_with_entries(self, downloader, isolated_download_dir):
        downloader.excluded_this_run.append("Muster_NL.pdf  (Datei-Filter, Pattern)")

        downloader.write_excluded_log()

        log_path = isolated_download_dir / "excluded_by_ignore.txt"
        assert log_path.exists()
        assert "Muster_NL.pdf" in log_path.read_text(encoding="utf-8")

    def test_no_log_file_when_nothing_excluded(self, downloader, isolated_download_dir):
        downloader.write_excluded_log()

        log_path = isolated_download_dir / "excluded_by_ignore.txt"
        assert not log_path.exists()

    def test_log_overwritten_not_appended_across_runs(self, downloader, isolated_download_dir):
        """Simuliert zwei main()-Läufe: excluded_this_run.clear() + neue
        Einträge + write_excluded_log() -> das Log darf nur den LETZTEN
        Lauf zeigen, nicht die Summe aller Läufe."""
        downloader.excluded_this_run.append("Lauf1_Datei.pdf  (Datei-Filter, Pattern)")
        downloader.write_excluded_log()

        downloader.excluded_this_run.clear()  # main() tut das zu Beginn jedes Laufs
        downloader.excluded_this_run.append("Lauf2_Datei.pdf  (Datei-Filter, Pattern)")
        downloader.write_excluded_log()

        content = (isolated_download_dir / "excluded_by_ignore.txt").read_text(encoding="utf-8")
        assert "Lauf1_Datei.pdf" not in content
        assert "Lauf2_Datei.pdf" in content
