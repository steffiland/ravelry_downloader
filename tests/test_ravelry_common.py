"""
Tests for the pure helper functions in ravelry_common.py.

Network and browser interactions (api_get, ensure_browser_login) are NOT
tested here, since they require real Ravelry credentials or an actual
login flow. This suite covers the deterministic logic: filename
sanitization, PDF signature checking, cookie validation.
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


class TestParseChooserLinks:
    """
    For patterns with multiple files (e.g. language variants),
    `/dls/{id}/{code}` doesn't return a PDF signature, but an HTML "choose
    file" intermediate page with `/dl/{company}/{id}?filename=...` links -
    even WITHOUT a login problem. _parse_chooser_links() must return ALL
    files with their real Ravelry filename, so the caller can send them
    through the normal ignore.txt filtering like any other download - NO
    preference for a variant hardcoded in the code (see
    fetch_file_variants()). This applies not only to language
    translations, but also to other file variants like "Easy Read",
    charts, or print-friendly editions.
    """

    def test_returns_empty_list_for_real_login_page(self):
        html = '<html><body>Please <a href="/account/login">log in</a></body></html>'
        assert rc._parse_chooser_links(html) == []

    def test_extracts_single_dl_link_with_real_filename(self):
        html = (
            '<a href="https://www.ravelry.com/dl/scheepjes/827389'
            '?filename=30.__DUTCH__Alto_Mare_Wrap.pdf">30.__DUTCH__Alto_Mare_Wrap.pdf</a>'
        )
        assert rc._parse_chooser_links(html) == [
            (
                "30.__DUTCH__Alto_Mare_Wrap.pdf",
                "https://www.ravelry.com/dl/scheepjes/827389"
                "?filename=30.__DUTCH__Alto_Mare_Wrap.pdf",
            )
        ]

    def test_extracts_all_language_variants_in_order(self):
        """ALL language variants must come back, not just a preferred
        one - the selection happens later via ignore.txt."""
        html = "".join(
            f'<a href="https://www.ravelry.com/dl/scheepjes/{code}'
            f'?filename=30.__{lang}__Alto_Mare_Wrap.pdf">x</a>'
            for code, lang in [
                (827389, "DUTCH"),
                (827390, "FRENCH"),
                (827394, "US"),
            ]
        )
        result = rc._parse_chooser_links(html)
        assert [filename for filename, _ in result] == [
            "30.__DUTCH__Alto_Mare_Wrap.pdf",
            "30.__FRENCH__Alto_Mare_Wrap.pdf",
            "30.__US__Alto_Mare_Wrap.pdf",
        ]

    def test_normalizes_http_scheme_to_https(self):
        html = (
            '<a href="http://www.ravelry.com/dl/scheepjes/827389'
            '?filename=file.pdf">x</a>'
        )
        filename, url = rc._parse_chooser_links(html)[0]
        assert url == "https://www.ravelry.com/dl/scheepjes/827389?filename=file.pdf"

    def test_deduplicates_repeated_links(self):
        """Every link appears twice on the real page (filename text +
        download icon) - but must only come back once."""
        html = (
            '<a href="https://www.ravelry.com/dl/scheepjes/827389?filename=f.pdf">f.pdf</a>'
            '<a href="https://www.ravelry.com/dl/scheepjes/827389?filename=f.pdf">'
            '<img src="icon.png"></a>'
        )
        assert len(rc._parse_chooser_links(html)) == 1

    def test_url_decodes_filename(self):
        html = (
            '<a href="https://www.ravelry.com/dl/scheepjes/827389'
            '?filename=30.%20US%20Alto%20Mare%20Wrap.pdf">x</a>'
        )
        filename, _ = rc._parse_chooser_links(html)[0]
        assert filename == "30. US Alto Mare Wrap.pdf"


class TestCookiesToRequestsDict:
    def test_filters_to_ravelry_domain_only(self):
        cookies = [
            {"name": "a", "value": "1", "domain": "www.ravelry.com"},
            {"name": "b", "value": "2", "domain": "example.com"},
        ]
        assert rc._cookies_to_requests_dict(cookies) == {"a": "1"}

    def test_empty_input_returns_empty_dict(self):
        assert rc._cookies_to_requests_dict([]) == {}
