"""
Tests für die Steuer-Dateien in ravelry-downloader.py:
  - ignore.txt (EXCLUDE-Logik, Dateinamen-Filter, gilt für ALLE Downloads)
    load_ignore_patterns(), is_ignored()
  - collections.txt (INCLUDE-Logik, nur Referenz-Collections)
    load_collection_includes(), is_collection_included()

Deckt u.a. den Bug ab, der beim manuellen Testen auffiel: automatisch
generierte Inline-Kommentare ('collection:213142  # Titel (147 Pattern)')
wurden beim Wiedereinlesen NICHT vom Wert getrennt.
"""

from __future__ import annotations

import os


def write_file(path, content: str):
    path.write_text(content, encoding="utf-8")


class TestLoadIgnorePatterns:
    """ignore.txt: reine EXCLUDE-Logik für Dateinamen, keine Collection-Syntax."""

    def test_creates_default_file_when_missing(self, downloader, isolated_download_dir):
        ignore_file = downloader.IGNORE_FILE
        assert not os.path.exists(ignore_file)

        filename_patterns = downloader.load_ignore_patterns(ignore_file)

        assert filename_patterns == []
        assert os.path.exists(ignore_file)

    def test_parses_plain_filename_patterns(self, downloader, isolated_download_dir):
        ignore_file = isolated_download_dir / "ignore.txt"
        write_file(ignore_file, "_NL.pdf\n_FR.pdf\n# ein Kommentar\n\n")

        filename_patterns = downloader.load_ignore_patterns(str(ignore_file))

        assert filename_patterns == ["_nl.pdf", "_fr.pdf"]

    def test_strips_inline_comment_from_filename_line(self, downloader, isolated_download_dir):
        ignore_file = isolated_download_dir / "ignore.txt"
        write_file(ignore_file, "_NL.pdf  # niederländische Version\n")

        filename_patterns = downloader.load_ignore_patterns(str(ignore_file))

        assert filename_patterns == ["_nl.pdf"]

    def test_blank_and_comment_only_lines_ignored(self, downloader, isolated_download_dir):
        ignore_file = isolated_download_dir / "ignore.txt"
        write_file(ignore_file, "\n   \n# nur ein Kommentar\n#\n")

        filename_patterns = downloader.load_ignore_patterns(str(ignore_file))

        assert filename_patterns == []

    def test_collection_syntax_is_not_special_in_ignore_file(self, downloader, isolated_download_dir):
        """ignore.txt kennt KEINE Collection-Syntax mehr (die lebt jetzt in
        collections.txt) – eine 'collection:...'-Zeile wird hier wie ein
        normaler (wenn auch unsinniger) Dateinamen-Filter behandelt."""
        ignore_file = isolated_download_dir / "ignore.txt"
        write_file(ignore_file, "collection:213142\n")

        filename_patterns = downloader.load_ignore_patterns(str(ignore_file))

        assert filename_patterns == ["collection:213142"]


class TestIsIgnored:
    def test_matches_substring_case_insensitive(self, downloader):
        assert downloader.is_ignored("Muster_NL.pdf", ["_nl.pdf"]) is True

    def test_no_match_when_pattern_absent(self, downloader):
        assert downloader.is_ignored("Muster_US.pdf", ["_nl.pdf"]) is False

    def test_empty_pattern_list_never_matches(self, downloader):
        assert downloader.is_ignored("irgendwas.pdf", []) is False


class TestLoadCollectionIncludes:
    """collections.txt: INCLUDE-Logik – nur AKTIVE (nicht '#'-präfixierte)
    'collection:...'-Zeilen zählen."""

    def test_creates_default_file_when_missing(self, downloader, isolated_download_dir):
        collections_file = downloader.COLLECTIONS_FILE
        assert not os.path.exists(collections_file)

        includes = downloader.load_collection_includes(collections_file)

        assert includes == []
        assert os.path.exists(collections_file)

    def test_active_line_is_included(self, downloader, isolated_download_dir):
        collections_file = isolated_download_dir / "collections.txt"
        write_file(collections_file, "collection:213142\n")

        includes = downloader.load_collection_includes(str(collections_file))

        assert includes == ["213142"]

    def test_inactive_line_with_leading_hash_is_not_included(self, downloader, isolated_download_dir):
        collections_file = isolated_download_dir / "collections.txt"
        write_file(collections_file, "#collection:213142\n")

        includes = downloader.load_collection_includes(str(collections_file))

        assert includes == []

    def test_strips_inline_comment_from_active_line(self, downloader, isolated_download_dir):
        """Regressionstest: die automatisch generierten Zeilen tragen einen
        Inline-Kommentar ('# Titel (n Pattern)'), der nicht Teil des Werts
        werden darf."""
        collections_file = isolated_download_dir / "collections.txt"
        write_file(
            collections_file,
            "collection:213142  # YARN - The After Party (147 Pattern)\n",
        )

        includes = downloader.load_collection_includes(str(collections_file))

        assert includes == ["213142"]

    def test_inactive_line_with_inline_comment_is_not_included(self, downloader, isolated_download_dir):
        """Das ist exakt das Format, das sync_new_reference_collections()
        automatisch erzeugt: inaktiv UND mit Inline-Kommentar."""
        collections_file = isolated_download_dir / "collections.txt"
        write_file(
            collections_file,
            "#collection:213142  # YARN - The After Party (147 Pattern)\n",
        )

        includes = downloader.load_collection_includes(str(collections_file))

        assert includes == []

    def test_include_by_title_fragment(self, downloader, isolated_download_dir):
        collections_file = isolated_download_dir / "collections.txt"
        write_file(collections_file, "collection:Yarn - The After Party\n")

        includes = downloader.load_collection_includes(str(collections_file))

        assert includes == ["yarn - the after party"]

    def test_pure_comment_lines_are_ignored(self, downloader, isolated_download_dir):
        collections_file = isolated_download_dir / "collections.txt"
        write_file(collections_file, "# Das ist nur ein Kommentar, keine Collection-Zeile\n")

        includes = downloader.load_collection_includes(str(collections_file))

        assert includes == []

    def test_mixed_active_and_inactive_lines(self, downloader, isolated_download_dir):
        collections_file = isolated_download_dir / "collections.txt"
        write_file(
            collections_file,
            "collection:213142  # Aktiv\n"
            "#collection:393415  # Inaktiv\n"
            "collection:41932  # Auch aktiv\n",
        )

        includes = downloader.load_collection_includes(str(collections_file))

        assert set(includes) == {"213142", "41932"}


class TestIsCollectionIncluded:
    def test_matches_by_pattern_source_id(self, downloader):
        collection = {"pattern_source_id": 213142, "title": "YARN - The After Party"}
        assert downloader.is_collection_included(collection, ["213142"]) is True

    def test_matches_by_title_fragment(self, downloader):
        collection = {"pattern_source_id": 213142, "title": "YARN - The After Party"}
        assert downloader.is_collection_included(collection, ["after party"]) is True

    def test_no_match_for_unrelated_include(self, downloader):
        collection = {"pattern_source_id": 213142, "title": "YARN - The After Party"}
        assert downloader.is_collection_included(collection, ["irgendwas anderes"]) is False

    def test_no_match_with_empty_include_list(self, downloader):
        """INCLUDE-Logik: ohne jede Freigabe wird NICHTS geladen (Standard
        ist aus, nicht an)."""
        collection = {"pattern_source_id": 213142, "title": "YARN - The After Party"}
        assert downloader.is_collection_included(collection, []) is False

    def test_integration_with_inline_comment_from_sync(self, downloader, isolated_download_dir):
        """End-to-End: Eine von sync_new_reference_collections() generierte
        (inaktive) Zeile darf erst NACH Entfernen des '#' tatsächlich greifen."""
        collections_file = isolated_download_dir / "collections.txt"

        write_file(
            collections_file,
            "#collection:213142  # YARN - The After Party (147 Pattern)\n",
        )
        includes_inactive = downloader.load_collection_includes(str(collections_file))
        collection = {"pattern_source_id": 213142, "title": "YARN - The After Party"}
        assert downloader.is_collection_included(collection, includes_inactive) is False

        write_file(
            collections_file,
            "collection:213142  # YARN - The After Party (147 Pattern)\n",
        )
        includes_active = downloader.load_collection_includes(str(collections_file))
        assert downloader.is_collection_included(collection, includes_active) is True
