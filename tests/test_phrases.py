# -*- coding: utf-8 -*-
"""Tests for core/phrases.py (pure python, no QGIS application needed)."""

import unittest

import utilities

phrases = utilities.import_plugin_module("core.phrases")


class PhraseTests(unittest.TestCase):
    def test_single_word(self):
        self.assertEqual(phrases.phrase_for([(1, 1, "Wien", False)], 1), "Wien")

    def test_linked_words_form_a_phrase(self):
        records = [
            (1, 1, "Neusiedler", False),
            (2, 2, "See", True),
            (3, 3, "Graz", False),
        ]
        self.assertEqual(phrases.phrase_for(records, 1), "Neusiedler See")
        self.assertEqual(phrases.phrase_for(records, 2), "Neusiedler See")
        self.assertEqual(phrases.phrase_for(records, 3), "Graz")

    def test_ordering_by_sort_key_not_input_order(self):
        records = [
            (3, 30, "Alpen", True),
            (1, 10, "Hohe", False),
            (2, 20, "Tauern", True),
            (4, 5, "Linz", False),
        ]
        self.assertEqual(phrases.phrase_for(records, 1), "Hohe Tauern Alpen")
        self.assertEqual(phrases.phrase_for(records, 3), "Hohe Tauern Alpen")
        self.assertEqual(phrases.phrase_for(records, 4), "Linz")

    def test_fid_breaks_ties(self):
        records = [(2, 1, "B", True), (1, 1, "A", False)]
        self.assertEqual(phrases.phrase_for(records, 2), "A B")

    def test_none_keys_sort_last_by_fid(self):
        records = [
            (5, None, "Bad", True),
            (4, None, "Ischl", True),
            (1, 1, "Salzburg", False),
            (3, 2, "Bad", False),
        ]
        # order: Salzburg(1), Bad(3), [None keys by fid] Ischl(4), Bad(5)
        self.assertEqual(phrases.phrase_for(records, 4), "Bad Ischl Bad")
        self.assertEqual(phrases.phrase_for(records, 1), "Salzburg")

    def test_all_none_keys(self):
        records = [(2, None, "b", True), (1, None, "a", False)]
        self.assertEqual(phrases.phrase_for(records, 1), "a b")

    def test_none_words_count_as_empty(self):
        records = [(1, 1, None, False), (2, 2, "x", True), (3, 3, None, False)]
        self.assertEqual(phrases.phrase_for(records, 2), " x")
        self.assertEqual(phrases.phrase_for(records, 3), "")

    def test_linked_first_word_starts_phrase(self):
        # a link flag on the very first word has nothing to link to
        records = [(1, 1, "a", True), (2, 2, "b", True)]
        self.assertEqual(phrases.phrase_for(records, 1), "a b")

    def test_falsy_link_values(self):
        records = [(1, 1, "a", None), (2, 2, "b", 0), (3, 3, "c", 1)]
        self.assertEqual(phrases.phrase_for(records, 1), "a")
        self.assertEqual(phrases.phrase_for(records, 3), "b c")

    def test_missing_fid(self):
        self.assertIsNone(phrases.phrase_for([(1, 1, "a", False)], 99))
        self.assertIsNone(phrases.phrase_for([], 1))


if __name__ == "__main__":
    unittest.main()
