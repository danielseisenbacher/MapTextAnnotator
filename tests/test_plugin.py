# -*- coding: utf-8 -*-
"""
Tests for the plugin controller (MaptextAnnotator.py): signal wiring, recompute
triggers, layer and project lifecycle, settings, export and unload.

Uses a mocked iface; the per-feature pipeline and the export functions are
patched, so only the controller logic is exercised.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import utilities

utilities.start_qgis()

import numpy as np  # noqa: E402
from qgis.core import (Qgis, QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry, QgsProject,  # noqa: E402
                       QgsRasterLayer, QgsVectorLayer)
from qgis.PyQt.QtCore import QCoreApplication, QEvent  # noqa: E402
from qgis.PyQt.QtWidgets import QDialog  # noqa: E402
from qgis.testing.mocked import get_iface  # noqa: E402

plugin_module = utilities.import_plugin_module("MaptextAnnotator")
pipeline = utilities.import_plugin_module("annotation_pipeline")
settings_module = utilities.import_plugin_module("settings")
schema = utilities.import_plugin_module("schema")
creator = utilities.import_plugin_module("coco.annotation_creator")
edge_density = utilities.import_plugin_module("core.edge_density")

RING = "POLYGON((0 0, 10 0, 10 5, 0 5, 0 0))"
LAYER_SIGNALS = ("featureAdded", "geometryChanged", "featureDeleted", "selectionChanged",
                 "afterCommitChanges", "afterRollBack")
MOVED = "POLYGON((0 0, 12 0, 10 5, 0 5, 0 0))"


def process_events():
    """Run queued timers / signals and delete objects scheduled with deleteLater()."""
    QCoreApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


class ControllerTestCase(unittest.TestCase):

    def setUp(self):
        self.project = QgsProject.instance()
        self.rasters = []
        self.store, _ = utilities.temp_settings_store()
        self.iface = get_iface()

        self.process_feature = self.patch(pipeline, "process_feature",
                                          side_effect=lambda fid, ctx: pipeline.FeatureResult(stats={"altitude": 1.0}))
        self.stored_stats = self.patch(pipeline, "stored_stats", return_value={"altitude": 2.0})
        self.transcription_for = self.patch(pipeline, "transcription_for", return_value=("Wien", "Wien am Main"))
        self.dataset_counts = self.patch(pipeline, "dataset_counts", return_value=(1, 1, 0))

        # Exceptions raised inside Qt slots are only printed; collect them so they fail the test
        self.slot_errors = []
        self.patch(sys, "excepthook", new=lambda etype, value, tb: self.slot_errors.append(value))

        self.plugin = self.new_plugin()
        self.plugin.initGui()

    def tearDown(self):
        for layer in self.project.mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.isEditable():
                layer.rollBack()
        self.plugin.unload()
        self.project.clear()
        process_events()
        for path in self.rasters:
            utilities.remove_raster(path)
        self.assertEqual(self.slot_errors, [])

    # -- helpers -------------------------------------------------------------

    def patch(self, target, name, **kwargs):
        patcher = mock.patch.object(target, name, **kwargs)
        patched = patcher.start()
        self.addCleanup(patcher.stop)
        return patched

    def new_plugin(self):
        with mock.patch.object(plugin_module, "PluginSettings",
                               lambda *a, **k: settings_module.PluginSettings(self.store)):
            return plugin_module.MaptextAnnotator(self.iface)

    def add_layer(self, name="Annotation Layer"):
        layer = utilities.make_annotation_layer(name=name)
        self.project.addMapLayer(layer)
        return layer

    def add_raster(self, name):
        path = utilities.make_raster(np.zeros((10, 10), dtype=np.float32), (0, 1, 0, 10, 0, -1))
        self.rasters.append(path)
        layer = QgsRasterLayer(path, name)
        self.assertTrue(layer.isValid())
        self.project.addMapLayer(layer)
        return layer

    def add_feature(self, layer, wkt=RING, command=True):
        """Add a polygon like the digitizing tools do (inside an edit command)
        or, with command=False, like a replay outside one. Returns the new fid."""
        if not layer.isEditable():
            layer.startEditing()
        before = set(layer.allFeatureIds())
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt(wkt))
        if command:
            layer.beginEditCommand("add")
        self.assertTrue(layer.addFeature(feature))
        if command:
            layer.endEditCommand()
        (fid,) = set(layer.allFeatureIds()) - before
        return fid

    def move_feature(self, layer, fid, command=True):
        if command:
            layer.beginEditCommand("move")
        self.assertTrue(layer.changeGeometry(fid, QgsGeometry.fromWkt(MOVED)))
        if command:
            layer.endEditCommand()

    def messages(self, level=None):
        texts = []
        for call in self.iface.messageBar().pushMessage.call_args_list:
            if level is None or call.kwargs.get("level") == level:
                texts.append(" ".join(str(a) for a in call.args))
        return texts

    def last_context(self):
        return self.process_feature.call_args.args[1]

    @staticmethod
    def receivers(layer):
        """Number of connections per layer signal the controller uses."""
        return {name: layer.receivers(getattr(layer, name)) for name in LAYER_SIGNALS}

    @staticmethod
    def plus_one(counts):
        return {name: count + 1 for name, count in counts.items()}


class LifecycleTest(ControllerTestCase):

    def test_class_factory(self):
        with mock.patch.object(plugin_module, "PluginSettings",
                               lambda *a, **k: settings_module.PluginSettings(self.store)):
            plugin = utilities.load_plugin_package().classFactory(self.iface)
        self.assertIsInstance(plugin, plugin_module.MaptextAnnotator)

    def test_init_gui_and_unload_without_run(self):
        self.assertEqual([a.text() for a in self.plugin.actions], ["Annotate MapText", "Settings…"])
        self.assertEqual(self.iface.addPluginToMenu.call_count, 2)
        self.plugin.toolbar.addAction.assert_called_once_with(self.plugin.actions[0])

        toolbar = self.plugin.toolbar
        self.plugin.unload()
        self.assertEqual(self.iface.removePluginMenu.call_count, 2)
        toolbar.deleteLater.assert_called_once()
        self.assertIsNone(self.plugin.dockwidget)
        self.iface.removeDockWidget.assert_not_called()
        self.plugin.unload()  # idempotent

        layer = self.add_layer()
        self.add_feature(layer)
        self.project.clear()
        self.process_feature.assert_not_called()

    def test_run_twice_creates_one_dock_and_one_recompute_per_add(self):
        layer = self.add_layer()
        self.plugin.run()
        dock = self.plugin.dockwidget
        self.plugin.run()

        self.assertIs(self.plugin.dockwidget, dock)
        self.assertEqual(self.iface.addDockWidget.call_count, 1)
        self.assertEqual(self.plugin.current_layer.id(), layer.id())

        fid = self.add_feature(layer)
        self.process_feature.assert_called_once()
        self.assertEqual(self.process_feature.call_args.args[0], fid)
        self.assertEqual(self.last_context().layer.id(), layer.id())
        self.assertEqual(dock.annotationTitleLabel.text(), "Last Created Annotation")
        self.transcription_for.assert_called_with(layer, fid)

    def test_unload_after_run_disconnects_everything(self):
        layer = self.add_layer()
        baseline = self.receivers(layer)
        self.plugin.run()
        self.assertEqual(self.receivers(layer), self.plus_one(baseline))
        dock = self.plugin.dockwidget
        fid = self.add_feature(layer)
        self.process_feature.reset_mock()
        self.stored_stats.reset_mock()

        with mock.patch.object(dock, "teardown", wraps=dock.teardown) as teardown:
            self.plugin.unload()
        teardown.assert_called_once()
        self.iface.removeDockWidget.assert_called_once_with(dock)
        self.assertIsNone(self.plugin.dockwidget)
        self.assertEqual(self.receivers(layer), baseline)
        process_events()

        self.add_feature(layer)
        self.move_feature(layer, fid)
        layer.selectByIds([fid])
        self.project.removeMapLayer(layer.id())
        self.add_layer("Other")
        self.project.clear()
        process_events()
        self.process_feature.assert_not_called()
        self.stored_stats.assert_not_called()

    def test_dock_signals_connected_once(self):
        self.plugin.run()
        self.plugin.run()
        with mock.patch.object(plugin_module.QFileDialog, "getSaveFileName", return_value=("", "")) as dialog:
            self.add_layer()
            self.plugin.dockwidget.exportAnnotationsButton.click()
        dialog.assert_called_once()


class RecomputeTriggerTest(ControllerTestCase):

    def setUp(self):
        super().setUp()
        self.layer = self.add_layer()
        self.plugin.run()

    def test_no_recompute_outside_edit_command_undo_redo_or_commit(self):
        fid = self.add_feature(self.layer)
        self.move_feature(self.layer, fid)
        self.assertEqual(self.process_feature.call_count, 2)
        self.process_feature.reset_mock()

        self.add_feature(self.layer, command=False)  # e.g. a replay outside any edit command
        self.move_feature(self.layer, fid, command=False)
        stack = self.layer.undoStack()
        for _ in range(4):
            stack.undo()
        for _ in range(4):
            stack.redo()
        self.assertTrue(self.layer.commitChanges(), self.layer.commitErrors())
        self.process_feature.assert_not_called()

    def test_geometry_change_in_edit_command_recomputes(self):
        fid = self.add_feature(self.layer)
        self.process_feature.reset_mock()

        self.move_feature(self.layer, fid)
        self.process_feature.assert_called_once()
        self.assertEqual(self.process_feature.call_args.args[0], fid)
        self.assertEqual(self.plugin.dockwidget.annotationTitleLabel.text(), "Last Edited Annotation")

    def test_failed_commit_keeps_triggers_working(self):
        fid = self.add_feature(self.layer)
        # the memory provider rejects the value -> beforeCommitChanges without afterCommitChanges
        self.layer.changeAttributeValue(fid, self.layer.fields().indexOf("Mean Altitude"), "not a number")
        self.assertFalse(self.layer.commitChanges(False))
        self.assertTrue(self.layer.isEditable())
        self.process_feature.reset_mock()

        self.add_feature(self.layer)
        self.process_feature.assert_called_once()

    def test_selection_only_displays_stored_values(self):
        fid = self.add_feature(self.layer)
        second = self.add_feature(self.layer)
        self.process_feature.reset_mock()
        dock = self.plugin.dockwidget

        with mock.patch.object(dock, "show_stats") as show_stats:
            self.layer.selectByIds([fid])
        show_stats.assert_called_once_with({"altitude": 2.0})
        self.assertEqual(self.stored_stats.call_args.args[0].id(), fid)
        self.assertEqual(dock.annotationTitleLabel.text(), "Selected Annotation")

        with mock.patch.object(dock, "reset_annotation_info") as reset:
            self.layer.selectByIds([fid, second])
        reset.assert_called_once()
        self.process_feature.assert_not_called()

    def test_delete_resets_info(self):
        fid = self.add_feature(self.layer)
        with mock.patch.object(self.plugin.dockwidget, "reset_annotation_info") as reset:
            self.layer.deleteFeature(fid)
        reset.assert_called()

    def test_commit_refreshes_counts_once(self):
        for _ in range(3):
            self.add_feature(self.layer)
        process_events()
        self.dataset_counts.reset_mock()

        self.assertTrue(self.layer.commitChanges(), self.layer.commitErrors())
        process_events()
        self.assertEqual(self.dataset_counts.call_count, 1)
        self.assertEqual(self.dataset_counts.call_args.args[0].id(), self.layer.id())

    def test_recompute_button(self):
        button = self.plugin.dockwidget.recomputeButton
        button.click()  # layer not editable
        fid = self.add_feature(self.layer)
        self.process_feature.reset_mock()
        button.click()  # nothing selected
        self.process_feature.assert_not_called()
        self.assertEqual(len(self.messages(Qgis.Info)), 2)

        def write_word(fid, ctx):
            ctx.layer.changeAttributeValue(fid, ctx.layer.fields().indexOf("Reference Image"), "scan.tif")
            return pipeline.FeatureResult(reference_image="scan.tif")

        self.process_feature.side_effect = write_word
        self.layer.selectByIds([fid])
        stack = self.layer.undoStack()
        count = stack.count()
        button.click()
        self.process_feature.assert_called_once()
        self.assertEqual(self.process_feature.call_args.args[0], fid)
        self.assertEqual(stack.count(), count + 1)
        self.assertEqual(stack.text(stack.count() - 1), "Recompute annotation statistics")
        self.assertFalse(self.layer.isEditCommandActive())

        stack.undo()  # the recompute is one undoable step
        self.assertFalse(self.layer.getFeature(fid)["Reference Image"])

    def test_recompute_button_failure_destroys_edit_command(self):
        fid = self.add_feature(self.layer)
        self.layer.selectByIds([fid])
        count = self.layer.undoStack().count()
        self.process_feature.side_effect = RuntimeError("boom")
        with self.assertRaises(RuntimeError):
            self.plugin.recompute_selected()
        self.assertFalse(self.layer.isEditCommandActive())
        self.assertEqual(self.layer.undoStack().count(), count)


class LayerSwitchTest(ControllerTestCase):

    def test_switching_layers_moves_connections(self):
        first = self.add_layer("A")
        second = self.add_layer("B")
        baseline = {first.id(): self.receivers(first), second.id(): self.receivers(second)}
        self.plugin.run()
        combo = self.plugin.dockwidget.annotationLayerCombo
        combo.setLayer(first)
        combo.setLayer(second)

        self.add_feature(first)
        self.process_feature.assert_not_called()
        self.add_feature(second)
        self.process_feature.assert_called_once()
        self.assertEqual(self.last_context().layer.id(), second.id())

        for layer in (first, second, first, second, first):
            combo.setLayer(layer)
        self.assertEqual(self.receivers(first), self.plus_one(baseline[first.id()]))
        self.assertEqual(self.receivers(second), baseline[second.id()])
        self.process_feature.reset_mock()
        self.add_feature(first)
        self.process_feature.assert_called_once()

    def test_failed_disconnect_does_not_leak_other_connections(self):
        first = self.add_layer("A")
        second = self.add_layer("B")
        baseline = self.receivers(first)
        self.plugin.run()
        combo = self.plugin.dockwidget.annotationLayerCombo
        combo.setLayer(first)
        fid = self.add_feature(first)
        first.featureAdded.disconnect(self.plugin._on_feature_added)  # first pair now fails to disconnect

        combo.setLayer(second)
        self.assertEqual(self.receivers(first), baseline)
        self.process_feature.reset_mock()
        self.move_feature(first, fid)
        self.process_feature.assert_not_called()

    def test_removing_current_layer(self):
        layer = self.add_layer()
        self.plugin.run()
        self.add_feature(layer)
        self.project.removeMapLayer(layer.id())
        process_events()
        self.assertIsNone(self.plugin.current_layer)

        other = self.add_layer("Other")
        self.process_feature.reset_mock()
        self.add_feature(other)
        self.process_feature.assert_called_once()
        self.assertEqual(self.last_context().layer.id(), other.id())

    def test_project_clear(self):
        layer = self.add_layer()
        self.plugin.run()
        self.add_feature(layer)
        self.project.clear()
        process_events()
        self.assertIsNone(self.plugin.current_layer)
        self.plugin.exportAnnotationsButtonClicked()  # no layer: warning, no crash
        self.plugin.recompute_selected()

        other = self.add_layer("Other")
        self.process_feature.reset_mock()
        self.add_feature(other)
        self.process_feature.assert_called_once()


class CreateLayerTest(ControllerTestCase):

    def test_create_layer(self):
        self.project.setCrs(QgsCoordinateReferenceSystem("EPSG:32633"))
        self.plugin.run()
        layer = self.plugin.createPolyLayer()

        self.assertEqual(layer.name(), "Annotation Layer")
        self.assertTrue(layer.isValid())
        self.assertEqual(layer.crs().authid(), "EPSG:32633")
        self.assertEqual({f.name(): f.type() for f in layer.fields()}, dict(schema.FIELDS))
        self.assertIn(layer.id(), self.project.mapLayers())
        self.assertEqual(self.plugin.dockwidget.annotationLayerCombo.currentLayer().id(), layer.id())
        self.assertEqual(self.plugin.current_layer.id(), layer.id())
        self.assertEqual(self.messages(Qgis.Warning), [])  # style loaded

        second = self.plugin.createPolyLayer()
        third = self.plugin.createPolyLayer()
        self.assertEqual(second.name(), "Annotation Layer 2")
        self.assertEqual(third.name(), "Annotation Layer 3")
        self.assertEqual(self.plugin.current_layer.id(), third.id())
        self.assertEqual(len([t for t in self.messages(Qgis.Info) if "temporary" in t]), 1)

    def test_create_layer_without_project_crs_has_valid_crs(self):
        self.assertFalse(self.project.crs().isValid())
        layer = self.plugin.createPolyLayer()  # also works before run()
        self.assertTrue(layer.crs().isValid())

    def test_generate_button(self):
        self.plugin.run()
        self.plugin.dockwidget.generateLayer.click()
        self.assertEqual(len(self.project.mapLayersByName("Annotation Layer")), 1)

    def test_style_failure_warns(self):
        self.plugin.plugin_dir = tempfile.gettempdir()  # no annotator_style.qml there
        layer = self.plugin.createPolyLayer()
        self.assertTrue(layer.isValid())
        self.assertEqual(len(self.messages(Qgis.Warning)), 1)


class ContextAndWarningTest(ControllerTestCase):

    def test_add_without_dem_and_slope(self):
        self.plugin.settings.set(settings_module.ALTITUDE, False)
        self.plugin.settings.set(settings_module.SLOPE, False)
        layer = self.add_layer()
        self.plugin.run()
        self.add_feature(layer)

        ctx = self.last_context()
        self.assertIsNone(ctx.dem_layer)
        self.assertIsNone(ctx.slope_layer)
        self.assertEqual(ctx.excluded_layer_ids, frozenset())
        self.assertIs(ctx.settings, self.plugin.settings)
        self.assertEqual(self.messages(Qgis.Warning), [])

    def test_chosen_dem_and_slope_are_passed_and_excluded(self):
        self.plugin.settings.set(settings_module.SLOPE, False)
        dem = self.add_raster("dem")
        slope = self.add_raster("slope")
        layer = self.add_layer()
        self.plugin.run()
        self.plugin.dockwidget.demLayerCombo.setLayer(dem)
        self.plugin.dockwidget.slopeLayerCombo.setLayer(slope)
        self.add_feature(layer)

        ctx = self.last_context()
        self.assertEqual(ctx.dem_layer.id(), dem.id())
        self.assertEqual(ctx.slope_layer.id(), slope.id())
        self.assertEqual(ctx.excluded_layer_ids, frozenset({dem.id(), slope.id()}))

    def test_warn_once(self):
        self.plugin._warn_once("a", "first a")
        self.plugin._warn_once("a", "second a")
        self.plugin._warn_once("b", "first b")
        self.assertEqual(len(self.messages(Qgis.Warning)), 2)
        self.plugin._clear_warnings()
        self.plugin._warn_once("a", "third a")
        self.assertEqual(len(self.messages(Qgis.Warning)), 3)

    def test_pipeline_warnings_shown_once_until_layers_change(self):
        def warn(fid, ctx):
            ctx.warn(pipeline.WARN_NO_DEM, "no DEM chosen")
            return pipeline.FeatureResult()

        self.process_feature.side_effect = warn
        dem = self.add_raster("dem")
        layer = self.add_layer()
        self.plugin.run()
        self.add_feature(layer)
        self.add_feature(layer)
        self.assertEqual(len(self.messages(Qgis.Warning)), 1)

        self.plugin.dockwidget.demLayerCombo.setLayer(dem)
        self.add_feature(layer)
        self.assertEqual(len(self.messages(Qgis.Warning)), 2)

        other = self.add_layer("Other")
        self.plugin.dockwidget.annotationLayerCombo.setLayer(other)
        self.add_feature(other)
        self.assertEqual(len(self.messages(Qgis.Warning)), 3)


class SettingsTest(ControllerTestCase):

    def open_settings(self, result, edge_id=None, via_menu=False):
        dialog_class = mock.Mock()
        dialog_class.return_value.exec_.return_value = result
        with mock.patch.object(plugin_module, "SettingsDialog", dialog_class), \
                mock.patch.object(edge_density, "edge_algorithm_id", return_value=edge_id):
            if via_menu:
                self.plugin.actions[1].trigger()
            else:
                self.plugin.dockwidget.settingsButton.click()
        return dialog_class

    def test_accept_applies_settings_and_clears_warnings(self):
        self.plugin.run()
        dock = self.plugin.dockwidget
        self.plugin._warn_once("cached", "cached warning")
        with mock.patch.object(dock, "apply_settings") as apply:
            dialog_class = self.open_settings(QDialog.Accepted, edge_id="grass7:i.zc")
        dialog_class.assert_called_once_with(self.plugin.settings, dock, edge_available=True)
        apply.assert_called_once_with(self.plugin.settings)
        self.plugin._warn_once("cached", "cached warning")
        self.assertEqual(len(self.messages(Qgis.Warning)), 2)

    def test_cancel_changes_nothing(self):
        self.plugin.run()
        with mock.patch.object(self.plugin.dockwidget, "apply_settings") as apply:
            self.open_settings(QDialog.Rejected)
        apply.assert_not_called()
        self.assertEqual(self.messages(), [])

    def test_edge_enabled_without_grass_warns_once(self):
        self.plugin.run()
        dialog_class = self.open_settings(QDialog.Accepted, edge_id=None)
        self.assertFalse(dialog_class.call_args.kwargs["edge_available"])
        self.assertEqual(len([t for t in self.messages(Qgis.Warning) if "GRASS" in t]), 1)
        # the pipeline reporting the same problem doesn't repeat it
        self.plugin._warn_once(pipeline.WARN_EDGE_UNAVAILABLE, "GRASS missing")
        self.assertEqual(len(self.messages(Qgis.Warning)), 1)

        self.plugin.settings.set(settings_module.EDGE, False)
        self.open_settings(QDialog.Accepted, edge_id=None)
        self.assertEqual(len(self.messages(Qgis.Warning)), 1)

    def test_menu_action_without_dock(self):
        dialog_class = self.open_settings(QDialog.Accepted, edge_id="grass7:i.zc", via_menu=True)
        self.assertIs(dialog_class.call_args.args[1], self.iface.mainWindow())
        self.assertIsNone(self.plugin.dockwidget)


class ExportTest(ControllerTestCase):

    def setUp(self):
        super().setUp()
        self.out_dir = tempfile.mkdtemp(prefix="mta-export-")
        self.addCleanup(shutil.rmtree, self.out_dir, True)
        self.layer = self.add_layer()
        self.plugin.run()
        self.records = [{"fid": 1}]
        self.coco = {"annotations": [{"id": 1}], "images": []}
        self.records_from_layer = self.patch(creator, "records_from_layer", return_value=self.records)
        self.build = self.patch(creator, "build_annotations", return_value=(self.coco, []))
        self.write = self.patch(creator, "write_annotations")

    def export(self, path):
        with mock.patch.object(plugin_module.QFileDialog, "getSaveFileName", return_value=(path, "")) as dialog:
            self.plugin.exportAnnotationsButtonClicked()
        return dialog

    def test_export_uses_settings_and_saves_last_dir(self):
        self.plugin.settings.set(settings_module.BBOX_FORMAT, "xywh")
        self.plugin.settings.set(settings_module.BEZIER_ORDER, "legacy")
        self.plugin.settings.set(settings_module.CONTRAST, False)

        self.export(os.path.join(self.out_dir, "out"))
        self.assertEqual(self.records_from_layer.call_args.args[0].id(), self.layer.id())
        self.build.assert_called_once_with(
            self.records, bbox_format="xywh", bezier_order="legacy",
            enabled_stats=frozenset({"altitude", "slope", "edge_complexity", "centroid"}))
        self.write.assert_called_once_with(self.coco, os.path.join(self.out_dir, "out.json"))
        self.assertEqual(settings_module.PluginSettings(self.store).get(settings_module.LAST_DIR), self.out_dir)
        self.assertEqual(len(self.messages(Qgis.Success)), 1)
        self.assertIn("Exported 1", self.messages(Qgis.Success)[0])

        dialog = self.export("")  # cancelled; starts in the last directory
        self.assertEqual(dialog.call_args.args[2], os.path.join(self.out_dir, "annotations.json"))
        self.assertEqual(self.write.call_count, 1)

    def test_skipped_features_are_reported(self):
        self.build.return_value = (self.coco, [(fid, f"reason {fid}") for fid in range(5)])
        self.export(os.path.join(self.out_dir, "out.json"))
        (text,) = self.messages(Qgis.Warning)
        self.assertIn("Skipped 5", text)
        self.assertIn("reason 2", text)
        self.assertNotIn("reason 3", text)
        self.assertIn("2 more", text)

    def test_export_failure_shows_critical_message(self):
        self.build.side_effect = ValueError("boom")
        self.export(os.path.join(self.out_dir, "out.json"))
        (text,) = self.messages(Qgis.Critical)
        self.assertIn("boom", text)
        self.write.assert_not_called()
        self.assertEqual(settings_module.PluginSettings(self.store).get(settings_module.LAST_DIR), self.out_dir)

    def test_export_without_layer_warns(self):
        self.project.removeMapLayer(self.layer.id())
        dialog = self.export(os.path.join(self.out_dir, "out.json"))
        dialog.assert_not_called()
        self.assertEqual(len(self.messages(Qgis.Warning)), 1)


class ProjectEntriesTest(ControllerTestCase):

    def entry(self, key):
        value, found = self.project.readEntry(settings_module.PROJECT_SCOPE, key, "")
        return value if found else None

    def test_dem_and_slope_choice_stored_and_restored_by_fresh_run(self):
        self.add_raster("a raster")
        dem = self.add_raster("b dem")
        slope = self.add_raster("c slope")
        self.plugin.run()
        self.plugin.dockwidget.demLayerCombo.setLayer(dem)
        self.plugin.dockwidget.slopeLayerCombo.setLayer(slope)
        self.assertEqual(self.entry(settings_module.PROJECT_DEM_LAYER), dem.id())
        self.assertEqual(self.entry(settings_module.PROJECT_SLOPE_LAYER), slope.id())

        self.plugin.unload()
        process_events()
        self.plugin = self.new_plugin()
        self.plugin.initGui()
        self.plugin.run()
        self.assertEqual(self.plugin.dockwidget.demLayerCombo.currentLayer().id(), dem.id())
        self.assertEqual(self.plugin.dockwidget.slopeLayerCombo.currentLayer().id(), slope.id())

    def test_stale_entry_is_ignored(self):
        self.project.writeEntry(settings_module.PROJECT_SCOPE, settings_module.PROJECT_DEM_LAYER, "missing")
        self.project.writeEntry(settings_module.PROJECT_SCOPE, settings_module.PROJECT_ANNOTATION_LAYER,
                                self.add_raster("not a vector").id())
        layer = self.add_layer()
        self.plugin.run()
        self.assertEqual(self.plugin.current_layer.id(), layer.id())

    def test_project_read_restores_layer_choices(self):
        # While a project loads, the combos auto-select the first layers before
        # readProject; those transient choices must not overwrite the stored ones.
        self.add_layer("A")
        annotation_id = self.add_layer("B").id()
        self.add_raster("a raster")
        dem_id = self.add_raster("b dem").id()
        self.plugin.run()
        dock = self.plugin.dockwidget
        dock.annotationLayerCombo.setLayer(self.project.mapLayer(annotation_id))
        dock.demLayerCombo.setLayer(self.project.mapLayer(dem_id))
        self.assertEqual(self.entry(settings_module.PROJECT_ANNOTATION_LAYER), annotation_id)
        self.assertEqual(self.entry(settings_module.PROJECT_DEM_LAYER), dem_id)

        tmp = tempfile.mkdtemp(prefix="mta-project-")
        self.addCleanup(shutil.rmtree, tmp, True)
        path = os.path.join(tmp, "project.qgs")
        self.assertTrue(self.project.write(path))
        self.project.clear()
        self.assertIsNone(self.entry(settings_module.PROJECT_ANNOTATION_LAYER))  # nothing written while clearing
        self.assertIsNone(self.entry(settings_module.PROJECT_DEM_LAYER))
        self.assertFalse(self.project.isDirty())

        self.assertTrue(self.project.read(path))
        process_events()
        self.assertEqual(dock.annotationLayerCombo.currentLayer().id(), annotation_id)
        self.assertEqual(dock.demLayerCombo.currentLayer().id(), dem_id)
        self.assertEqual(self.plugin.current_layer.id(), annotation_id)
        self.assertEqual(self.entry(settings_module.PROJECT_ANNOTATION_LAYER), annotation_id)
        other_raster = self.project.mapLayersByName("a raster")[0]
        dock.demLayerCombo.setLayer(other_raster)  # choices are stored again after loading
        self.assertEqual(self.entry(settings_module.PROJECT_DEM_LAYER), other_raster.id())
        dock.demLayerCombo.setLayer(self.project.mapLayer(dem_id))

        self.process_feature.reset_mock()
        self.add_feature(self.project.mapLayer(annotation_id))
        self.process_feature.assert_called_once()
        self.assertEqual(self.last_context().dem_layer.id(), dem_id)


if __name__ == "__main__":
    unittest.main()
