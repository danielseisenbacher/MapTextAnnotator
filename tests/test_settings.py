# -*- coding: utf-8 -*-
"""Tests for settings.PluginSettings (persistence through a temporary ini store)."""

import unittest

import utilities

utilities.start_qgis()

from qgis.core import QgsSettings  # noqa: E402
from qgis.PyQt.QtCore import QSettings  # noqa: E402

settings = utilities.import_plugin_module("settings")
schema = utilities.import_plugin_module("schema")

# A non-default value of the right type for every key.
CHANGED = {
    settings.ALTITUDE: False,
    settings.SLOPE: False,
    settings.CONTRAST: False,
    settings.EDGE: False,
    settings.CENTROID: False,
    settings.EDGE_WIDTH: 7,
    settings.EDGE_THRESHOLD: 12.5,
    settings.EDGE_BUFFER: 0.25,
    settings.CONTRAST_LOWER: 2.5,
    settings.CONTRAST_UPPER: 97.5,
    settings.BBOX_FORMAT: "polygon",
    settings.BEZIER_ORDER: "legacy",
    settings.LAST_DIR: "/tmp/exports",
    settings.SHOW_INSTRUCTIONS: False,
}


def reopen(path):
    """A fresh store on the same ini file, as after a QGIS restart."""
    return QgsSettings(path, QSettings.IniFormat)


class SettingsDefaultsTest(unittest.TestCase):

    def setUp(self):
        self.store, self.path = utilities.temp_settings_store()
        self.settings = settings.PluginSettings(self.store)

    def test_changed_covers_every_key(self):
        self.assertEqual(set(CHANGED), set(settings.DEFAULTS))
        for key, value in CHANGED.items():
            self.assertNotEqual(value, settings.DEFAULTS[key], key)
            self.assertIs(type(value), type(settings.DEFAULTS[key]), key)

    def test_empty_store_gives_defaults(self):
        self.assertEqual(self.settings.as_dict(), settings.DEFAULTS)

    def test_documented_defaults(self):
        expected = {
            "stats/altitude": True,
            "stats/slope": True,
            "stats/contrast": True,
            "stats/edge_complexity": True,
            "stats/centroid": True,
            "edge/width": 3,
            "edge/threshold": 5.0,
            "edge/buffer_ratio": 0.1,
            "contrast/lower_pct": 5.0,
            "contrast/upper_pct": 95.0,
            "export/bbox_format": "xyxy",
            "export/bezier_order": "abcnet",
            "export/last_dir": "",
            "ui/show_instructions": True,
        }
        self.assertEqual(settings.DEFAULTS, expected)

    def test_default_types(self):
        for key, default in settings.DEFAULTS.items():
            self.assertIs(type(self.settings.get(key)), type(default), key)

    def test_as_dict_is_a_copy(self):
        values = self.settings.as_dict()
        values[settings.EDGE_WIDTH] = 99
        self.assertEqual(self.settings.get(settings.EDGE_WIDTH), 3)

    def test_enum_defaults_are_valid(self):
        self.assertIn(settings.DEFAULTS[settings.BBOX_FORMAT], settings.BBOX_FORMATS)
        self.assertIn(settings.DEFAULTS[settings.BEZIER_ORDER], settings.BEZIER_ORDERS)
        self.assertEqual(set(settings.BBOX_FORMATS), {"xyxy", "xywh", "polygon"})
        self.assertEqual(set(settings.BEZIER_ORDERS), {"abcnet", "legacy"})

    def test_stat_toggles_match_schema(self):
        self.assertEqual(set(settings.STAT_TOGGLES), set(schema.STAT_FIELDS))
        for key in settings.STAT_TOGGLES.values():
            self.assertIn(key, settings.DEFAULTS)


class SettingsSetGetTest(unittest.TestCase):

    def setUp(self):
        self.store, self.path = utilities.temp_settings_store()
        self.settings = settings.PluginSettings(self.store)

    def test_bool_coercion_from_strings(self):
        for raw, expected in (("true", True), ("false", False), ("1", True), ("0", False),
                              ("True", True), ("FALSE", False), (" yes ", True), ("off", False)):
            self.settings.set(settings.ALTITUDE, raw)
            self.assertIs(self.settings.get(settings.ALTITUDE), expected, raw)

    def test_bool_coercion_from_numbers(self):
        self.settings.set(settings.SLOPE, 0)
        self.assertIs(self.settings.get(settings.SLOPE), False)
        self.settings.set(settings.SLOPE, 1)
        self.assertIs(self.settings.get(settings.SLOPE), True)

    def test_invalid_bool_string(self):
        with self.assertRaises(ValueError):
            self.settings.set(settings.ALTITUDE, "maybe")
        self.assertIs(self.settings.get(settings.ALTITUDE), True)

    def test_int_coercion(self):
        self.settings.set(settings.EDGE_WIDTH, "5")
        self.assertEqual(self.settings.get(settings.EDGE_WIDTH), 5)
        self.assertIs(type(self.settings.get(settings.EDGE_WIDTH)), int)
        self.settings.set(settings.EDGE_WIDTH, "7.0")
        self.assertEqual(self.settings.get(settings.EDGE_WIDTH), 7)
        self.settings.set(settings.EDGE_WIDTH, 9.0)
        self.assertEqual(self.settings.get(settings.EDGE_WIDTH), 9)

    def test_int_rejects_fractions_and_garbage(self):
        for raw in (2.5, "abc", None):
            with self.assertRaises(ValueError, msg=repr(raw)):
                self.settings.set(settings.EDGE_WIDTH, raw)
        self.assertEqual(self.settings.get(settings.EDGE_WIDTH), 3)

    def test_float_coercion(self):
        self.settings.set(settings.EDGE_THRESHOLD, "2.5")
        self.assertEqual(self.settings.get(settings.EDGE_THRESHOLD), 2.5)
        self.settings.set(settings.CONTRAST_LOWER, 3)
        self.assertEqual(self.settings.get(settings.CONTRAST_LOWER), 3.0)
        self.assertIs(type(self.settings.get(settings.CONTRAST_LOWER)), float)

    def test_float_rejects_garbage_and_non_finite(self):
        for raw in ("abc", "nan", "inf", float("nan"), None):
            with self.assertRaises(ValueError, msg=repr(raw)):
                self.settings.set(settings.EDGE_THRESHOLD, raw)
        self.assertEqual(self.settings.get(settings.EDGE_THRESHOLD), 5.0)

    def test_string_values(self):
        self.settings.set(settings.LAST_DIR, "/data/out")
        self.assertEqual(self.settings.get(settings.LAST_DIR), "/data/out")
        self.settings.set(settings.LAST_DIR, None)
        self.assertEqual(self.settings.get(settings.LAST_DIR), "")

    def test_valid_enum_values(self):
        for key in settings.BBOX_FORMATS:
            self.settings.set(settings.BBOX_FORMAT, key)
            self.assertEqual(self.settings.get(settings.BBOX_FORMAT), key)
        for key in settings.BEZIER_ORDERS:
            self.settings.set(settings.BEZIER_ORDER, key)
            self.assertEqual(self.settings.get(settings.BEZIER_ORDER), key)

    def test_invalid_enum_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.settings.set(settings.BBOX_FORMAT, "bogus")
        with self.assertRaises(ValueError):
            self.settings.set(settings.BEZIER_ORDER, "XYXY")
        self.assertEqual(self.settings.get(settings.BBOX_FORMAT), "xyxy")
        self.assertEqual(self.settings.get(settings.BEZIER_ORDER), "abcnet")

    def test_unknown_key_raises_key_error(self):
        with self.assertRaises(KeyError):
            self.settings.set("stats/unknown", True)
        with self.assertRaises(KeyError):
            self.settings.get("stats/unknown")

    def test_set_does_not_persist_without_save(self):
        self.settings.set(settings.EDGE_WIDTH, 9)
        self.assertEqual(settings.PluginSettings(reopen(self.path)).get(settings.EDGE_WIDTH), 3)

    def test_reset(self):
        for key, value in CHANGED.items():
            self.settings.set(key, value)
        self.settings.reset()
        self.assertEqual(self.settings.as_dict(), settings.DEFAULTS)

    def test_reset_does_not_touch_the_store_until_save(self):
        for key, value in CHANGED.items():
            self.settings.set(key, value)
        self.settings.save()
        self.settings.reset()
        self.assertEqual(settings.PluginSettings(reopen(self.path)).as_dict(), CHANGED)
        self.settings.save()
        self.assertEqual(settings.PluginSettings(reopen(self.path)).as_dict(), settings.DEFAULTS)

    def test_enabled_stats(self):
        self.assertEqual(self.settings.enabled_stats(), frozenset(schema.STAT_FIELDS))
        self.settings.set(settings.ALTITUDE, False)
        self.settings.set(settings.EDGE, False)
        self.assertEqual(self.settings.enabled_stats(),
                         frozenset({"slope", "contrast", "centroid"}))
        self.assertFalse(self.settings.stat_enabled("altitude"))
        self.assertFalse(self.settings.stat_enabled("edge_complexity"))
        self.assertTrue(self.settings.stat_enabled("slope"))
        for key in settings.STAT_TOGGLES.values():
            self.settings.set(key, False)
        self.assertEqual(self.settings.enabled_stats(), frozenset())


class SettingsPersistenceTest(unittest.TestCase):

    def setUp(self):
        self.store, self.path = utilities.temp_settings_store()

    def test_round_trip_every_key(self):
        original = settings.PluginSettings(self.store)
        for key, value in CHANGED.items():
            original.set(key, value)
        original.save()

        loaded = settings.PluginSettings(reopen(self.path))
        self.assertEqual(loaded.as_dict(), CHANGED)
        for key, value in CHANGED.items():
            self.assertIs(type(loaded.get(key)), type(value), key)

    def test_round_trip_defaults(self):
        settings.PluginSettings(self.store).save()
        self.assertEqual(settings.PluginSettings(reopen(self.path)).as_dict(), settings.DEFAULTS)

    def test_store_uses_prefix(self):
        self.assertEqual(settings.PREFIX, "MaptextAnnotator/")
        plugin = settings.PluginSettings(self.store)
        plugin.set(settings.EDGE_WIDTH, 11)
        plugin.save()

        raw = QSettings(self.path, QSettings.IniFormat)
        keys = raw.allKeys()
        self.assertTrue(keys)
        self.assertTrue(all(key.startswith("MaptextAnnotator/") for key in keys), keys)
        self.assertEqual(set(keys), {"MaptextAnnotator/" + key for key in settings.DEFAULTS})
        self.assertEqual(int(raw.value("MaptextAnnotator/edge/width")), 11)

    def test_invalid_stored_values_fall_back_to_defaults(self):
        raw = QSettings(self.path, QSettings.IniFormat)
        raw.setValue("MaptextAnnotator/edge/threshold", "abc")
        raw.setValue("MaptextAnnotator/edge/width", "seven")
        raw.setValue("MaptextAnnotator/contrast/lower_pct", "nan")
        raw.setValue("MaptextAnnotator/stats/slope", "maybe")
        raw.setValue("MaptextAnnotator/export/bbox_format", "bogus")
        raw.setValue("MaptextAnnotator/export/bezier_order", "")
        # A valid value next to the invalid ones is still read.
        raw.setValue("MaptextAnnotator/contrast/upper_pct", "90")
        raw.sync()
        del raw

        loaded = settings.PluginSettings(reopen(self.path))
        self.assertEqual(loaded.get(settings.EDGE_THRESHOLD), settings.DEFAULTS[settings.EDGE_THRESHOLD])
        self.assertEqual(loaded.get(settings.EDGE_WIDTH), settings.DEFAULTS[settings.EDGE_WIDTH])
        self.assertEqual(loaded.get(settings.CONTRAST_LOWER), settings.DEFAULTS[settings.CONTRAST_LOWER])
        self.assertIs(loaded.get(settings.SLOPE), True)
        self.assertEqual(loaded.get(settings.BBOX_FORMAT), "xyxy")
        self.assertEqual(loaded.get(settings.BEZIER_ORDER), "abcnet")
        self.assertEqual(loaded.get(settings.CONTRAST_UPPER), 90.0)

    def test_string_booleans_from_ini_are_read(self):
        raw = QSettings(self.path, QSettings.IniFormat)
        raw.setValue("MaptextAnnotator/stats/altitude", "false")
        raw.setValue("MaptextAnnotator/ui/show_instructions", "0")
        raw.sync()
        del raw
        loaded = settings.PluginSettings(reopen(self.path))
        self.assertIs(loaded.get(settings.ALTITUDE), False)
        self.assertIs(loaded.get(settings.SHOW_INSTRUCTIONS), False)

    def test_load_rereads_the_store(self):
        plugin = settings.PluginSettings(self.store)
        other = settings.PluginSettings(reopen(self.path))
        other.set(settings.BBOX_FORMAT, "xywh")
        other.save()
        plugin.load()
        self.assertEqual(plugin.get(settings.BBOX_FORMAT), "xywh")


if __name__ == "__main__":
    unittest.main()
