# -*- coding: utf-8 -*-
"""
End-to-end test without mocks of the pipeline: plugin dock -> generated layer ->
features drawn inside edit commands -> stored attributes -> JSON export.

Scan raster: EPSG:32633, origin (500000, 5000100), 1 m pixels, 200 x 100 px,
so pixel x = X - 500000 and pixel y = 5000100 - Y.
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import utilities

utilities.start_qgis()

import numpy as np  # noqa: E402
from qgis.core import (  # noqa: E402
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsGeometry,
    QgsProject,
    QgsRasterLayer,
)
from qgis.PyQt.QtCore import QDateTime  # noqa: E402
from qgis.testing.mocked import get_iface  # noqa: E402

plugin_module = utilities.import_plugin_module("MaptextAnnotator")
settings_module = utilities.import_plugin_module("settings")
creator = utilities.import_plugin_module("coco.annotation_creator")

SCAN_GT = (500000.0, 1.0, 0.0, 5000100.0, 0.0, -1.0)
DEM_GT = (499900.0, 10.0, 0.0, 5000200.0, 0.0, -10.0)
DEM_HEIGHT = 512.0

# Word rectangle: pixel x 10..50, pixel y 60..80
BL, BR, TR, TL = (500010, 5000020), (500050, 5000020), (500050, 5000040), (500010, 5000040)


def ring_wkt(points):
    coords = ", ".join(f"{x} {y}" for x, y in list(points) + [points[0]])
    return f"POLYGON(({coords}))"


def ccw_ring(n_per_edge):
    """Counter-clockwise ring from BL with n_per_edge vertices on the bottom and the top edge."""
    xs = np.linspace(BL[0], BR[0], n_per_edge)
    bottom = [(x, BL[1]) for x in xs]
    top = [(x, TL[1]) for x in xs[::-1]]
    return bottom + top


class IntegrationTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="mta-integration-")
        rgb = np.stack([
            np.tile(np.arange(200, dtype=np.uint8), (100, 1)),
            np.full((100, 200), 100, dtype=np.uint8),
            np.full((100, 200), 50, dtype=np.uint8),
        ])
        cls.scan_path = utilities.make_raster(rgb, SCAN_GT, path=os.path.join(cls.tmp, "scan.tif"))
        cls.dem_path = utilities.make_raster(np.full((40, 40), DEM_HEIGHT, dtype=np.float32), DEM_GT,
                                             nodata=-9999, path=os.path.join(cls.tmp, "dem.tif"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        project = QgsProject.instance()
        project.removeAllMapLayers()
        project.setCrs(QgsCoordinateReferenceSystem("EPSG:32633"))

        self.store, _ = utilities.temp_settings_store()
        self.settings = settings_module.PluginSettings(self.store)
        self.settings.set(settings_module.EDGE, False)  # GRASS is slow; covered in test_edge_density
        self.settings.save()

        self.scan = QgsRasterLayer(self.scan_path, "scan")
        self.dem = QgsRasterLayer(self.dem_path, "dem")
        self.assertTrue(self.scan.isValid() and self.dem.isValid())
        project.addMapLayer(self.scan)

        self.iface = get_iface()
        with mock.patch.object(plugin_module, "PluginSettings", lambda *a, **k: settings_module.PluginSettings(self.store)):
            self.plugin = plugin_module.MaptextAnnotator(self.iface)
        self.plugin.initGui()
        self.plugin.run()
        self.dock = self.plugin.dockwidget

        self.plugin.createPolyLayer()
        self.layer = QgsProject.instance().mapLayersByName("Annotation Layer")[0]
        self.dock.annotationLayerCombo.setLayer(self.layer)

    def tearDown(self):
        if self.layer.isEditable():
            self.layer.rollBack()
        self.plugin.unload()
        QgsProject.instance().removeAllMapLayers()

    # -- helpers -------------------------------------------------------------

    def add_word(self, points, word, linked=False):
        feature = QgsFeature(self.layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt(ring_wkt(points)))
        feature["Word Transcription"] = word
        feature["Link to previous Word"] = linked
        feature["Create Date"] = QDateTime.currentDateTime()
        feature["Certainty"] = 3
        if not self.layer.isEditable():
            self.layer.startEditing()
        self.layer.beginEditCommand("add word")
        self.assertTrue(self.layer.addFeature(feature))
        self.layer.endEditCommand()

    def commit(self):
        self.assertTrue(self.layer.commitChanges(), self.layer.commitErrors())

    def features_by_word(self):
        return {f["Word Transcription"]: f for f in self.layer.getFeatures()}

    def warning_texts(self):
        return [" ".join(str(a) for a in c.args) for c in self.iface.messageBar().pushMessage.call_args_list]

    # -- tests ---------------------------------------------------------------

    def test_attributes_without_dem_and_slope(self):
        self.settings.set(settings_module.ALTITUDE, False)
        self.settings.set(settings_module.SLOPE, False)
        self.settings.save()
        self.plugin.settings.load()
        self.dock.apply_settings(self.plugin.settings)

        self.add_word(ccw_ring(2), "Wien")
        self.add_word(ccw_ring(3), "am", linked=True)
        self.add_word(ccw_ring(4), "Main", linked=True)
        self.commit()

        words = self.features_by_word()
        for word in ("Wien", "am", "Main"):
            f = words[word]
            self.assertEqual(f["Reference Image"], self.scan_path)
            self.assertTrue(f["Upper Bezier"] and f["Lower Bezier"], word)
            self.assertTrue(f["Bounding Box"], word)
            self.assertIsNone(f["Mean Altitude"])
            self.assertIsNone(f["Mean Slope"])
            self.assertAlmostEqual(f["Lon"], 15.0, delta=0.01)
            self.assertAlmostEqual(f["Lat"], 45.14, delta=0.05)
            self.assertIsNotNone(f["Contrast"])
        self.assertFalse(any("DEM" in t or "slope" in t.lower() for t in self.warning_texts()), self.warning_texts())

    def test_dem_stats_and_dem_never_reference_image(self):
        QgsProject.instance().addMapLayer(self.dem)  # added last -> top-most and visible
        self.dock.demLayerCombo.setLayer(self.dem)

        self.add_word(ccw_ring(2), "Berg")
        self.commit()

        f = self.features_by_word()["Berg"]
        self.assertEqual(f["Reference Image"], self.scan_path)
        self.assertAlmostEqual(f["Mean Altitude"], DEM_HEIGHT)
        self.assertAlmostEqual(f["Max Altitude"], DEM_HEIGHT)

    def test_clockwise_drawing_is_corrected(self):
        self.add_word([BL, TL, TR, BR], "CW")
        self.add_word(ccw_ring(2), "CCW")
        self.commit()
        words = self.features_by_word()
        self.assertEqual(words["CW"]["Upper Bezier"], words["CCW"]["Upper Bezier"])
        self.assertEqual(words["CW"]["Lower Bezier"], words["CCW"]["Lower Bezier"])

    def test_invalid_geometry_is_kept_but_skipped_at_export(self):
        self.add_word([BL, BR, TR, TL, (500005, 5000030)], "odd")
        self.add_word(ccw_ring(2), "ok")
        self.commit()
        self.assertIsNone(self.features_by_word()["odd"]["Upper Bezier"] or None)

        coco, skipped = creator.build_annotations(creator.records_from_layer(self.layer))
        self.assertEqual(len(coco["annotations"]), 1)
        self.assertEqual(len(skipped), 1)

    def test_export_formats_and_orders(self):
        self.add_word(ccw_ring(2), "Wort")
        self.commit()
        records = creator.records_from_layer(self.layer)

        expected_bbox = {
            "xyxy": [10, 60, 50, 80],
            "xywh": [10, 60, 40, 20],
            "polygon": [10, 60, 50, 60, 50, 80, 10, 80],
        }
        for fmt, expected in expected_bbox.items():
            for order in settings_module.BEZIER_ORDERS:
                with self.subTest(fmt=fmt, order=order):
                    coco, skipped = creator.build_annotations(records, bbox_format=fmt, bezier_order=order)
                    json.dumps(coco)
                    self.assertEqual(skipped, [])
                    self.assertEqual(coco["images"][0]["width"], 200)
                    self.assertEqual(coco["images"][0]["height"], 100)
                    self.assertEqual(coco["images"][0]["file_name"], "scan.tif")
                    ann = coco["annotations"][0]
                    np.testing.assert_allclose(ann["bbox"], expected, atol=1e-6)
                    pts = np.array(ann["bezier_pts"]).reshape(8, 2)
                    if order == "abcnet":
                        np.testing.assert_allclose(pts[0], (10, 60), atol=1e-6)  # top, left -> right
                        np.testing.assert_allclose(pts[3], (50, 60), atol=1e-6)
                        np.testing.assert_allclose(pts[4], (50, 80), atol=1e-6)  # bottom, right -> left
                        np.testing.assert_allclose(pts[7], (10, 80), atol=1e-6)
                    else:
                        np.testing.assert_allclose(pts[0], (50, 60), atol=1e-6)
                        np.testing.assert_allclose(pts[3], (10, 60), atol=1e-6)
                        np.testing.assert_allclose(pts[4], (50, 80), atol=1e-6)
                        np.testing.assert_allclose(pts[7], (10, 80), atol=1e-6)

    def test_export_button_writes_file_with_settings(self):
        self.settings.set(settings_module.BBOX_FORMAT, "xywh")
        self.settings.set(settings_module.CONTRAST, False)
        self.settings.save()
        self.plugin.settings.load()

        self.add_word(ccw_ring(2), "Datei")
        self.commit()

        out = os.path.join(self.tmp, "export.json")
        with mock.patch.object(plugin_module.QFileDialog, "getSaveFileName", return_value=(out, "")):
            self.plugin.exportAnnotationsButtonClicked()
            self.plugin.exportAnnotationsButtonClicked()  # second export must not accumulate

        with open(out, encoding="utf-8") as f:
            coco = json.load(f)
        self.assertEqual(coco["info"]["bbox_format"], "xywh")
        self.assertEqual(len(coco["images"]), 1)
        self.assertEqual(len(coco["annotations"]), 1)
        ann = coco["annotations"][0]
        np.testing.assert_allclose(ann["bbox"], [10, 60, 40, 20], atol=1e-6)
        self.assertNotIn("contrast", ann)
        self.assertIn("mean_altitude", ann)


if __name__ == "__main__":
    unittest.main()
