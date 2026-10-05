# -*- coding: utf-8 -*-
"""Tests for settings_dialog.SettingsDialog."""

import unittest
from unittest import mock

import utilities

utilities.start_qgis()

from qgis.core import QgsSettings  # noqa: E402
from qgis.PyQt.QtCore import QSettings  # noqa: E402
from qgis.PyQt.QtWidgets import (  # noqa: E402
    QAbstractButton,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QSpinBox,
)

settings = utilities.import_plugin_module("settings")
settings_dialog = utilities.import_plugin_module("settings_dialog")

CHECKS = {
    "altitudeCheck": settings.ALTITUDE,
    "slopeCheck": settings.SLOPE,
    "contrastCheck": settings.CONTRAST,
    "edgeCheck": settings.EDGE,
    "centroidCheck": settings.CENTROID,
    "showInstructionsCheck": settings.SHOW_INSTRUCTIONS,
}
SPINS = {
    "edgeWidthSpin": (QSpinBox, settings.EDGE_WIDTH),
    "edgeThresholdSpin": (QDoubleSpinBox, settings.EDGE_THRESHOLD),
    "contrastLowerSpin": (QDoubleSpinBox, settings.CONTRAST_LOWER),
    "contrastUpperSpin": (QDoubleSpinBox, settings.CONTRAST_UPPER),
}
COMBOS = {
    "bboxFormatCombo": (settings.BBOX_FORMAT, settings.BBOX_FORMATS),
    "bezierOrderCombo": (settings.BEZIER_ORDER, settings.BEZIER_ORDERS),
}

# Non-default values, chosen to be representable by the widgets.
CUSTOM = {
    settings.ALTITUDE: False,
    settings.SLOPE: True,
    settings.CONTRAST: True,
    settings.EDGE: False,
    settings.CENTROID: False,
    settings.EDGE_WIDTH: 5,
    settings.EDGE_THRESHOLD: 7.5,
    settings.CONTRAST_LOWER: 10.0,
    settings.CONTRAST_UPPER: 90.0,
    settings.BBOX_FORMAT: "xywh",
    settings.BEZIER_ORDER: "legacy",
    settings.SHOW_INSTRUCTIONS: False,
}


def stored(path):
    """Settings as a fresh session would load them from the ini file."""
    return settings.PluginSettings(QgsSettings(path, QSettings.IniFormat)).as_dict()


class SettingsDialogTest(unittest.TestCase):

    def setUp(self):
        self.store, self.path = utilities.temp_settings_store()
        self.settings = settings.PluginSettings(self.store)
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.deleteLater()

    def make_dialog(self, **kwargs):
        dialog = settings_dialog.SettingsDialog(self.settings, **kwargs)
        dialog.show_validation_error = mock.Mock()
        self.dialogs.append(dialog)
        return dialog

    def widget(self, dialog, cls, name):
        found = dialog.findChild(cls, name)
        self.assertIsNotNone(found, name)
        return found

    def save_custom(self):
        for key, value in CUSTOM.items():
            self.settings.set(key, value)
        self.settings.save()

    def set_widgets(self, dialog, values):
        for name, key in CHECKS.items():
            self.widget(dialog, QCheckBox, name).setChecked(values[key])
        for name, (cls, key) in SPINS.items():
            self.widget(dialog, cls, name).setValue(values[key])
        for name, (key, _) in COMBOS.items():
            combo = self.widget(dialog, QComboBox, name)
            combo.setCurrentIndex(combo.findData(values[key]))

    def assert_widgets_show(self, dialog, values):
        for name, key in CHECKS.items():
            self.assertEqual(self.widget(dialog, QCheckBox, name).isChecked(), values[key], name)
        for name, (cls, key) in SPINS.items():
            self.assertAlmostEqual(self.widget(dialog, cls, name).value(), values[key], msg=name)
        for name, (key, _) in COMBOS.items():
            self.assertEqual(self.widget(dialog, QComboBox, name).currentData(), values[key], name)

    # -- structure ------------------------------------------------------------

    def test_window_title_and_contract_widgets(self):
        dialog = self.make_dialog()
        self.assertEqual(dialog.windowTitle(), "MapText Annotator Settings")
        for name in CHECKS:
            self.widget(dialog, QCheckBox, name)
        for name, (cls, _) in SPINS.items():
            self.widget(dialog, cls, name)
        for name in COMBOS:
            self.widget(dialog, QComboBox, name)
        self.widget(dialog, QAbstractButton, "restoreDefaultsButton")
        box = self.widget(dialog, QDialogButtonBox, "buttonBox")
        self.assertIsNotNone(box.button(QDialogButtonBox.Ok))
        self.assertIsNotNone(box.button(QDialogButtonBox.Cancel))

    def test_check_labels_explain_dependencies(self):
        dialog = self.make_dialog()
        self.assertIn("DEM", dialog.altitudeCheck.text())
        self.assertIn("slope layer", dialog.slopeCheck.text())
        self.assertIn("GRASS", dialog.edgeCheck.text())
        self.assertIn("WGS 84", dialog.centroidCheck.text())

    def test_spin_ranges(self):
        dialog = self.make_dialog()
        self.assertEqual(dialog.edgeWidthSpin.minimum(), 1)
        self.assertGreaterEqual(dialog.edgeWidthSpin.maximum(), 15)
        self.assertEqual((dialog.edgeThresholdSpin.minimum(), dialog.edgeThresholdSpin.maximum()), (0.0, 1000.0))
        for spin in (dialog.contrastLowerSpin, dialog.contrastUpperSpin):
            self.assertEqual((spin.minimum(), spin.maximum()), (0.0, 100.0))

    def test_combo_item_data_are_enum_keys(self):
        dialog = self.make_dialog()
        for name, (_, choices) in COMBOS.items():
            combo = self.widget(dialog, QComboBox, name)
            data = [combo.itemData(i) for i in range(combo.count())]
            texts = [combo.itemText(i) for i in range(combo.count())]
            self.assertEqual(data, list(choices), name)
            self.assertEqual(texts, list(choices.values()), name)

    # -- values -----------------------------------------------------------------

    def test_widgets_reflect_defaults(self):
        dialog = self.make_dialog()
        self.assert_widgets_show(dialog, settings.DEFAULTS)

    def test_widgets_reflect_settings_on_open(self):
        self.save_custom()
        dialog = self.make_dialog()
        self.assert_widgets_show(dialog, CUSTOM)

    def test_accept_updates_and_saves_settings(self):
        dialog = self.make_dialog()
        self.set_widgets(dialog, CUSTOM)
        dialog.accept()

        self.assertEqual(dialog.result(), QDialog.Accepted)
        dialog.show_validation_error.assert_not_called()
        expected = dict(settings.DEFAULTS, **CUSTOM)
        self.assertEqual(self.settings.as_dict(), expected)
        self.assertEqual(stored(self.path), expected)

    def test_ok_button_accepts(self):
        dialog = self.make_dialog()
        dialog.bboxFormatCombo.setCurrentIndex(dialog.bboxFormatCombo.findData("polygon"))
        dialog.buttonBox.button(QDialogButtonBox.Ok).click()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(stored(self.path)[settings.BBOX_FORMAT], "polygon")

    def test_accept_keeps_settings_without_widgets(self):
        self.settings.set(settings.LAST_DIR, "/data/exports")
        self.settings.set(settings.EDGE_BUFFER, 0.3)
        self.settings.save()
        dialog = self.make_dialog()
        dialog.accept()
        self.assertEqual(stored(self.path)[settings.LAST_DIR], "/data/exports")
        self.assertEqual(stored(self.path)[settings.EDGE_BUFFER], 0.3)

    def test_reject_leaves_settings_unchanged(self):
        self.save_custom()
        before = self.settings.as_dict()
        dialog = self.make_dialog()
        self.set_widgets(dialog, dict(settings.DEFAULTS, **{settings.EDGE_WIDTH: 9}))
        dialog.reject()

        self.assertEqual(dialog.result(), QDialog.Rejected)
        self.assertEqual(self.settings.as_dict(), before)
        self.assertEqual(stored(self.path), before)

    def test_cancel_button_rejects(self):
        dialog = self.make_dialog()
        dialog.edgeWidthSpin.setValue(9)
        dialog.buttonBox.button(QDialogButtonBox.Cancel).click()
        self.assertEqual(dialog.result(), QDialog.Rejected)
        self.assertEqual(self.settings.get(settings.EDGE_WIDTH), 3)
        self.assertEqual(stored(self.path)[settings.EDGE_WIDTH], 3)

    def test_restore_defaults_then_accept_saves_defaults(self):
        self.settings.set(settings.EDGE_BUFFER, 0.3)
        self.settings.set(settings.LAST_DIR, "/data/exports")
        self.save_custom()
        dialog = self.make_dialog()
        dialog.restoreDefaultsButton.click()
        self.assert_widgets_show(dialog, settings.DEFAULTS)
        dialog.accept()

        expected = dict(settings.DEFAULTS, **{settings.LAST_DIR: "/data/exports"})
        self.assertEqual(self.settings.as_dict(), expected)
        self.assertEqual(stored(self.path), expected)

    def test_restore_defaults_then_cancel_keeps_settings(self):
        self.save_custom()
        before = self.settings.as_dict()
        dialog = self.make_dialog()
        dialog.restoreDefaultsButton.click()
        # Restoring changes only the widgets.
        self.assertEqual(self.settings.as_dict(), before)
        dialog.reject()
        self.assertEqual(self.settings.as_dict(), before)
        self.assertEqual(stored(self.path), before)

    def test_restore_defaults_restores_enabled_state(self):
        dialog = self.make_dialog()
        dialog.edgeCheck.setChecked(False)
        dialog.contrastCheck.setChecked(False)
        dialog.restoreDefaultsButton.click()
        self.assertTrue(dialog.edgeWidthSpin.isEnabled())
        self.assertTrue(dialog.contrastLowerSpin.isEnabled())

    # -- validation ---------------------------------------------------------------

    def test_lower_percentile_not_below_upper_is_refused(self):
        self.save_custom()
        before = self.settings.as_dict()
        for lower, upper in ((60.0, 40.0), (50.0, 50.0)):
            dialog = self.make_dialog()
            dialog.edgeWidthSpin.setValue(9)
            dialog.contrastLowerSpin.setValue(lower)
            dialog.contrastUpperSpin.setValue(upper)
            self.assertIsNotNone(dialog.validate())
            dialog.accept()

            dialog.show_validation_error.assert_called_once()
            self.assertNotEqual(dialog.result(), QDialog.Accepted)
            self.assertEqual(self.settings.as_dict(), before)
            self.assertEqual(stored(self.path), before)

    def test_valid_percentiles(self):
        dialog = self.make_dialog()
        dialog.contrastLowerSpin.setValue(1.0)
        dialog.contrastUpperSpin.setValue(99.0)
        self.assertIsNone(dialog.validate())

    def test_refused_dialog_can_be_fixed_and_accepted(self):
        dialog = self.make_dialog()
        dialog.contrastLowerSpin.setValue(80.0)
        dialog.contrastUpperSpin.setValue(20.0)
        dialog.accept()
        self.assertNotEqual(dialog.result(), QDialog.Accepted)
        dialog.contrastUpperSpin.setValue(99.0)
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(stored(self.path)[settings.CONTRAST_LOWER], 80.0)
        self.assertEqual(stored(self.path)[settings.CONTRAST_UPPER], 99.0)

    def test_show_validation_error_uses_message_box(self):
        dialog = settings_dialog.SettingsDialog(self.settings)
        self.dialogs.append(dialog)
        with mock.patch.object(settings_dialog.QMessageBox, "warning") as warning:
            dialog.contrastLowerSpin.setValue(70.0)
            dialog.contrastUpperSpin.setValue(30.0)
            dialog.accept()
        warning.assert_called_once()
        self.assertNotEqual(dialog.result(), QDialog.Accepted)

    # -- enabled state ----------------------------------------------------------

    def test_edge_unavailable_disables_edge_widgets(self):
        dialog = self.make_dialog(edge_available=False)
        for widget in (dialog.edgeCheck, dialog.edgeWidthSpin, dialog.edgeThresholdSpin):
            self.assertFalse(widget.isEnabled(), widget.objectName())
            self.assertIn("GRASS", widget.toolTip())
            self.assertIn("i.zc", widget.toolTip())
        # Re-checking the box can't enable the spins while GRASS is missing.
        dialog.edgeCheck.setChecked(True)
        self.assertFalse(dialog.edgeWidthSpin.isEnabled())

    def test_edge_unavailable_keeps_stored_edge_preference(self):
        dialog = self.make_dialog(edge_available=False)
        dialog.accept()
        self.assertIs(stored(self.path)[settings.EDGE], True)

    def test_edge_check_toggles_edge_spins(self):
        dialog = self.make_dialog()
        self.assertTrue(dialog.edgeCheck.isEnabled())
        self.assertTrue(dialog.edgeWidthSpin.isEnabled())
        self.assertTrue(dialog.edgeThresholdSpin.isEnabled())
        dialog.edgeCheck.setChecked(False)
        self.assertFalse(dialog.edgeWidthSpin.isEnabled())
        self.assertFalse(dialog.edgeThresholdSpin.isEnabled())
        dialog.edgeCheck.setChecked(True)
        self.assertTrue(dialog.edgeWidthSpin.isEnabled())

    def test_edge_spins_disabled_when_setting_off(self):
        self.settings.set(settings.EDGE, False)
        dialog = self.make_dialog()
        self.assertFalse(dialog.edgeCheck.isChecked())
        self.assertFalse(dialog.edgeWidthSpin.isEnabled())
        self.assertFalse(dialog.edgeThresholdSpin.isEnabled())

    def test_contrast_check_toggles_percentile_spins(self):
        dialog = self.make_dialog()
        self.assertTrue(dialog.contrastLowerSpin.isEnabled())
        dialog.contrastCheck.setChecked(False)
        self.assertFalse(dialog.contrastLowerSpin.isEnabled())
        self.assertFalse(dialog.contrastUpperSpin.isEnabled())
        dialog.contrastCheck.setChecked(True)
        self.assertTrue(dialog.contrastUpperSpin.isEnabled())


if __name__ == "__main__":
    unittest.main()
