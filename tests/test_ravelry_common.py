"""
Tests für die reinen Hilfsfunktionen in ravelry_common.py.

Netzwerk- und Browser-Interaktionen (api_get, ensure_browser_login) werden
hier NICHT getestet, da sie echte Ravelry-Zugangsdaten bzw. einen echten
Login-Flow erfordern. Diese Suite deckt die deterministische Logik ab:
Dateinamen-Bereinigung, PDF-Signaturprüfung, Cookie-Validierung.
"""

from __future__ import annotations

import time

import ravelry_common as rc


class TestSanitizeFilename:
    def test_replaces_forbidden_characters(self):
        assert rc.sanitize_filename('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"

    def test_leaves_normal_names_untouched(self):
        assert rc.sanitize_filename("Normaler Name 2.pdf") == "Normaler Name 2.pdf"

    def test_handles_unicode(self):
        assert rc.sanitize_filename("Mütze_für_Größe_42") == "Mütze_für_Größe_42"


class TestIsPdfResponse:
    def test_recognizes_pdf_signature(self):
        assert rc._is_pdf_response("application/octet-stream", b"%PDF-1.4\n...") is True

    def test_recognizes_pdf_content_type(self):
        assert rc._is_pdf_response("application/pdf", b"irrelevant") is True

    def test_rejects_html_response(self):
        assert rc._is_pdf_response("text/html; charset=utf-8", b"<!DOCTYPE html>") is False

    def test_rejects_empty_content_type_without_signature(self):
        assert rc._is_pdf_response("", b"not a pdf") is False


class TestCookiesLookValid:
    def test_empty_list_is_invalid(self):
        assert rc._cookies_look_valid([]) is False

    def test_none_is_invalid(self):
        assert rc._cookies_look_valid(None) is False

    def test_no_ravelry_cookies_is_invalid(self):
        cookies = [{"name": "foo", "value": "bar", "domain": "example.com", "expires": -1}]
        assert rc._cookies_look_valid(cookies) is False

    def test_ravelry_cookie_without_expiry_is_valid(self):
        cookies = [{"name": "session", "value": "x", "domain": "www.ravelry.com", "expires": -1}]
        assert rc._cookies_look_valid(cookies) is True

    def test_ravelry_cookie_with_future_expiry_is_valid(self):
        future = time.time() + 3600
        cookies = [{"name": "session", "value": "x", "domain": "www.ravelry.com", "expires": future}]
        assert rc._cookies_look_valid(cookies) is True

    def test_ravelry_cookie_with_past_expiry_is_invalid(self):
        past = time.time() - 3600
        cookies = [{"name": "session", "value": "x", "domain": "www.ravelry.com", "expires": past}]
        assert rc._cookies_look_valid(cookies) is False


class TestExtractFileChooserUrl:
    """
    Für Pattern mit mehreren Dateien (z.B. Sprachvarianten) liefert
    `/dls/{id}/{code}` keine PDF-Signatur, sondern eine HTML-"Datei
    wählen"-Zwischenseite mit `/dl/{company}/{id}?filename=...`-Links – auch
    OHNE Login-Problem. download_pdf() muss diese Seite erkennen und einem
    passenden Link folgen, statt sie als Login-Fehler zu behandeln.
    """

    def test_returns_none_for_real_login_page(self):
        html = '<html><body>Please <a href="/account/login">log in</a></body></html>'
        assert rc._extract_file_chooser_url(html) is None

    def test_extracts_single_dl_link(self):
        html = (
            '<a href="https://www.ravelry.com/dl/scheepjes/827389'
            '?filename=30.__DUTCH__Alto_Mare_Wrap.pdf">30.__DUTCH__Alto_Mare_Wrap.pdf</a>'
        )
        assert rc._extract_file_chooser_url(html) == (
            "https://www.ravelry.com/dl/scheepjes/827389"
            "?filename=30.__DUTCH__Alto_Mare_Wrap.pdf"
        )

    def test_prefers_us_variant_among_multiple_languages(self):
        html = "".join(
            f'<a href="https://www.ravelry.com/dl/scheepjes/{code}'
            f'?filename=30.__{lang}__Alto_Mare_Wrap.pdf">x</a>'
            for code, lang in [
                (827389, "DUTCH"),
                (827390, "FRENCH"),
                (827394, "US"),
            ]
        )
        assert rc._extract_file_chooser_url(html) == (
            "https://www.ravelry.com/dl/scheepjes/827394"
            "?filename=30.__US__Alto_Mare_Wrap.pdf"
        )

    def test_normalizes_http_scheme_to_https(self):
        html = (
            '<a href="http://www.ravelry.com/dl/scheepjes/827389'
            '?filename=file.pdf">x</a>'
        )
        assert rc._extract_file_chooser_url(html) == (
            "https://www.ravelry.com/dl/scheepjes/827389?filename=file.pdf"
        )


class TestCookiesToRequestsDict:
    def test_filters_to_ravelry_domain_only(self):
        cookies = [
            {"name": "a", "value": "1", "domain": "www.ravelry.com"},
            {"name": "b", "value": "2", "domain": "example.com"},
        ]
        assert rc._cookies_to_requests_dict(cookies) == {"a": "1"}

    def test_empty_input_returns_empty_dict(self):
        assert rc._cookies_to_requests_dict([]) == {}
