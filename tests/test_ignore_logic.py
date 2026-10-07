"""
Tests für die ignore.txt-Verarbeitung in ravelry-downloader.py:
  - Datei-Substring-Filter (is_ignored)
  - Collection-Ausschlüsse per 'collection:<id-oder-titel>' (is_collection_ignored)
  - Inline-Kommentare in ignore.txt-Zeilen werden korrekt abgeschnitten

Deckt den Bug ab, der beim manuellen Testen auffiel: die automatisch von
sync_new_reference_collections() erzeugten Zeilen ('collection:213142  #
Titel (147 Pattern)') wurden beim Wiedereinlesen NICHT vom Kommentar
getrennt, wodurch is_collection_ignored() nie zutraf.
"""

from __future__ import annotations


def write_ignore_file(path, content: str):
    path.write_text(content, encoding="utf-8")


class TestLoadIgnorePatterns:
    def test_creates_default_file_when_missing(self, downloader, isolated_download_dir):
        ignore_file = downloader.IGNORE_FILE
        assert not __import__("os").path.exists(ignore_file)

        filename_patterns, collection_excludes = downloader.load_ignore_patterns(ignore_file)

        assert filename_patterns == []
        assert collection_excludes == []
        assert __import__("os").path.exists(ignore_file)

    def test_parses_plain_filename_patterns(self, downloader, isolated_download_dir):
        ignore_file = isolated_download_dir / "ignore.txt"
        write_ignore_file(ignore_file, "_NL.pdf\n_FR.pdf\n# ein Kommentar\n\n")

        filename_patterns, collection_excludes = downloader.load_ignore_patterns(str(ignore_file))

        assert filename_patterns == ["_nl.pdf", "_fr.pdf"]
        assert collection_excludes == []

    def test_parses_collection_exclude_by_id(self, downloader, isolated_download_dir):
        ignore_file = isolated_download_dir / "ignore.txt"
        write_ignore_file(ignore_file, "collection:213142\n")

        _, collection_excludes = downloader.load_ignore_patterns(str(ignore_file))

        assert collection_excludes == ["213142"]

    def test_strips_inline_comment_from_collection_line(self, downloader, isolated_download_dir):
        """Regressionstest für den gefundenen Bug: Inline-Kommentare (wie sie
        sync_new_reference_collections() automatisch anhängt) dürfen nicht
        Teil des Exclude-Werts werden."""
        ignore_file = isolated_download_dir / "ignore.txt"
        write_ignore_file(
            ignore_file,
            "collection:213142  # YARN - The After Party (147 Pattern)\n",
        )

        _, collection_excludes = downloader.load_ignore_patterns(str(ignore_file))

        assert collection_excludes == ["213142"]

    def test_strips_inline_comment_from_filename_line(self, downloader, isolated_download_dir):
        ignore_file = isolated_download_dir / "ignore.txt"
        write_ignore_file(ignore_file, "_NL.pdf  # niederländische Version\n")

        filename_patterns, _ = downloader.load_ignore_patterns(str(ignore_file))

        assert filename_patterns == ["_nl.pdf"]

    def test_collection_exclude_by_title_fragment(self, downloader, isolated_download_dir):
        ignore_file = isolated_download_dir / "ignore.txt"
        write_ignore_file(ignore_file, "collection:Yarn - The After Party\n")

        _, collection_excludes = downloader.load_ignore_patterns(str(ignore_file))

        assert collection_excludes == ["yarn - the after party"]

    def test_blank_and_comment_only_lines_ignored(self, downloader, isolated_download_dir):
        ignore_file = isolated_download_dir / "ignore.txt"
        write_ignore_file(ignore_file, "\n   \n# nur ein Kommentar\n#\n")

        filename_patterns, collection_excludes = downloader.load_ignore_patterns(str(ignore_file))

        assert filename_patterns == []
        assert collection_excludes == []


class TestIsIgnored:
    def test_matches_substring_case_insensitive(self, downloader):
        assert downloader.is_ignored("Muster_NL.pdf", ["_nl.pdf"]) is True

    def test_no_match_when_pattern_absent(self, downloader):
        assert downloader.is_ignored("Muster_US.pdf", ["_nl.pdf"]) is False

    def test_empty_pattern_list_never_matches(self, downloader):
        assert downloader.is_ignored("irgendwas.pdf", []) is False


class TestIsCollectionIgnored:
    def test_matches_by_pattern_source_id(self, downloader):
        collection = {"pattern_source_id": 213142, "title": "YARN - The After Party"}
        assert downloader.is_collection_ignored(collection, ["213142"]) is True

    def test_matches_by_title_fragment(self, downloader):
        collection = {"pattern_source_id": 213142, "title": "YARN - The After Party"}
        assert downloader.is_collection_ignored(collection, ["after party"]) is True

    def test_no_match_for_unrelated_exclude(self, downloader):
        collection = {"pattern_source_id": 213142, "title": "YARN - The After Party"}
        assert downloader.is_collection_ignored(collection, ["irgendwas anderes"]) is False

    def test_no_match_with_empty_exclude_list(self, downloader):
        collection = {"pattern_source_id": 213142, "title": "YARN - The After Party"}
        assert downloader.is_collection_ignored(collection, []) is False

    def test_integration_with_inline_comment_from_sync(self, downloader, isolated_download_dir):
        """End-to-End: Eine von sync_new_reference_collections() generierte
        Zeile muss nach dem Wiedereinlesen tatsächlich greifen."""
        ignore_file = isolated_download_dir / "ignore.txt"
        write_ignore_file(
            ignore_file,
            "collection:213142  # YARN - The After Party (147 Pattern)\n",
        )
        _, collection_excludes = downloader.load_ignore_patterns(str(ignore_file))

        collection = {"pattern_source_id": 213142, "title": "YARN - The After Party"}
        assert downloader.is_collection_ignored(collection, collection_excludes) is True
