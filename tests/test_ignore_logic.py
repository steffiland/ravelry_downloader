"""
Tests for the control files in ravelry-downloader.py:
  - ignore.txt (EXCLUDE logic, filename filter, applies to ALL downloads)
    load_ignore_patterns(), is_ignored()
  - collections.txt (INCLUDE logic, only reference collections)
    load_collection_includes(), is_collection_included()

Covers, among other things, the bug that surfaced during manual testing:
automatically generated inline comments
('collection:213142  # Title (147 patterns)') were NOT separated from the
value when read back in.
"""

from __future__ import annotations

import os


def write_file(path, content: str):
    path.write_text(content, encoding="utf-8")


class TestLoadIgnorePatterns:
    """ignore.txt: pure EXCLUDE logic for filenames, no collection syntax."""

    def test_creates_default_file_when_missing(self, downloader, isolated_download_dir):
        ignore_file = downloader.IGNORE_FILE
        assert not os.path.exists(ignore_file)

        filename_patterns = downloader.load_ignore_patterns(ignore_file)

        assert filename_patterns == []
        assert os.path.exists(ignore_file)

    def test_parses_plain_filename_patterns(self, downloader, isolated_download_dir):
        ignore_file = isolated_download_dir / "ignore.txt"
        write_file(ignore_file, "_NL.pdf\n_FR.pdf\n# a comment\n\n")

        filename_patterns = downloader.load_ignore_patterns(str(ignore_file))

        assert filename_patterns == ["_nl.pdf", "_fr.pdf"]

    def test_strips_inline_comment_from_filename_line(self, downloader, isolated_download_dir):
        ignore_file = isolated_download_dir / "ignore.txt"
        write_file(ignore_file, "_NL.pdf  # Dutch version\n")

        filename_patterns = downloader.load_ignore_patterns(str(ignore_file))

        assert filename_patterns == ["_nl.pdf"]

    def test_blank_and_comment_only_lines_ignored(self, downloader, isolated_download_dir):
        ignore_file = isolated_download_dir / "ignore.txt"
        write_file(ignore_file, "\n   \n# just a comment\n#\n")

        filename_patterns = downloader.load_ignore_patterns(str(ignore_file))

        assert filename_patterns == []

    def test_collection_syntax_is_not_special_in_ignore_file(self, downloader, isolated_download_dir):
        """ignore.txt no longer knows any collection syntax (that now lives
        in collections.txt) - a 'collection:...' line is treated here like
        a normal (if nonsensical) filename filter."""
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
    """collections.txt: INCLUDE logic - only ACTIVE (not '#'-prefixed)
    'collection:...' lines count."""

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
        """Regression test: the automatically generated lines carry an
        inline comment ('# Title (n patterns)') that must not become part
        of the value."""
        collections_file = isolated_download_dir / "collections.txt"
        write_file(
            collections_file,
            "collection:213142  # YARN - The After Party (147 patterns)\n",
        )

        includes = downloader.load_collection_includes(str(collections_file))

        assert includes == ["213142"]

    def test_inactive_line_with_inline_comment_is_not_included(self, downloader, isolated_download_dir):
        """This is exactly the format that
        sync_new_reference_collections() generates automatically: inactive
        AND with an inline comment."""
        collections_file = isolated_download_dir / "collections.txt"
        write_file(
            collections_file,
            "#collection:213142  # YARN - The After Party (147 patterns)\n",
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
        write_file(collections_file, "# This is just a comment, not a collection line\n")

        includes = downloader.load_collection_includes(str(collections_file))

        assert includes == []

    def test_mixed_active_and_inactive_lines(self, downloader, isolated_download_dir):
        collections_file = isolated_download_dir / "collections.txt"
        write_file(
            collections_file,
            "collection:213142  # Active\n"
            "#collection:393415  # Inactive\n"
            "collection:41932  # Also active\n",
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
        assert downloader.is_collection_included(collection, ["something else"]) is False

    def test_no_match_with_empty_include_list(self, downloader):
        """INCLUDE logic: with no opt-in at all, NOTHING is downloaded (the
        default is off, not on)."""
        collection = {"pattern_source_id": 213142, "title": "YARN - The After Party"}
        assert downloader.is_collection_included(collection, []) is False

    def test_integration_with_inline_comment_from_sync(self, downloader, isolated_download_dir):
        """End-to-end: a line generated by sync_new_reference_collections()
        (inactive) must only take effect AFTER the '#' is removed."""
        collections_file = isolated_download_dir / "collections.txt"

        write_file(
            collections_file,
            "#collection:213142  # YARN - The After Party (147 patterns)\n",
        )
        includes_inactive = downloader.load_collection_includes(str(collections_file))
        collection = {"pattern_source_id": 213142, "title": "YARN - The After Party"}
        assert downloader.is_collection_included(collection, includes_inactive) is False

        write_file(
            collections_file,
            "collection:213142  # YARN - The After Party (147 patterns)\n",
        )
        includes_active = downloader.load_collection_includes(str(collections_file))
        assert downloader.is_collection_included(collection, includes_active) is True
