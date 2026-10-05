# -*- coding: utf-8 -*-
"""
MapText Annotator plugin controller.

Owns the menu / toolbar actions and the dock widget, and wires the current
annotation layer and the project to the per-feature pipeline
(annotation_pipeline) and the COCO export (coco.annotation_creator).
No computation happens here.

(C) 2026 Daniel Seisenbacher, GPL-2.0-or-later.
"""

import os

from qgis.PyQt import sip
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QDialog, QFileDialog
from qgis.core import Qgis, QgsApplication, QgsCoordinateReferenceSystem, QgsField, QgsProject, QgsVectorLayer

from . import annotation_pipeline, resources, schema  # noqa: F401  resources registers the icon
from . import settings as plugin_settings
from .coco import annotation_creator
from .core import edge_density
from .MaptextAnnotator_dockwidget import MaptextAnnotatorDockWidget
from .settings import PluginSettings
from .settings_dialog import SettingsDialog

MENU = "&MapText Annotator"
ICON_PATH = ":/plugins/MaptextAnnotator/icon.png"
MESSAGE_TITLE = "MapText Annotator"
LAYER_BASE_NAME = "Annotation Layer"
STYLE_FILE = "annotator_style.qml"
FALLBACK_CRS = "EPSG:4326"

TITLE_LAST_CREATED = "Last Created Annotation"
TITLE_LAST_EDITED = "Last Edited Annotation"
TITLE_SELECTED = "Selected Annotation"

# How many skipped features are listed in the export message
MAX_SKIPPED_SHOWN = 3


def _disconnect_all(connections):
    """Disconnect (signal, slot) pairs one by one, so a pair that is already
    gone (deleted sender, never connected) doesn't keep the others connected."""
    for signal, slot in connections:
        try:
            signal.disconnect(slot)
        except (TypeError, RuntimeError):
            pass


def _alive(obj):
    return obj is not None and not sip.isdeleted(obj)


class MaptextAnnotator:
    """QGIS plugin implementation."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.settings = PluginSettings()

        self.actions = []
        self.toolbar = None
        self.dockwidget = None
        self.current_layer = None

        self._dock_connections = []
        self._layer_connections = []
        self._project_connections = []
        self._warned = set()
        self._scratch_hint_shown = False
        self._recomputing = False
        self._project_busy = False

        # Coalesces count refreshes: a commit emits featureAdded / featureDeleted per feature
        self._counts_timer = QTimer()
        self._counts_timer.setSingleShot(True)
        self._counts_timer.setInterval(0)
        self._counts_timer.timeout.connect(self._refresh_counts)

    # -- QGIS plugin interface ------------------------------------------------

    def initGui(self):
        """Create the menu entries, the toolbar icon and the project connections."""
        self.toolbar = self.iface.addToolBar("MaptextAnnotator")
        self.toolbar.setObjectName("MaptextAnnotator")
        self._add_action(QIcon(ICON_PATH), "Annotate MapText", self.run, add_to_toolbar=True)
        self._add_action(QgsApplication.getThemeIcon("/mActionOptions.svg"), "Settings…", self.open_settings)

        project = QgsProject.instance()
        self._project_connections = [
            (project.aboutToBeCleared, self._on_project_busy),
            (project.loadingLayer, self._on_project_busy),
            (project.readProject, self._on_project_read),
            (project.cleared, self._on_project_cleared),
            (project.layerWillBeRemoved[str], self._on_layer_will_be_removed),
        ]
        for signal, slot in self._project_connections:
            signal.connect(slot)

    def _add_action(self, icon, text, callback, add_to_toolbar=False):
        action = QAction(icon, text, self.iface.mainWindow())
        action.triggered.connect(callback)
        self.iface.addPluginToMenu(MENU, action)
        if add_to_toolbar:
            self.toolbar.addAction(action)
        self.actions.append(action)
        return action

    def unload(self):
        """Remove menu entries, toolbar and dock, and disconnect everything.
        Safe to call when run() was never called."""
        self._counts_timer.stop()
        self._disconnect_layer()
        _disconnect_all(self._project_connections)
        self._project_connections = []

        dock, self.dockwidget = self.dockwidget, None
        _disconnect_all(self._dock_connections)
        self._dock_connections = []
        if _alive(dock):
            dock.teardown()
            self.iface.removeDockWidget(dock)
            dock.deleteLater()

        for action in self.actions:
            self.iface.removePluginMenu(MENU, action)
            if self.toolbar is not None:
                self.toolbar.removeAction(action)
            action.deleteLater()
        self.actions = []
        if self.toolbar is not None:
            self.toolbar.deleteLater()
            self.toolbar = None

    def run(self, *_args):
        """Show the dock, creating it on first use."""
        if not _alive(self.dockwidget):
            self._create_dock()
            self._set_annotation_layer(self.dockwidget.annotationLayerCombo.currentLayer())
        self.dockwidget.apply_settings(self.settings)
        self._restore_layer_choices()
        self._refresh_counts()
        self.dockwidget.show()
        self.dockwidget.raise_()

    def _create_dock(self):
        dock = MaptextAnnotatorDockWidget(self.iface.mainWindow())
        self.dockwidget = dock
        self._dock_connections = [
            (dock.annotationLayerCombo.layerChanged, self._on_annotation_layer_changed),
            (dock.demLayerCombo.layerChanged, self._on_dem_layer_changed),
            (dock.slopeLayerCombo.layerChanged, self._on_slope_layer_changed),
            (dock.generateLayer.clicked, self.createPolyLayer),
            (dock.exportAnnotationsButton.clicked, self.exportAnnotationsButtonClicked),
            (dock.settingsButton.clicked, self.open_settings),
            (dock.recomputeButton.clicked, self.recompute_selected),
            (dock.closingPlugin, self._on_dock_closed),
        ]
        for signal, slot in self._dock_connections:
            signal.connect(slot)
        self.iface.addDockWidget(Qt.RightDockWidgetArea, dock)

    def _on_dock_closed(self):
        # Annotation processing goes on while the dock is hidden; only the display pauses.
        self._counts_timer.stop()

    # -- messages -------------------------------------------------------------

    def _message(self, text, level=Qgis.Info, duration=5):
        self.iface.messageBar().pushMessage(MESSAGE_TITLE, text, level=level, duration=duration)

    def _warn_once(self, key, message):
        """Show a warning at most once per key until the cache is cleared
        (settings or layer selection change)."""
        if key in self._warned:
            return
        self._warned.add(key)
        self._message(message, Qgis.Warning, duration=10)

    def _clear_warnings(self):
        self._warned.clear()

    def _parent_widget(self):
        return self.dockwidget if _alive(self.dockwidget) else self.iface.mainWindow()

    # -- project --------------------------------------------------------------

    def _save_layer_choice(self, key, layer):
        if self._project_busy:
            return
        project = QgsProject.instance()
        if _alive(layer):
            project.writeEntry(plugin_settings.PROJECT_SCOPE, key, layer.id())
        else:
            project.removeEntry(plugin_settings.PROJECT_SCOPE, key)

    def _restore_layer_choices(self):
        """Select the DEM, slope and annotation layers stored in the project,
        where they still exist."""
        dock = self.dockwidget
        if not _alive(dock):
            return
        project = QgsProject.instance()
        for key, combo in ((plugin_settings.PROJECT_DEM_LAYER, dock.demLayerCombo),
                           (plugin_settings.PROJECT_SLOPE_LAYER, dock.slopeLayerCombo),
                           (plugin_settings.PROJECT_ANNOTATION_LAYER, dock.annotationLayerCombo)):
            layer_id, found = project.readEntry(plugin_settings.PROJECT_SCOPE, key, "")
            layer = project.mapLayer(layer_id) if found and layer_id else None
            # setLayer() with a layer the combo filters out would clear the combo
            if layer is not None and any(combo.layer(i) is not None and combo.layer(i).id() == layer_id
                                         for i in range(combo.count())):
                combo.setLayer(layer)

    def _on_project_busy(self, *_args):
        # While a project is cleared or loaded, the combos follow the layers being
        # removed / added (properties are already replaced): don't store those choices.
        self._project_busy = True

    def _on_project_read(self, *_args):
        self._project_busy = False
        self._clear_warnings()
        self._restore_layer_choices()

    def _on_project_cleared(self):
        # The layers are already deleted at this point
        self._project_busy = False
        self._disconnect_layer()
        self._clear_warnings()
        self._refresh_counts()
        self._reset_info()

    def _on_layer_will_be_removed(self, layer_id):
        layer = self._live_layer()
        if layer is not None and layer.id() == layer_id:
            self._set_annotation_layer(None)

    # -- dock combos ----------------------------------------------------------

    def _on_annotation_layer_changed(self, layer):
        self._save_layer_choice(plugin_settings.PROJECT_ANNOTATION_LAYER, layer)
        self._clear_warnings()
        self._set_annotation_layer(layer)

    def _on_dem_layer_changed(self, layer):
        self._save_layer_choice(plugin_settings.PROJECT_DEM_LAYER, layer)
        self._clear_warnings()

    def _on_slope_layer_changed(self, layer):
        self._save_layer_choice(plugin_settings.PROJECT_SLOPE_LAYER, layer)
        self._clear_warnings()

    # -- annotation layer connections -----------------------------------------

    def _live_layer(self):
        """The current annotation layer, or None if unset or already deleted."""
        if not _alive(self.current_layer):
            self.current_layer = None
        return self.current_layer

    def _set_annotation_layer(self, layer):
        self._disconnect_layer()
        if _alive(layer) and isinstance(layer, QgsVectorLayer):
            self._connect_layer(layer)
        self._refresh_counts()
        self._show_selection()

    def _connect_layer(self, layer):
        self.current_layer = layer
        self._layer_connections = [
            (layer.featureAdded, self._on_feature_added),
            (layer.geometryChanged, self._on_geometry_changed),
            (layer.featureDeleted, self._on_feature_deleted),
            (layer.selectionChanged, self._on_selection_changed),
            (layer.afterCommitChanges, self._on_edits_finished),
            (layer.afterRollBack, self._on_edits_finished),
        ]
        for signal, slot in self._layer_connections:
            signal.connect(slot)

    def _disconnect_layer(self):
        _disconnect_all(self._layer_connections)
        self._layer_connections = []
        self.current_layer = None

    def _on_feature_added(self, fid):
        self._on_feature_changed(fid, TITLE_LAST_CREATED)
        self._schedule_counts()

    def _on_geometry_changed(self, fid, _geometry):
        self._on_feature_changed(fid, TITLE_LAST_EDITED)

    def _on_feature_changed(self, fid, title):
        """Recompute a feature after a user add / geometry edit. Undo, redo and
        the replay during a commit happen outside an edit command and only
        restore already computed attributes, so they are ignored."""
        layer = self._live_layer()
        if layer is None or self._recomputing:
            return
        if not (layer.isEditable() and layer.isEditCommandActive()):
            return
        self._recompute(layer, fid, title)

    def _on_feature_deleted(self, _fid):
        self._schedule_counts()
        self._reset_info()

    def _on_selection_changed(self, *_args):
        self._show_selection()

    def _on_edits_finished(self, *_args):
        self._schedule_counts()
        self._show_selection()

    # -- computation and display ----------------------------------------------

    def _pipeline_context(self, layer):
        dock = self.dockwidget
        dem = dock.demLayerCombo.currentLayer() if _alive(dock) else None
        slope = dock.slopeLayerCombo.currentLayer() if _alive(dock) else None
        return annotation_pipeline.PipelineContext(
            layer=layer,
            settings=self.settings,
            dem_layer=dem,
            slope_layer=slope,
            # Never use the DEM / slope as reference image, even when their stats are off
            excluded_layer_ids=frozenset(lyr.id() for lyr in (dem, slope) if lyr is not None),
            fallback_crs=self.iface.mapCanvas().mapSettings().destinationCrs(),
            warn=self._warn_once,
        )

    def _recompute(self, layer, fid, title):
        """Run the pipeline for one feature (writes into the edit buffer) and show the result."""
        self._recomputing = True
        try:
            result = annotation_pipeline.process_feature(fid, self._pipeline_context(layer))
        finally:
            self._recomputing = False
        dock = self.dockwidget
        if _alive(dock):
            dock.show_stats(result.stats)
            dock.show_transcription(*annotation_pipeline.transcription_for(layer, fid))
            dock.annotationTitleLabel.setText(title)
        self._schedule_counts()

    def recompute_selected(self, *_args):
        """Recompute the single selected feature as one undoable edit command."""
        layer = self._live_layer()
        if layer is None:
            self._message("Select an annotation layer first.")
            return
        if not layer.isEditable():
            self._message("Toggle editing on the annotation layer to recompute its statistics.")
            return
        selected = layer.selectedFeatureIds()
        if len(selected) != 1:
            self._message("Select exactly one annotation to recompute.")
            return
        layer.beginEditCommand("Recompute annotation statistics")
        try:
            self._recompute(layer, selected[0], TITLE_SELECTED)
        except Exception:
            layer.destroyEditCommand()
            raise
        layer.endEditCommand()

    def _show_selection(self):
        """Display the stored values of the single selected feature; no recomputation."""
        dock = self.dockwidget
        layer = self._live_layer()
        if not _alive(dock) or layer is None:
            self._reset_info()
            return
        selected = layer.selectedFeatureIds()
        feature = layer.getFeature(selected[0]) if len(selected) == 1 else None
        if feature is None or not feature.isValid():
            self._reset_info()
            return
        dock.show_stats(annotation_pipeline.stored_stats(feature))
        dock.show_transcription(*annotation_pipeline.transcription_for(layer, feature.id()))
        dock.annotationTitleLabel.setText(TITLE_SELECTED)

    def _reset_info(self):
        dock = self.dockwidget
        if _alive(dock):
            dock.reset_annotation_info()
            dock.annotationTitleLabel.setText(TITLE_LAST_CREATED)

    def _schedule_counts(self):
        if _alive(self.dockwidget):
            self._counts_timer.start()

    def _refresh_counts(self):
        dock = self.dockwidget
        if not _alive(dock):
            return
        layer = self._live_layer()
        if layer is None:
            dock.show_dataset_counts(None, None, None)
        else:
            dock.show_dataset_counts(*annotation_pipeline.dataset_counts(layer))

    # -- actions --------------------------------------------------------------

    def createPolyLayer(self, *_args):
        """Add a new memory annotation layer with the full schema and select it."""
        project = QgsProject.instance()
        name, number = LAYER_BASE_NAME, 2
        while project.mapLayersByName(name):
            name = f"{LAYER_BASE_NAME} {number}"
            number += 1

        crs = project.crs()
        if not crs.isValid():
            crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        if not crs.isValid():
            crs = QgsCoordinateReferenceSystem(FALLBACK_CRS)

        layer = QgsVectorLayer("Polygon", name, "memory")
        layer.setCrs(crs)
        layer.dataProvider().addAttributes([QgsField(field, field_type) for field, field_type in schema.FIELDS.items()])
        layer.updateFields()
        message, ok = layer.loadNamedStyle(os.path.join(self.plugin_dir, STYLE_FILE))
        if not ok:
            self._message(f"Could not load the annotation style: {message}", Qgis.Warning)
        project.addMapLayer(layer)

        if _alive(self.dockwidget):
            self.dockwidget.annotationLayerCombo.setLayer(layer)
        if not self._scratch_hint_shown:
            self._scratch_hint_shown = True
            self._message(
                f"'{name}' is a temporary scratch layer: its annotations are lost when QGIS closes. "
                "Save it with Layer > Make Permanent or Export > Save Features As.",
                Qgis.Info, duration=15)
        return layer

    def open_settings(self, *_args):
        edge_available = edge_density.edge_algorithm_id() is not None
        dialog = SettingsDialog(self.settings, self._parent_widget(), edge_available=edge_available)
        if dialog.exec_() != QDialog.Accepted:
            return
        self._clear_warnings()
        if _alive(self.dockwidget):
            self.dockwidget.apply_settings(self.settings)
        if self.settings.stat_enabled("edge_complexity") and not edge_available:
            self._warn_once(annotation_pipeline.WARN_EDGE_UNAVAILABLE,
                            "Edge complexity is enabled, but GRASS (i.zc) is not available. "
                            "Enable the GRASS processing provider or turn edge complexity off in the settings.")

    def exportAnnotationsButtonClicked(self, *_args):
        """Export the current annotation layer to a COCO-style JSON file."""
        layer = self._live_layer()
        if layer is None:
            self._message("No annotation layer selected, nothing to export.", Qgis.Warning)
            return

        last_dir = self.settings.get(plugin_settings.LAST_DIR)
        start = os.path.join(last_dir, "annotations.json") if last_dir and os.path.isdir(last_dir) else "annotations.json"
        path, _ = QFileDialog.getSaveFileName(self._parent_widget(), "Export Annotations", start, "JSON Files (*.json)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        self.settings.set(plugin_settings.LAST_DIR, os.path.dirname(path))
        self.settings.save()

        try:
            records = annotation_creator.records_from_layer(layer)
            coco, skipped = annotation_creator.build_annotations(
                records,
                bbox_format=self.settings.get(plugin_settings.BBOX_FORMAT),
                bezier_order=self.settings.get(plugin_settings.BEZIER_ORDER),
                enabled_stats=self.settings.enabled_stats(),
            )
            annotation_creator.write_annotations(coco, path)
        except Exception as e:  # report instead of raising into the Qt event loop
            self._message(f"Export failed: {e}", Qgis.Critical, duration=0)
            return

        text = f"Exported {len(coco.get('annotations', []))} annotation(s) to {path}."
        if not skipped:
            self._message(text, Qgis.Success)
            return
        reasons = "; ".join(f"feature {fid}: {reason}" for fid, reason in skipped[:MAX_SKIPPED_SHOWN])
        if len(skipped) > MAX_SKIPPED_SHOWN:
            reasons += f"; and {len(skipped) - MAX_SKIPPED_SHOWN} more"
        self._message(f"{text} Skipped {len(skipped)} feature(s) ({reasons}).", Qgis.Warning, duration=15)
