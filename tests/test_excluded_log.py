"""
Tests for the log of entries not downloaded (write_excluded_log(),
EXCLUDED_LOG_FILE) in ravelry-downloader.py.

Covers:
  - try_download() records files filtered by ignore.txt in the log
  - process_reference_collections() records collections NOT activated via
    collections.txt in the log (INCLUDE logic: without an opt-in, nothing
    is downloaded)
  - the log is overwritten on every main() run (not cumulative)
  - with no exclusions in this run, NO log file is created
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
        """A download that is NOT filtered by ignore.txt must not show up
        in the excluded log (regardless of whether it succeeds)."""
        # Mock download_with_login_fallback so no real network call happens
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
        """INCLUDE logic: a collection that is NOT in collection_includes
        is not downloaded and ends up in the excluded log."""
        downloader.process_reference_collections(
            collections=[IGNORED_COLLECTION],
            ignore_patterns=[],
            collection_includes=[],  # nothing activated
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
        """Simulates two main() runs: excluded_this_run.clear() + new
        entries + write_excluded_log() -> the log may only show the LAST
        run, not the sum of all runs."""
        downloader.excluded_this_run.append("Lauf1_Datei.pdf  (Datei-Filter, Pattern)")
        downloader.write_excluded_log()

        downloader.excluded_this_run.clear()  # main() does this at the start of every run
        downloader.excluded_this_run.append("Lauf2_Datei.pdf  (Datei-Filter, Pattern)")
        downloader.write_excluded_log()

        content = (isolated_download_dir / "excluded_by_ignore.txt").read_text(encoding="utf-8")
        assert "Lauf1_Datei.pdf" not in content
        assert "Lauf2_Datei.pdf" in content
