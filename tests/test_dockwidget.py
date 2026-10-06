# -*- coding: utf-8 -*-
"""Tests for the dock widget (MaptextAnnotator_dockwidget.MaptextAnnotatorDockWidget)."""

import unittest
from unittest import mock

import numpy as np

import utilities

utilities.start_qgis()

from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer  # noqa: E402
from qgis.PyQt import sip  # noqa: E402
from qgis.PyQt.QtCore import QCoreApplication, QEvent, QVariant  # noqa: E402

schema = utilities.import_plugin_module("schema")
settings = utilities.import_plugin_module("settings")
dockwidget = utilities.import_plugin_module("MaptextAnnotator_dockwidget")

Dock = dockwidget.MaptextAnnotatorDockWidget
NONE_SELECTED = "None Selected"
CORE_ONLY = {name: schema.FIELDS[name] for name in schema.CORE_FIELDS}


def combo_layers(combo):
    """The layers a QgsMapLayerComboBox offers (the empty entry is skipped)."""
    return [combo.layer(i) for i in range(combo.count()) if combo.layer(i) is not None]


class DockTestCase(unittest.TestCase):

    def setUp(self):
        self.project = QgsProject.instance()
        self.project.removeAllMapLayers()
        self.raster_paths = []
        self.docks = []

    def tearDown(self):
        for dock in self.docks:
            if not sip.isdeleted(dock):
                dock.teardown()
                dock.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.project.removeAllMapLayers()
        for path in self.raster_paths:
            utilities.remove_raster(path)

    def make_dock(self):
        dock = Dock()
        self.docks.append(dock)
        return dock

    def add_raster(self, name="Map scan"):
        path = utilities.make_raster(np.zeros((3, 20, 20), dtype=np.uint8), (500000, 1, 0, 5000020, 0, -1))
        self.raster_paths.append(path)
        layer = QgsRasterLayer(path, name)
        self.assertTrue(layer.isValid())
        self.project.addMapLayer(layer)
        return layer

    def add_vector(self, kind="Point", name="Notes"):
        layer = QgsVectorLayer(kind, name, "memory")
        self.project.addMapLayer(layer)
        return layer

    def add_annotation_layer(self, name="Annotation Layer", fields=None):
        layer = utilities.make_annotation_layer(name=name, fields=fields)
        self.project.addMapLayer(layer)
        return layer

    def plugin_settings(self, **overrides):
        store, _ = utilities.temp_settings_store()
        plugin = settings.PluginSettings(store)
        for key, value in overrides.items():
            plugin.set(key, value)
        return plugin


class LayerComboTest(DockTestCase):

    def test_dem_and_slope_start_empty_with_layers_loaded(self):
        scan = self.add_raster()
        self.add_vector()
        self.add_annotation_layer()
        dock = self.make_dock()
        self.assertIsNone(dock.demLayerCombo.currentLayer())
        self.assertIsNone(dock.slopeLayerCombo.currentLayer())
        # The rasters are offered, just not pre-selected.
        self.assertIn(scan, combo_layers(dock.demLayerCombo))
        self.assertIn(scan, combo_layers(dock.slopeLayerCombo))

    def test_dem_and_slope_start_empty_without_layers(self):
        dock = self.make_dock()
        self.assertIsNone(dock.demLayerCombo.currentLayer())
        self.assertIsNone(dock.slopeLayerCombo.currentLayer())

    def test_rasters_added_later_are_not_auto_selected(self):
        self.add_raster("First")
        dock = self.make_dock()
        later = self.add_raster("Later")
        self.assertIsNone(dock.demLayerCombo.currentLayer())
        self.assertIsNone(dock.slopeLayerCombo.currentLayer())
        self.assertIn(later, combo_layers(dock.demLayerCombo))

    def test_rasters_added_to_empty_project_are_not_auto_selected(self):
        dock = self.make_dock()
        self.add_raster()
        self.assertIsNone(dock.demLayerCombo.currentLayer())
        self.assertIsNone(dock.slopeLayerCombo.currentLayer())

    def test_chosen_dem_can_be_cleared(self):
        dem = self.add_raster("DEM")
        dock = self.make_dock()
        dock.demLayerCombo.setLayer(dem)
        self.assertIs(dock.demLayerCombo.currentLayer(), dem)
        dock.demLayerCombo.setLayer(None)
        self.assertIsNone(dock.demLayerCombo.currentLayer())

    def test_dem_and_slope_combos_offer_rasters_only(self):
        self.add_raster()
        self.add_vector("Point")
        self.add_vector("Polygon", "Polygons")
        self.add_annotation_layer()
        dock = self.make_dock()
        for combo in (dock.demLayerCombo, dock.slopeLayerCombo):
            layers = combo_layers(combo)
            self.assertEqual(len(layers), 1)
            self.assertTrue(all(isinstance(layer, QgsRasterLayer) for layer in layers))

    def test_annotation_combo_filters_by_core_fields(self):
        self.add_raster()
        self.add_vector("Point")
        plain_polygon = self.add_vector("Polygon", "Plain polygon")
        annotation = self.add_annotation_layer()
        core_only = self.add_annotation_layer("Core only", fields=CORE_ONLY)
        dock = self.make_dock()

        offered = combo_layers(dock.annotationLayerCombo)
        self.assertIn(annotation, offered)
        self.assertIn(core_only, offered)
        self.assertNotIn(plain_polygon, offered)
        self.assertEqual(len(offered), 2)

    def test_annotation_combo_requires_matching_field_types(self):
        wrong_type = dict(CORE_ONLY, **{"Create Date": QVariant.String})
        layer = self.add_annotation_layer("Wrong type", fields=wrong_type)
        missing = {name: ftype for name, ftype in CORE_ONLY.items() if name != "Lower Bezier"}
        missing_layer = self.add_annotation_layer("Missing field", fields=missing)
        dock = self.make_dock()
        offered = combo_layers(dock.annotationLayerCombo)
        self.assertNotIn(layer, offered)
        self.assertNotIn(missing_layer, offered)

    def test_annotation_combo_follows_added_and_removed_layers(self):
        dock = self.make_dock()
        plain_polygon = self.add_vector("Polygon", "Plain polygon")
        annotation = self.add_annotation_layer()
        offered = combo_layers(dock.annotationLayerCombo)
        self.assertEqual(offered, [annotation])
        self.assertNotIn(plain_polygon, offered)

        self.project.removeMapLayer(annotation.id())
        self.assertEqual(combo_layers(dock.annotationLayerCombo), [])
        self.assertEqual(len(dock.annotationLayerCombo.exceptedLayerList()), 1)

    def test_layer_has_required_fields(self):
        annotation = utilities.make_annotation_layer()
        self.assertTrue(dockwidget.layer_has_required_fields(annotation, CORE_ONLY))
        self.assertTrue(dockwidget.layer_has_required_fields(annotation, schema.FIELDS))
        self.assertFalse(dockwidget.layer_has_required_fields(None, CORE_ONLY))
        self.assertFalse(dockwidget.layer_has_required_fields(QgsVectorLayer("Polygon", "x", "memory"), CORE_ONLY))


class ApplySettingsTest(DockTestCase):

    STAT_ROWS = {
        settings.ALTITUDE: ("meanAltitudeCaption", "meanAltitudeLabel"),
        settings.SLOPE: ("meanSlopeCaption", "meanSlopeLabel"),
        settings.EDGE: ("complexityCaption", "complexityLabel"),
        settings.CONTRAST: ("contrastCaption", "contrastLabel"),
    }

    def assert_shown(self, dock, name, shown):
        widget = getattr(dock, name)
        self.assertEqual(widget.isHidden(), not shown, name)
        self.assertEqual(widget.isVisibleTo(dock), shown, name)

    def test_defaults_show_everything(self):
        dock = self.make_dock()
        dock.apply_settings(self.plugin_settings())
        for name in ("demLayerWidget", "slopeLayerWidget", "groupBox", "settingsButton", "recomputeButton"):
            self.assert_shown(dock, name, True)
        for caption, label in self.STAT_ROWS.values():
            self.assert_shown(dock, caption, True)
            self.assert_shown(dock, label, True)

    def test_each_stat_toggle_hides_its_row(self):
        dock = self.make_dock()
        for key, (caption, label) in self.STAT_ROWS.items():
            dock.apply_settings(self.plugin_settings(**{key: False}))
            self.assert_shown(dock, caption, False)
            self.assert_shown(dock, label, False)
            for other_key, (other_caption, other_label) in self.STAT_ROWS.items():
                if other_key != key:
                    self.assert_shown(dock, other_caption, True)
                    self.assert_shown(dock, other_label, True)

    def test_altitude_off_hides_dem_picker(self):
        dock = self.make_dock()
        dock.apply_settings(self.plugin_settings(**{settings.ALTITUDE: False}))
        self.assert_shown(dock, "demLayerWidget", False)
        self.assertFalse(dock.demLayerCombo.isVisibleTo(dock))
        self.assert_shown(dock, "slopeLayerWidget", True)
        self.assertTrue(dock.slopeLayerCombo.isVisibleTo(dock))

    def test_slope_off_hides_slope_picker(self):
        dock = self.make_dock()
        dock.apply_settings(self.plugin_settings(**{settings.SLOPE: False}))
        self.assert_shown(dock, "slopeLayerWidget", False)
        self.assertFalse(dock.slopeLayerCombo.isVisibleTo(dock))
        self.assert_shown(dock, "demLayerWidget", True)
        self.assertTrue(dock.demLayerCombo.isVisibleTo(dock))

    def test_settings_button_stays_visible_without_dem_and_slope(self):
        dock = self.make_dock()
        dock.apply_settings(self.plugin_settings(**{settings.ALTITUDE: False, settings.SLOPE: False}))
        self.assert_shown(dock, "demLayerWidget", False)
        self.assert_shown(dock, "slopeLayerWidget", False)
        self.assert_shown(dock, "settingsButton", True)

    def test_settings_can_be_reenabled(self):
        dock = self.make_dock()
        off = {key: False for key in settings.STAT_TOGGLES.values()}
        off[settings.SHOW_INSTRUCTIONS] = False
        dock.apply_settings(self.plugin_settings(**off))
        dock.apply_settings(self.plugin_settings())
        for name in ("demLayerWidget", "slopeLayerWidget", "groupBox"):
            self.assert_shown(dock, name, True)
        for caption, label in self.STAT_ROWS.values():
            self.assert_shown(dock, caption, True)
            self.assert_shown(dock, label, True)

    def test_instructions_follow_setting(self):
        dock = self.make_dock()
        dock.apply_settings(self.plugin_settings(**{settings.SHOW_INSTRUCTIONS: False}))
        self.assert_shown(dock, "groupBox", False)
        dock.apply_settings(self.plugin_settings(**{settings.SHOW_INSTRUCTIONS: True}))
        self.assert_shown(dock, "groupBox", True)

    def test_settings_button_has_icon_and_tooltip(self):
        dock = self.make_dock()
        self.assertFalse(dock.settingsButton.icon().isNull())
        self.assertEqual(dock.settingsButton.toolTip(), "Settings")


class InstructionsTest(DockTestCase):

    def test_collapsing_instructions_hides_contents(self):
        dock = self.make_dock()
        contents = ("graphicsView", "instruction1", "instruction2", "instruction3")
        dock.groupBox.setChecked(False)
        for name in contents:
            self.assertTrue(getattr(dock, name).isHidden(), name)
        dock.groupBox.setChecked(True)
        for name in contents:
            self.assertFalse(getattr(dock, name).isHidden(), name)

    def test_example_image_is_loaded_once(self):
        dock = self.make_dock()
        scene = dock.graphicsView.scene()
        self.assertIsNotNone(scene)
        items = scene.items()
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0].pixmap().isNull())

    def test_example_image_fits_view_when_shown(self):
        dock = self.make_dock()
        dock.resize(400, 900)
        dock.show()
        QCoreApplication.processEvents()
        try:
            view = dock.graphicsView
            item = view.scene().items()[0]
            mapped = view.mapFromScene(item.sceneBoundingRect()).boundingRect()
            self.assertTrue(view.viewport().rect().contains(mapped), (mapped, view.viewport().rect()))
            dock.fit_example_image()
        finally:
            dock.hide()


class DisplayTest(DockTestCase):

    VALUE_LABELS = ("meanAltitudeLabel", "meanSlopeLabel", "complexityLabel", "contrastLabel",
                    "wordTranscriptionLabel", "phraseTranscriptionLabel", "labelCountLabel",
                    "phraseCountLabel", "imageCountLabel")

    def test_initial_texts(self):
        dock = self.make_dock()
        for name in self.VALUE_LABELS:
            self.assertEqual(getattr(dock, name).text(), NONE_SELECTED, name)

    def test_show_stats(self):
        dock = self.make_dock()
        dock.show_stats({"altitude": 1234.5678, "slope": 12, "edge_complexity": 0.0, "contrast": None})
        self.assertEqual(dock.meanAltitudeLabel.text(), "1234.57")
        self.assertEqual(dock.meanSlopeLabel.text(), "12.00")
        self.assertEqual(dock.complexityLabel.text(), "0.00")
        self.assertEqual(dock.contrastLabel.text(), NONE_SELECTED)

    def test_show_stats_missing_and_unusable_values(self):
        dock = self.make_dock()
        dock.show_stats({"altitude": 1.0, "slope": 2.0, "edge_complexity": 3.0, "contrast": 0.5})
        dock.show_stats({"altitude": QVariant(), "slope": float("nan"), "edge_complexity": "n/a"})
        for name in ("meanAltitudeLabel", "meanSlopeLabel", "complexityLabel", "contrastLabel"):
            self.assertEqual(getattr(dock, name).text(), NONE_SELECTED, name)

    def test_show_transcription(self):
        dock = self.make_dock()
        dock.show_transcription("Wien", "Stadt Wien")
        self.assertEqual(dock.wordTranscriptionLabel.text(), "Wien")
        self.assertEqual(dock.phraseTranscriptionLabel.text(), "Stadt Wien")
        dock.show_transcription(None, "")
        self.assertEqual(dock.wordTranscriptionLabel.text(), NONE_SELECTED)
        self.assertEqual(dock.phraseTranscriptionLabel.text(), NONE_SELECTED)
        dock.show_transcription(QVariant(), None)
        self.assertEqual(dock.wordTranscriptionLabel.text(), NONE_SELECTED)

    def test_show_dataset_counts(self):
        dock = self.make_dock()
        dock.show_dataset_counts(12, 3, 1)
        self.assertEqual(dock.labelCountLabel.text(), "12")
        self.assertEqual(dock.phraseCountLabel.text(), "3")
        self.assertEqual(dock.imageCountLabel.text(), "1")
        dock.show_dataset_counts(0, None, None)
        self.assertEqual(dock.labelCountLabel.text(), "0")
        self.assertEqual(dock.phraseCountLabel.text(), NONE_SELECTED)
        self.assertEqual(dock.imageCountLabel.text(), NONE_SELECTED)

    def test_reset_annotation_info(self):
        dock = self.make_dock()
        dock.show_stats({"altitude": 1.0, "slope": 2.0, "edge_complexity": 3.0, "contrast": 0.5})
        dock.show_transcription("Wien", "Stadt Wien")
        dock.show_dataset_counts(5, 2, 1)
        dock.reset_annotation_info()
        for name in self.VALUE_LABELS[:6]:
            self.assertEqual(getattr(dock, name).text(), NONE_SELECTED, name)
        # Dataset counts belong to the layer, not the current annotation.
        self.assertEqual(dock.labelCountLabel.text(), "5")

    def test_close_emits_closing_plugin(self):
        dock = self.make_dock()
        received = []
        dock.closingPlugin.connect(lambda: received.append(True))
        dock.show()
        dock.close()
        self.assertEqual(received, [True])


class TeardownTest(DockTestCase):

    def test_teardown_disconnects_project_signals(self):
        with mock.patch.object(Dock, "filter_unfit_rows") as filter_rows:
            dock = self.make_dock()
            filter_rows.reset_mock()
            self.add_vector("Polygon", "Before teardown")
            self.assertEqual(filter_rows.call_count, 1)

            dock.teardown()
            filter_rows.reset_mock()
            layer = self.add_vector("Polygon", "After teardown")
            self.project.removeMapLayer(layer.id())
            filter_rows.assert_not_called()

    def test_teardown_twice_does_not_raise(self):
        dock = self.make_dock()
        dock.teardown()
        dock.teardown()

    def test_dock_keeps_working_after_teardown(self):
        dock = self.make_dock()
        dock.teardown()
        dock.show_stats({"altitude": 1.0})
        dock.filter_unfit_rows()
        self.assertEqual(dock.meanAltitudeLabel.text(), "1.00")

    def test_layer_changes_after_dock_deletion_without_teardown(self):
        dock = self.make_dock()
        sip.delete(dock)
        layer = self.add_vector("Polygon", "Orphan")
        self.project.removeMapLayer(layer.id())


if __name__ == "__main__":
    unittest.main()
