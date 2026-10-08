"""
Tests for the categorization of library entries in ravelry-downloader.py:
categorize_item(), find_unhandled_items(), report_unhandled_items().

Background: a live analysis of the real Ravelry library showed 858
entries across 6 different data "shapes". Three of these fell into none
of the three download paths (volumes, individual patterns, reference
collections):

  - 114x external patterns (download_location.type == "external") -
    already filtered out earlier via process_individual_patterns(), since
    pdf_in_library is missing. Not part of this categorization (which only
    concerns items that have NO pattern_id path at all).
  - 19x 'single_pattern_source': pattern_source_id set, patterns_count==1,
    but no pattern_id (e.g. "Star Book No. 169", "Filati Häkeln 02") -
    confirmed externally acquired single magazine issues, not
    downloadable.
  - 2x 'orphan': neither pattern_id nor pattern_source_id (e.g. "Noctiluca
    Dress" from Etsy, "Crochet Every Way Stitch Dictionary" as a reference
    book).

These tests ensure that such entries continue to NOT be downloaded (as
confirmed by the user: "external patterns should not be downloaded"), but
unlike before are visibly reported instead of being silently swallowed.
"""

from __future__ import annotations


# Real (anonymized) examples from the six observed library shapes.

VOLUME_BUNDLE = {
    "title": "Bibelot",
    "pattern_id": 7517377,
    "pattern_source_id": None,
    "patterns_count": 1,
    "has_downloads": True,
}

INDIVIDUAL_PATTERN = {
    "title": "Alto Mare Wrap",
    "pattern_id": 845320,
    "pattern_source_id": None,
    "patterns_count": 1,
    "has_downloads": False,
}

REFERENCE_COLLECTION = {
    "title": "YARN - The After Party",
    "pattern_id": None,
    "pattern_source_id": 213142,
    "patterns_count": 147,
    "has_downloads": False,
}

COLLECTION_WITH_OWN_BUNDLE = {
    "title": "Shawl Collection to Crochet 4",
    "pattern_id": None,
    "pattern_source_id": 239508,
    "patterns_count": 4,
    "has_downloads": True,
}

# "Star Book No. 169, Socks Socks Socks and Mittens, Too" - an externally
# acquired single magazine issue, per the user: "Star Book [...] externally
# acquired [...] magazines"
SINGLE_PATTERN_SOURCE_MAGAZINE = {
    "title": "Star Book No. 169, Socks Socks Socks and Mittens, Too",
    "pattern_id": None,
    "pattern_source_id": 160865,
    "patterns_count": 1,
    "has_downloads": False,
}

# "Noctiluca Dress" - per the user: "a dress purchased on Etsy"
ORPHAN_ETSY_PATTERN = {
    "title": "Noctiluca Dress",
    "pattern_id": None,
    "pattern_source_id": None,
    "patterns_count": 0,
    "has_downloads": False,
}

# "Crochet Every Way Stitch Dictionary" - per the user: "it's a book, that's fine"
# (a reference work deliberately added to the library, not an individual pattern)
ORPHAN_REFERENCE_BOOK = {
    "title": "Crochet Every Way Stitch Dictionary: 125 Essential Stitches to Crochet in Three Ways",
    "pattern_id": None,
    "pattern_source_id": None,
    "patterns_count": 0,
    "has_downloads": False,
}


class TestCategorizeItem:
    def test_volume_bundle(self, downloader):
        assert downloader.categorize_item(VOLUME_BUNDLE) == "volume_bundle"

    def test_individual_pattern(self, downloader):
        assert downloader.categorize_item(INDIVIDUAL_PATTERN) == "individual_pattern"

    def test_reference_collection(self, downloader):
        assert downloader.categorize_item(REFERENCE_COLLECTION) == "reference_collection"

    def test_collection_with_own_bundle_counts_as_volume_bundle(self, downloader):
        """has_downloads=True takes precedence over patterns_count>1: a
        collection WITH its own PDF bundle is handled by process_volumes,
        not by process_reference_collections."""
        assert downloader.categorize_item(COLLECTION_WITH_OWN_BUNDLE) == "volume_bundle"

    def test_single_pattern_source_magazine(self, downloader):
        assert downloader.categorize_item(SINGLE_PATTERN_SOURCE_MAGAZINE) == "single_pattern_source"

    def test_orphan_etsy_pattern(self, downloader):
        assert downloader.categorize_item(ORPHAN_ETSY_PATTERN) == "orphan"

    def test_orphan_reference_book(self, downloader):
        assert downloader.categorize_item(ORPHAN_REFERENCE_BOOK) == "orphan"

    def test_every_item_gets_exactly_one_category(self, downloader):
        """Every item must fall into EXACTLY one of the five categories -
        no gaps, no overlap."""
        valid_categories = {
            "volume_bundle", "individual_pattern", "reference_collection",
            "single_pattern_source", "orphan",
        }
        items = [
            VOLUME_BUNDLE, INDIVIDUAL_PATTERN, REFERENCE_COLLECTION,
            COLLECTION_WITH_OWN_BUNDLE, SINGLE_PATTERN_SOURCE_MAGAZINE,
            ORPHAN_ETSY_PATTERN, ORPHAN_REFERENCE_BOOK,
        ]
        for item in items:
            assert downloader.categorize_item(item) in valid_categories


class TestFindUnhandledItems:
    def test_finds_single_pattern_source_and_orphans(self, downloader):
        items = [
            VOLUME_BUNDLE, INDIVIDUAL_PATTERN, REFERENCE_COLLECTION,
            SINGLE_PATTERN_SOURCE_MAGAZINE, ORPHAN_ETSY_PATTERN, ORPHAN_REFERENCE_BOOK,
        ]

        unhandled = downloader.find_unhandled_items(items)

        assert SINGLE_PATTERN_SOURCE_MAGAZINE in unhandled
        assert ORPHAN_ETSY_PATTERN in unhandled
        assert ORPHAN_REFERENCE_BOOK in unhandled

    def test_excludes_downloadable_categories(self, downloader):
        items = [VOLUME_BUNDLE, INDIVIDUAL_PATTERN, REFERENCE_COLLECTION]

        unhandled = downloader.find_unhandled_items(items)

        assert unhandled == []

    def test_empty_input(self, downloader):
        assert downloader.find_unhandled_items([]) == []


class TestReportUnhandledItems:
    def test_writes_report_file_with_titles(self, downloader, isolated_download_dir):
        items = [VOLUME_BUNDLE, SINGLE_PATTERN_SOURCE_MAGAZINE, ORPHAN_ETSY_PATTERN]

        downloader.report_unhandled_items(items)

        report_path = isolated_download_dir / "skipped_non_downloadable.txt"
        assert report_path.exists()
        content = report_path.read_text(encoding="utf-8")
        assert "Star Book No. 169" in content
        assert "Noctiluca Dress" in content
        # Downloadable items must NOT show up in the report
        assert "Bibelot" not in content

    def test_no_report_file_when_nothing_unhandled(self, downloader, isolated_download_dir):
        downloader.report_unhandled_items([VOLUME_BUNDLE, INDIVIDUAL_PATTERN])

        report_path = isolated_download_dir / "skipped_non_downloadable.txt"
        assert not report_path.exists()

    def test_report_does_not_trigger_any_download(self, downloader, isolated_download_dir):
        """report_unhandled_items() may ONLY log/report, never call
        try_download() or otherwise trigger network I/O."""
        items = [SINGLE_PATTERN_SOURCE_MAGAZINE, ORPHAN_ETSY_PATTERN]

        # No download directory content expected besides the report file
        downloader.report_unhandled_items(items)

        created_files = list(isolated_download_dir.iterdir())
        assert created_files == [isolated_download_dir / "skipped_non_downloadable.txt"]

    def test_report_overwrites_on_each_run(self, downloader, isolated_download_dir):
        downloader.report_unhandled_items([SINGLE_PATTERN_SOURCE_MAGAZINE])
        downloader.report_unhandled_items([ORPHAN_ETSY_PATTERN])

        content = (isolated_download_dir / "skipped_non_downloadable.txt").read_text(encoding="utf-8")
        assert "Star Book No. 169" not in content
        assert "Noctiluca Dress" in content
