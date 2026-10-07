"""
Tests für die Kategorisierung von Library-Einträgen in ravelry-downloader.py:
categorize_item(), find_unhandled_items(), report_unhandled_items().

Hintergrund: Eine Live-Analyse der echten Ravelry-Library zeigte 858 Einträge
in 6 unterschiedlichen Daten-"Shapes". Drei davon griffen in keinem der drei
Download-Pfade (Volumes, Einzelpattern, Referenz-Collections):

  - 114x externe Pattern (download_location.type == "external") – fallen
    schon vorher via process_individual_patterns() raus, da pdf_in_library
    fehlt. Nicht Teil dieser Kategorisierung (die betrifft nur Items, die
    GAR KEINEN pattern_id-Pfad haben).
  - 19x 'single_pattern_source': pattern_source_id gesetzt, patterns_count==1,
    aber kein pattern_id (z.B. "Star Book No. 169", "Filati Häkeln 02") –
    bestätigt extern erworbene Zeitschriften-Einzelhefte, nicht downloadbar.
  - 2x 'orphan': weder pattern_id noch pattern_source_id (z.B. "Noctiluca
    Dress" von Etsy, "Crochet Every Way Stitch Dictionary" als Referenzbuch).

Diese Tests stellen sicher, dass solche Einträge weiterhin NICHT herunter-
geladen werden (wie vom Nutzer bestätigt: "externe patterns sollen nicht
runtergeladen werden"), aber im Gegensatz zu vorher sichtbar reportet statt
lautlos verschluckt werden.
"""

from __future__ import annotations


# Reale (anonymisierte) Beispiele aus den sechs beobachteten Library-Shapes.

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

# "Star Book No. 169, Socks Socks Socks and Mittens, Too" – extern erworbenes
# Zeitschriften-Einzelheft, laut Nutzer: "Star Book [...] extern erworbene[...]
# Zeitschriften"
SINGLE_PATTERN_SOURCE_MAGAZINE = {
    "title": "Star Book No. 169, Socks Socks Socks and Mittens, Too",
    "pattern_id": None,
    "pattern_source_id": 160865,
    "patterns_count": 1,
    "has_downloads": False,
}

# "Noctiluca Dress" – laut Nutzer: "bei Etsy erworbenes Dress"
ORPHAN_ETSY_PATTERN = {
    "title": "Noctiluca Dress",
    "pattern_id": None,
    "pattern_source_id": None,
    "patterns_count": 0,
    "has_downloads": False,
}

# "Crochet Every Way Stitch Dictionary" – laut Nutzer: "ist ein Buch, das passt"
# (bewusst in die Library aufgenommenes Referenzwerk, kein Einzelpattern)
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
        """has_downloads=True hat Vorrang vor patterns_count>1: eine Collection
        MIT eigenem PDF-Bundle wird von process_volumes behandelt, nicht von
        process_reference_collections."""
        assert downloader.categorize_item(COLLECTION_WITH_OWN_BUNDLE) == "volume_bundle"

    def test_single_pattern_source_magazine(self, downloader):
        assert downloader.categorize_item(SINGLE_PATTERN_SOURCE_MAGAZINE) == "single_pattern_source"

    def test_orphan_etsy_pattern(self, downloader):
        assert downloader.categorize_item(ORPHAN_ETSY_PATTERN) == "orphan"

    def test_orphan_reference_book(self, downloader):
        assert downloader.categorize_item(ORPHAN_REFERENCE_BOOK) == "orphan"

    def test_every_item_gets_exactly_one_category(self, downloader):
        """Jedes Item muss in GENAU eine der fünf Kategorien fallen -
        keine Lücken, keine Überlappung."""
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
        # Downloadbare Items dürfen NICHT im Report auftauchen
        assert "Bibelot" not in content

    def test_no_report_file_when_nothing_unhandled(self, downloader, isolated_download_dir):
        downloader.report_unhandled_items([VOLUME_BUNDLE, INDIVIDUAL_PATTERN])

        report_path = isolated_download_dir / "skipped_non_downloadable.txt"
        assert not report_path.exists()

    def test_report_does_not_trigger_any_download(self, downloader, isolated_download_dir):
        """report_unhandled_items() darf NUR loggen/reporten, niemals
        try_download() aufrufen oder sonst Netzwerk-I/O auslösen."""
        items = [SINGLE_PATTERN_SOURCE_MAGAZINE, ORPHAN_ETSY_PATTERN]

        # Kein Download-Verzeichnis-Inhalt außer der Report-Datei erwartet
        downloader.report_unhandled_items(items)

        created_files = list(isolated_download_dir.iterdir())
        assert created_files == [isolated_download_dir / "skipped_non_downloadable.txt"]

    def test_report_overwrites_on_each_run(self, downloader, isolated_download_dir):
        downloader.report_unhandled_items([SINGLE_PATTERN_SOURCE_MAGAZINE])
        downloader.report_unhandled_items([ORPHAN_ETSY_PATTERN])

        content = (isolated_download_dir / "skipped_non_downloadable.txt").read_text(encoding="utf-8")
        assert "Star Book No. 169" not in content
        assert "Noctiluca Dress" in content
