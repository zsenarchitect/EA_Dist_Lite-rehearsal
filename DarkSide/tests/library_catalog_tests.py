#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Unit tests for EnneadTab/DEPOT/LIBRARY_CATALOG.py's pure functions.

Covers resolve_media_url()'s host-allowlist (senzhang-todo #5511: added when
place_asset.button became a second live consumer of download_asset(), so an
absolute URL from Library's own JSON response can no longer be fetched
unchecked onto a foreign host). Transport (_get/_download, dotnet vs urllib)
is exercised on a live host, same as depot_client_tests.py's sibling ASSET/
STATE coverage -- not duplicated here.

CPython 3, no host app. Run from the repo root:
    .venv/Scripts/python.exe -m unittest DarkSide.tests.library_catalog_tests -v
"""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_REPO, "Apps", "lib"))

from EnneadTab.DEPOT import LIBRARY_CATALOG


class ResolveMediaUrlTests(unittest.TestCase):

    def setUp(self):
        os.environ.pop("EA_LIBRARY_URL", None)

    def test_relative_path_resolves_onto_default_host(self):
        self.assertEqual(
            LIBRARY_CATALOG.resolve_media_url("/files/enscape/Materials/Foo.mat"),
            "https://enneadtab.com/library/files/enscape/Materials/Foo.mat",
        )

    def test_relative_path_without_leading_slash_still_resolves(self):
        self.assertEqual(
            LIBRARY_CATALOG.resolve_media_url("files/x.rfa"),
            "https://enneadtab.com/library/files/x.rfa",
        )

    def test_absolute_url_on_librarys_own_host_passes_through(self):
        url = "https://enneadtab.com/library/files/x.3dm"
        self.assertEqual(LIBRARY_CATALOG.resolve_media_url(url), url)

    def test_absolute_url_on_a_foreign_host_is_refused(self):
        self.assertIsNone(LIBRARY_CATALOG.resolve_media_url("https://evil.example.com/payload.3dm"))

    def test_absolute_url_on_a_lookalike_subdomain_is_refused(self):
        # "enneadtab.com.evil.example.com" contains the real host as a
        # substring -- must fail on an exact host match, not `in`.
        self.assertIsNone(LIBRARY_CATALOG.resolve_media_url("https://enneadtab.com.evil.example.com/x.3dm"))

    def test_empty_or_missing_input_returns_none(self):
        self.assertIsNone(LIBRARY_CATALOG.resolve_media_url(None))
        self.assertIsNone(LIBRARY_CATALOG.resolve_media_url(""))

    def test_allowlist_follows_the_ea_library_url_override(self):
        os.environ["EA_LIBRARY_URL"] = "http://localhost:3000"
        try:
            self.assertEqual(
                LIBRARY_CATALOG.resolve_media_url("http://localhost:3000/files/x.3dm"),
                "http://localhost:3000/files/x.3dm",
            )
            # The production host is no longer implicitly trusted once the
            # override points somewhere else.
            self.assertIsNone(LIBRARY_CATALOG.resolve_media_url("https://enneadtab.com/library/files/x.3dm"))
        finally:
            os.environ.pop("EA_LIBRARY_URL", None)


class HostOfTests(unittest.TestCase):

    def test_extracts_host_with_no_path(self):
        self.assertEqual(LIBRARY_CATALOG._host_of("https://enneadtab.com"), "enneadtab.com")

    def test_extracts_host_ignoring_path_and_query(self):
        self.assertEqual(LIBRARY_CATALOG._host_of("https://enneadtab.com/a/b?c=1"), "enneadtab.com")

    def test_extracts_host_with_port(self):
        self.assertEqual(LIBRARY_CATALOG._host_of("http://localhost:3000/x"), "localhost:3000")

    def test_lowercases_the_host(self):
        self.assertEqual(LIBRARY_CATALOG._host_of("https://ENNEADTAB.com/x"), "enneadtab.com")

    def test_malformed_url_returns_none(self):
        self.assertIsNone(LIBRARY_CATALOG._host_of("not-a-url"))


if __name__ == "__main__":
    unittest.main()
