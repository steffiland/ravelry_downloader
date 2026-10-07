"""
Tests für den Katalog-Sync-Mechanismus von Referenz-Collections in
ravelry-downloader.py (INCLUDE-Logik über collections.txt):

  - find_reference_collections() erkennt Collections ohne eigenes PDF-Bundle
  - sync_new_reference_collections() trägt neue Collections automatisch
    INAKTIV in collections.txt ein
  - wiederholte Syncs erzeugen keine Duplikate (Idempotenz)
  - eine vom Nutzer manuell AKTIVIERTE Zeile (führendes '#' entfernt) wird
    beim nächsten Sync NICHT wieder deaktiviert oder dupliziert (das ist der
    ganze Zweck: einmal aktiviert bleibt aktiviert, bis der Nutzer es
    selbst ändert)
"""

from __future__ import annotations

import json


# Beispiel-Library-Items, wie sie von library/search.json zurückkommen.
EBOOK_ITEM = {
    "id": 593135913,
    "pattern_id": 7517377,
    "pattern_source_id": None,
    "title": "Bibelot",
    "patterns_count": 1,
    "has_downloads": True,
}

REFERENCE_COLLECTION_AFTER_PARTY = {
    "id": 592424159,
    "pattern_id": None,
    "pattern_source_id": 213142,
    "title": "YARN - The After Party",
    "patterns_count": 147,
    "has_downloads": False,
}

REFERENCE_COLLECTION_MAGAZINE = {
    "id": 500000001,
    "pattern_id": None,
    "pattern_source_id": 393415,
    "title": "Simply Crochet, Issue 174",
    "patterns_count": 17,
    "has_downloads": False,
}

BUNDLE_COLLECTION_WITH_DOWNLOADS = {
    "id": 500000002,
    "pattern_id": None,
    "pattern_source_id": 999999,
    "title": "Shawl Collection to Crochet 4",
    "patterns_count": 4,
    "has_downloads": True,  # hat eigenes PDF-Bundle -> KEINE Referenz-Collection
}


class TestFindReferenceCollections:
    def test_finds_collections_without_downloads(self, downloader):
        items = [EBOOK_ITEM, REFERENCE_COLLECTION_AFTER_PARTY, BUNDLE_COLLECTION_WITH_DOWNLOADS]

        result = downloader.find_reference_collections(items)

        assert result == [REFERENCE_COLLECTION_AFTER_PARTY]

    def test_single_pattern_items_are_not_collections(self, downloader):
        result = downloader.find_reference_collections([EBOOK_ITEM])
        assert result == []

    def test_collection_with_own_pdf_bundle_is_excluded(self, downloader):
        """patterns_count > 1 reicht nicht: has_downloads=True bedeutet, es
        gibt bereits ein eigenes PDF-Bundle (z.B. 'Shawl Collection to Crochet
        4' aus process_volumes) -> keine Referenz-Collection."""
        result = downloader.find_reference_collections([BUNDLE_COLLECTION_WITH_DOWNLOADS])
        assert result == []

    def test_empty_input(self, downloader):
        assert downloader.find_reference_collections([]) == []


class TestSyncNewReferenceCollections:
    def test_writes_new_collection_as_inactive_line(self, downloader, isolated_download_dir):
        downloader.sync_new_reference_collections([REFERENCE_COLLECTION_AFTER_PARTY])

        content = (isolated_download_dir / "collections.txt").read_text(encoding="utf-8")

        assert "#collection:213142" in content
        assert "YARN - The After Party" in content
        assert "147 Pattern" in content

    def test_synced_collection_is_tracked(self, downloader, isolated_download_dir):
        downloader.sync_new_reference_collections([REFERENCE_COLLECTION_AFTER_PARTY])

        tracked = downloader.load_synced_collection_ids()

        assert 213142 in tracked

    def test_second_sync_does_not_duplicate_entry(self, downloader, isolated_download_dir):
        downloader.sync_new_reference_collections([REFERENCE_COLLECTION_AFTER_PARTY])
        downloader.sync_new_reference_collections([REFERENCE_COLLECTION_AFTER_PARTY])

        content = (isolated_download_dir / "collections.txt").read_text(encoding="utf-8")

        assert content.count("collection:213142") == 1

    def test_multiple_collections_all_get_synced(self, downloader, isolated_download_dir):
        downloader.sync_new_reference_collections(
            [REFERENCE_COLLECTION_AFTER_PARTY, REFERENCE_COLLECTION_MAGAZINE]
        )

        content = (isolated_download_dir / "collections.txt").read_text(encoding="utf-8")

        assert "#collection:213142" in content
        assert "#collection:393415" in content

    def test_manually_activated_line_is_not_touched_again(self, downloader, isolated_download_dir):
        """Kernverhalten des Katalog-Sync: aktiviert der Nutzer eine Zeile
        (führendes '#' entfernt = 'ich will diese Collection laden'), darf
        ein erneuter Sync-Lauf sie NICHT wieder deaktivieren oder
        duplizieren."""
        collections_file = isolated_download_dir / "collections.txt"

        downloader.sync_new_reference_collections([REFERENCE_COLLECTION_AFTER_PARTY])
        assert "#collection:213142" in collections_file.read_text(encoding="utf-8")

        # Nutzer aktiviert die Zeile manuell (führendes '#' entfernen)
        content = collections_file.read_text(encoding="utf-8")
        content = content.replace("#collection:213142", "collection:213142")
        collections_file.write_text(content, encoding="utf-8")

        # Erneuter Sync-Lauf mit denselben Collections aus der API
        downloader.sync_new_reference_collections([REFERENCE_COLLECTION_AFTER_PARTY])

        final_content = collections_file.read_text(encoding="utf-8")
        assert "collection:213142" in final_content
        assert "#collection:213142" not in final_content  # nicht erneut deaktiviert
        assert final_content.count("collection:213142") == 1  # nicht dupliziert

    def test_only_truly_new_collections_are_appended(self, downloader, isolated_download_dir):
        """Nach dem ersten Sync von Collection A ist ein zweiter Sync-Aufruf
        mit [A, B] erwartet, nur B neu hinzuzufügen."""
        downloader.sync_new_reference_collections([REFERENCE_COLLECTION_AFTER_PARTY])
        downloader.sync_new_reference_collections(
            [REFERENCE_COLLECTION_AFTER_PARTY, REFERENCE_COLLECTION_MAGAZINE]
        )

        content = (isolated_download_dir / "collections.txt").read_text(encoding="utf-8")
        assert content.count("collection:213142") == 1
        assert content.count("collection:393415") == 1

    def test_no_write_when_no_new_collections(self, downloader, isolated_download_dir):
        collections_file = isolated_download_dir / "collections.txt"
        downloader.sync_new_reference_collections([REFERENCE_COLLECTION_AFTER_PARTY])
        mtime_before = collections_file.stat().st_mtime_ns

        downloader.sync_new_reference_collections([REFERENCE_COLLECTION_AFTER_PARTY])

        assert collections_file.stat().st_mtime_ns == mtime_before


class TestSyncRoundTrip:
    """End-to-End: sync schreiben -> einlesen -> is_collection_included prüfen.
    Deckt exakt den Workflow ab, den main() im echten Lauf durchläuft."""

    def test_newly_synced_collection_is_not_included_by_default(self, downloader, isolated_download_dir):
        downloader.sync_new_reference_collections([REFERENCE_COLLECTION_AFTER_PARTY])
        includes = downloader.load_collection_includes(downloader.COLLECTIONS_FILE)

        assert downloader.is_collection_included(
            REFERENCE_COLLECTION_AFTER_PARTY, includes
        ) is False

    def test_manually_activated_collection_is_included(self, downloader, isolated_download_dir):
        collections_file = isolated_download_dir / "collections.txt"

        downloader.sync_new_reference_collections([REFERENCE_COLLECTION_AFTER_PARTY])
        content = collections_file.read_text(encoding="utf-8")
        content = content.replace("#collection:213142", "collection:213142")  # aktivieren
        collections_file.write_text(content, encoding="utf-8")

        includes = downloader.load_collection_includes(str(collections_file))

        assert downloader.is_collection_included(
            REFERENCE_COLLECTION_AFTER_PARTY, includes
        ) is True

    def test_sync_tracking_file_persists_across_calls(self, downloader, isolated_download_dir):
        sync_file = isolated_download_dir / ".collection_sync.json"

        downloader.sync_new_reference_collections([REFERENCE_COLLECTION_AFTER_PARTY])

        assert sync_file.exists()
        tracked_ids = json.loads(sync_file.read_text(encoding="utf-8"))
        assert 213142 in tracked_ids
