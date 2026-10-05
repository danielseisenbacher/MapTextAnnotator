# -*- coding: utf-8 -*-
"""Tests for annotation_pipeline.py. Raster statistics and edge density are
patched; their own tests live in test_raster_stats.py / test_edge_density.py."""

import unittest
from unittest import mock

import utilities

utilities.start_qgis()

import numpy as np  # noqa: E402
from osgeo import gdal, osr  # noqa: E402
from qgis.core import (  # noqa: E402
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsProject,
    QgsRasterLayer,
)
from qgis.PyQt.QtCore import QDateTime  # noqa: E402

pipeline = utilities.import_plugin_module("annotation_pipeline")
schema = utilities.import_plugin_module("schema")
plugin_settings = utilities.import_plugin_module("settings")
raster_stats = utilities.import_plugin_module("core.raster_stats")
edge_density = utilities.import_plugin_module("core.edge_density")

# 100 x 100 m rasters (1 m pixels) in EPSG:32633
ORIGIN_X, ORIGIN_Y = 500000.0, 5300000.0
GEOTRANSFORM = (ORIGIN_X, 1.0, 0.0, ORIGIN_Y, 0.0, -1.0)

# A word box inside the rasters, drawn counter-clockwise from the bottom-left corner
X0, Y0, X1, Y1 = ORIGIN_X + 10, ORIGIN_Y - 60, ORIGIN_X + 50, ORIGIN_Y - 50
RECT_WKT = f"POLYGON(({X0} {Y0}, {X1} {Y0}, {X1} {Y1}, {X0} {Y1}, {X0} {Y0}))"
# Odd vertex count: can't be split into lower / upper edges
FIVE_WKT = f"POLYGON(({X0} {Y0}, {X0 + 20} {Y0}, {X1} {Y0}, {X1} {Y1}, {X0} {Y1}, {X0} {Y0}))"
# Far outside every raster
OUTSIDE_WKT = "POLYGON((600000 5000000, 600040 5000000, 600040 5000010, 600000 5000010, 600000 5000000))"

ZONAL = {"mean": 412.345, "median": 410.0, "min": 400.004, "max": 425.5, "count": 400}


def multipoint(wkt):
    geom = QgsGeometry.fromWkt(wkt)
    return [(p.x(), p.y()) for p in geom.asMultiPoint()]


class PipelineTestCase(unittest.TestCase):
    def setUp(self):
        self.project = QgsProject.instance()
        self.paths = []
        self.store, _ = utilities.temp_settings_store()
        self.settings = plugin_settings.PluginSettings(self.store)
        self.layer = utilities.make_annotation_layer()
        self.assertTrue(self.layer.startEditing())
        self.warnings = []

        # every test gets fresh mocks for the core computations
        self.zonal = self._patch(raster_stats, "zonal_stats", return_value=dict(ZONAL))
        self.contrast = self._patch(raster_stats, "contrast", return_value=0.4567)
        self.edge = self._patch(edge_density, "edge_density", return_value=0.1234)

    def tearDown(self):
        self.layer.rollBack()
        self.project.removeAllMapLayers()
        for path in self.paths:
            utilities.remove_raster(path)

    def _patch(self, module, name, **kwargs):
        patcher = mock.patch.object(module, name, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def add_raster(self, name, epsg=32633, geotransform=GEOTRANSFORM, bands=1, add=True):
        data = np.zeros((bands, 100, 100), dtype=np.uint8)
        path = utilities.make_raster(data, geotransform, epsg=epsg)
        self.paths.append(path)
        layer = QgsRasterLayer(path, name, "gdal")
        self.assertTrue(layer.isValid())
        if add:
            self.project.addMapLayer(layer)
        return layer

    def hide(self, layer):
        self.project.layerTreeRoot().findLayer(layer.id()).setItemVisibilityChecked(False)

    def add_feature(self, wkt=RECT_WKT, layer=None, **attributes):
        layer = layer or self.layer
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt(wkt))
        for name, value in attributes.items():
            feature[name] = value
        self.assertTrue(layer.addFeature(feature))
        return feature.id()

    def context(self, **kwargs):
        kwargs.setdefault("warn", lambda key, message: self.warnings.append((key, message)))
        return pipeline.PipelineContext(self.layer, self.settings, **kwargs)

    def value(self, fid, name, layer=None):
        return (layer or self.layer).getFeature(fid)[name]

    def warning_keys(self):
        return [key for key, _ in self.warnings]

    def disable(self, *keys):
        for key in keys:
            self.settings.set(key, False)


class SetAttrTests(PipelineTestCase):
    def test_editable_layer(self):
        fid = self.add_feature()
        self.assertTrue(pipeline.set_attr(self.layer, fid, "Word Transcription", "Wien"))
        self.assertEqual(self.value(fid, "Word Transcription"), "Wien")
        self.assertTrue(pipeline.set_attr(self.layer, fid, "Word Transcription", None))
        self.assertIsNone(self.value(fid, "Word Transcription"))

    def test_missing_field(self):
        fid = self.add_feature()
        self.assertFalse(pipeline.set_attr(self.layer, fid, "No Such Field", 1))

    def test_non_editable_layer(self):
        layer = utilities.make_annotation_layer()
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt(RECT_WKT))
        layer.dataProvider().addFeature(feature)
        fid = next(layer.getFeatures()).id()
        self.assertFalse(layer.isEditable())
        self.assertFalse(pipeline.set_attr(layer, fid, "Word Transcription", "Wien"))
        self.assertIsNone(self.value(fid, "Word Transcription", layer))


class ReferenceRasterTests(PipelineTestCase):
    def find(self, wkt=RECT_WKT, **kwargs):
        return pipeline.find_reference_raster(QgsGeometry.fromWkt(wkt), self.context(**kwargs))

    def test_top_most_visible_wins(self):
        bottom = self.add_raster("bottom")
        top = self.add_raster("top")  # added last -> top of the layer tree
        self.assertEqual(self.find().id(), top.id())
        self.hide(top)
        self.assertEqual(self.find().id(), bottom.id())
        self.hide(bottom)
        self.assertIsNone(self.find())

    def test_layer_tree_order_not_insertion_order(self):
        first = self.add_raster("first")
        second = self.add_raster("second")
        root = self.project.layerTreeRoot()
        # move "first" above "second"
        node = root.findLayer(first.id())
        clone = node.clone()
        root.insertChildNode(0, clone)
        root.removeChildNode(node)
        self.assertEqual(root.layerOrder()[0].id(), first.id())
        self.assertEqual(self.find().id(), first.id())
        self.assertNotEqual(self.find().id(), second.id())

    def test_excluded_dem_never_chosen(self):
        scan = self.add_raster("scan")
        dem = self.add_raster("dem")  # top-most and visible
        self.assertEqual(self.find().id(), dem.id())
        self.assertEqual(self.find(excluded_layer_ids=frozenset({dem.id()})).id(), scan.id())
        self.assertIsNone(self.find(excluded_layer_ids=frozenset({dem.id(), scan.id()})))

    def test_non_intersecting_raster_ignored(self):
        self.add_raster("scan")
        self.assertIsNone(self.find(OUTSIDE_WKT))

    def test_xyz_layer_ignored(self):
        scan = self.add_raster("scan")
        xyz = QgsRasterLayer(
            "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0", "osm", "wms"
        )
        self.project.addMapLayer(xyz)  # top-most, covers the whole world
        self.assertEqual(self.find().id(), scan.id())

    def test_missing_file_ignored(self):
        scan = self.add_raster("scan")
        broken = QgsRasterLayer("/nonexistent/scan.tif", "broken", "gdal")
        self.project.addMapLayer(broken)
        self.assertEqual(self.find().id(), scan.id())
        # valid layer whose file was removed after loading
        gone = self.add_raster("gone")
        gdal.Unlink(gone.source())
        self.paths.remove(gone.source())
        self.assertTrue(gone.isValid())
        self.assertEqual(self.find().id(), scan.id())

    def test_layer_not_in_layer_tree_ignored(self):
        scan = self.add_raster("scan")
        orphan = self.add_raster("orphan", add=False)
        self.project.addMapLayer(orphan, False)  # registered, but no layer tree node
        self.assertIsNone(self.project.layerTreeRoot().findLayer(orphan.id()))
        self.assertEqual(self.find().id(), scan.id())

    def test_raster_in_other_crs(self):
        # the same area as a raster in EPSG:4326
        src, dst = osr.SpatialReference(), osr.SpatialReference()
        src.ImportFromEPSG(32633)
        dst.ImportFromEPSG(4326)
        dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        lon, lat, _ = osr.CoordinateTransformation(src, dst).TransformPoint(ORIGIN_X, ORIGIN_Y)
        geographic = self.add_raster("geographic", epsg=4326, geotransform=(lon, 1e-5, 0, lat, 0, -1e-5))
        self.assertEqual(self.find().id(), geographic.id())


class ProcessFeatureTests(PipelineTestCase):
    def test_all_fields_written(self):
        scan = self.add_raster("scan", bands=3)
        dem = self.add_raster("dem")
        slope = self.add_raster("slope")
        fid = self.add_feature()
        ctx = self.context(dem_layer=dem, slope_layer=slope,
                           excluded_layer_ids=frozenset({dem.id(), slope.id()}))

        result = pipeline.process_feature(fid, ctx)

        self.assertEqual(self.warnings, [])
        self.assertTrue(result.ok)
        self.assertEqual(result.reference_image, scan.source())
        self.assertEqual(self.value(fid, "Reference Image"), scan.source())

        self.assertEqual(multipoint(self.value(fid, "Bounding Points")),
                         [(X0, Y0), (X1, Y0), (X1, Y1), (X0, Y1)])
        self.assertEqual(multipoint(self.value(fid, "Bounding Box")), [(X0, Y0), (X1, Y1)])
        obb = multipoint(self.value(fid, "Oriented Bounding Box"))
        self.assertEqual(len(obb), 4)
        self.assertEqual(sorted(obb), sorted([(X0, Y0), (X1, Y0), (X1, Y1), (X0, Y1)]))

        lower = multipoint(self.value(fid, "Lower Bezier"))
        upper = multipoint(self.value(fid, "Upper Bezier"))
        self.assertEqual(len(lower), 4)
        self.assertEqual(len(upper), 4)
        self.assertEqual(lower[0], (X0, Y0))   # bottom-left -> bottom-right
        self.assertEqual(lower[-1], (X1, Y0))
        self.assertEqual(upper[0], (X1, Y1))   # top-right -> top-left
        self.assertEqual(upper[-1], (X0, Y1))

        self.assertAlmostEqual(self.value(fid, "Mean Altitude"), 412.35)
        self.assertEqual(self.value(fid, "Median Altitude"), 410.0)
        self.assertEqual(self.value(fid, "Max Altitude"), 425.5)
        self.assertEqual(self.value(fid, "Min Altitude"), 400.0)
        self.assertAlmostEqual(self.value(fid, "Mean Slope"), 412.35)
        self.assertAlmostEqual(self.value(fid, "Complexity"), 0.12)
        self.assertAlmostEqual(self.value(fid, "Contrast"), 0.46)
        self.assertEqual(result.stats, {"altitude": 412.35, "slope": 412.35,
                                        "edge_complexity": 0.12, "contrast": 0.46})

        # zonal stats on the DEM / slope layers given in the context (not looked up by name)
        paths = [c.args[0] for c in self.zonal.call_args_list]
        self.assertEqual(paths, [dem.source(), slope.source()])
        self.assertTrue(QgsGeometry.fromWkt(self.zonal.call_args.args[1]).equals(QgsGeometry.fromWkt(RECT_WKT)))

        # edge / contrast on the reference image with the configured parameters
        self.edge.assert_called_once()
        args, kwargs = self.edge.call_args
        self.assertEqual(args[0], scan.source())
        self.assertTrue(QgsGeometry.fromWkt(args[1]).equals(QgsGeometry.fromWkt(RECT_WKT)))
        self.assertEqual(kwargs, {"width": 3, "threshold": 5.0, "buffer_ratio": 0.1})
        self.contrast.assert_called_once()
        self.assertEqual(self.contrast.call_args.args[0], scan.source())
        self.assertEqual(self.contrast.call_args.args[2:], (5.0, 95.0))

    def test_settings_are_passed_through(self):
        self.add_raster("scan")
        self.settings.set(plugin_settings.EDGE_WIDTH, 5)
        self.settings.set(plugin_settings.EDGE_THRESHOLD, 2.5)
        self.settings.set(plugin_settings.EDGE_BUFFER, 0.3)
        self.settings.set(plugin_settings.CONTRAST_LOWER, 10.0)
        self.settings.set(plugin_settings.CONTRAST_UPPER, 90.0)
        self.disable(plugin_settings.ALTITUDE, plugin_settings.SLOPE)
        pipeline.process_feature(self.add_feature(), self.context())
        self.assertEqual(self.edge.call_args.kwargs, {"width": 5, "threshold": 2.5, "buffer_ratio": 0.3})
        self.assertEqual(self.contrast.call_args.args[2:], (10.0, 90.0))

    def test_dem_on_top_is_not_reference_image(self):
        scan = self.add_raster("scan")
        dem = self.add_raster("dem")  # top-most, visible
        self.disable(plugin_settings.SLOPE)
        fid = self.add_feature()
        result = pipeline.process_feature(
            fid, self.context(dem_layer=dem, excluded_layer_ids=frozenset({dem.id()})))
        self.assertEqual(result.reference_image, scan.source())
        self.assertEqual(self.value(fid, "Reference Image"), scan.source())
        self.assertEqual(self.zonal.call_args.args[0], dem.source())

    def test_dem_and_slope_disabled(self):
        self.add_raster("scan")
        self.disable(plugin_settings.ALTITUDE, plugin_settings.SLOPE)
        fid = self.add_feature(**{"Mean Altitude": 42.0, "Mean Slope": 7.0})
        result = pipeline.process_feature(fid, self.context())
        self.zonal.assert_not_called()
        self.assertEqual(self.warnings, [])
        self.assertTrue(result.ok)
        # fields of disabled stats are left alone
        self.assertEqual(self.value(fid, "Mean Altitude"), 42.0)
        self.assertEqual(self.value(fid, "Mean Slope"), 7.0)
        self.assertNotIn("altitude", result.stats)
        self.assertNotIn("slope", result.stats)

    def test_dem_enabled_without_layer_warns_once(self):
        self.add_raster("scan")
        fid = self.add_feature(**{"Mean Altitude": 42.0})
        result = pipeline.process_feature(fid, self.context())
        self.zonal.assert_not_called()
        self.assertEqual(self.warning_keys().count(pipeline.WARN_NO_DEM), 1)
        self.assertEqual(self.warning_keys().count(pipeline.WARN_NO_SLOPE), 1)
        self.assertFalse(result.ok)
        self.assertEqual(self.value(fid, "Mean Altitude"), 42.0)
        # the other steps still ran
        self.assertIsNotNone(self.value(fid, "Contrast"))
        self.assertIsNotNone(self.value(fid, "Lower Bezier"))

    def test_disabled_stats_are_skipped_silently(self):
        self.add_raster("scan")
        self.disable(plugin_settings.ALTITUDE, plugin_settings.SLOPE, plugin_settings.EDGE,
                     plugin_settings.CONTRAST, plugin_settings.CENTROID)
        fid = self.add_feature(**{"Complexity": 0.9, "Contrast": 0.8, "Lat": 1.0, "Lon": 2.0})
        result = pipeline.process_feature(fid, self.context())
        self.assertEqual(self.warnings, [])
        self.assertEqual(result.stats, {})
        self.edge.assert_not_called()
        self.contrast.assert_not_called()
        self.assertEqual(self.value(fid, "Complexity"), 0.9)
        self.assertEqual(self.value(fid, "Contrast"), 0.8)
        self.assertEqual(self.value(fid, "Lat"), 1.0)
        self.assertEqual(self.value(fid, "Lon"), 2.0)
        self.assertIsNotNone(self.value(fid, "Upper Bezier"))

    def test_invalid_geometry(self):
        self.add_raster("scan")
        self.disable(plugin_settings.ALTITUDE, plugin_settings.SLOPE)
        fid = self.add_feature(FIVE_WKT, **{"Lower Bezier": "stale", "Upper Bezier": "stale"})
        result = pipeline.process_feature(fid, self.context())
        self.assertFalse(result.ok)
        self.assertEqual(self.warning_keys(), [pipeline.WARN_INVALID_GEOMETRY])
        message = self.warnings[0][1]
        self.assertIn("4 vertices", message)
        self.assertIn("same number of vertices", message)
        # stale curves never survive a geometry edit
        self.assertIsNone(self.value(fid, "Lower Bezier"))
        self.assertIsNone(self.value(fid, "Upper Bezier"))
        # the other steps still ran
        self.assertNotEqual(self.value(fid, "Reference Image"), schema.NO_REFERENCE_IMAGE)
        self.assertEqual(len(multipoint(self.value(fid, "Bounding Points"))), 5)
        self.assertIsNotNone(self.value(fid, "Lat"))
        self.assertAlmostEqual(self.value(fid, "Contrast"), 0.46)
        self.assertAlmostEqual(self.value(fid, "Complexity"), 0.12)

    def test_too_few_vertices(self):
        self.disable(plugin_settings.ALTITUDE, plugin_settings.SLOPE)
        self.add_raster("scan")
        triangle = f"POLYGON(({X0} {Y0}, {X1} {Y0}, {X0} {Y1}, {X0} {Y0}))"
        fid = self.add_feature(triangle)
        pipeline.process_feature(fid, self.context())
        self.assertEqual(self.warning_keys(), [pipeline.WARN_INVALID_GEOMETRY])
        self.assertIsNone(self.value(fid, "Lower Bezier"))

    def test_clockwise_drawing_gives_storage_order(self):
        self.add_raster("scan")
        self.disable(plugin_settings.ALTITUDE, plugin_settings.SLOPE)
        clockwise = f"POLYGON(({X0} {Y0}, {X0} {Y1}, {X1} {Y1}, {X1} {Y0}, {X0} {Y0}))"
        fid = self.add_feature(clockwise)
        pipeline.process_feature(fid, self.context())
        lower = multipoint(self.value(fid, "Lower Bezier"))
        upper = multipoint(self.value(fid, "Upper Bezier"))
        self.assertEqual((lower[0], lower[-1]), ((X0, Y0), (X1, Y0)))
        self.assertEqual((upper[0], upper[-1]), ((X1, Y1), (X0, Y1)))

    def test_failing_zonal_stats_does_not_stop_contrast(self):
        self.add_raster("scan")
        dem = self.add_raster("dem")
        self.zonal.side_effect = raster_stats.RasterStatsError("cannot open")
        self.disable(plugin_settings.SLOPE)
        fid = self.add_feature(**{"Mean Altitude": 42.0})
        result = pipeline.process_feature(
            fid, self.context(dem_layer=dem, excluded_layer_ids=frozenset({dem.id()})))
        self.assertFalse(result.ok)
        self.assertEqual(self.warning_keys(), [pipeline.WARN_STAT_FAILED])
        self.assertIn("cannot open", self.warnings[0][1])
        self.assertIsNone(self.value(fid, "Mean Altitude"))
        self.assertIsNone(result.stats["altitude"])
        self.contrast.assert_called_once()
        self.assertAlmostEqual(self.value(fid, "Contrast"), 0.46)
        self.assertAlmostEqual(self.value(fid, "Complexity"), 0.12)

    def test_zonal_stats_none_clears_fields(self):
        self.add_raster("scan")
        dem = self.add_raster("dem")
        self.zonal.return_value = None  # polygon outside the DEM
        self.disable(plugin_settings.SLOPE)
        fid = self.add_feature(**{"Mean Altitude": 42.0})
        result = pipeline.process_feature(fid, self.context(dem_layer=dem))
        self.assertIsNone(self.value(fid, "Mean Altitude"))
        self.assertIsNone(result.stats["altitude"])
        self.assertTrue(result.ok)

    def test_edge_unavailable(self):
        self.add_raster("scan")
        self.disable(plugin_settings.ALTITUDE, plugin_settings.SLOPE)
        self.edge.side_effect = edge_density.EdgeDensityUnavailable("no GRASS")
        fid = self.add_feature(**{"Complexity": 0.9})
        result = pipeline.process_feature(fid, self.context())
        self.assertEqual(self.warning_keys(), [pipeline.WARN_EDGE_UNAVAILABLE])
        self.assertEqual(self.value(fid, "Complexity"), 0.9)
        self.assertNotIn("edge_complexity", result.stats)
        self.assertAlmostEqual(self.value(fid, "Contrast"), 0.46)

    def test_no_reference_raster(self):
        self.disable(plugin_settings.ALTITUDE, plugin_settings.SLOPE)
        stale = {name: "stale" for name in pipeline.BOUNDING_FIELDS + pipeline.BEZIER_FIELDS}
        fid = self.add_feature(OUTSIDE_WKT, **stale, **{"Complexity": 0.9, "Contrast": 0.8})
        self.add_raster("scan")
        result = pipeline.process_feature(fid, self.context())
        self.assertFalse(result.ok)
        self.assertEqual(self.warning_keys(), [pipeline.WARN_NO_REFERENCE])
        self.assertIsNone(result.reference_image)
        self.assertEqual(self.value(fid, "Reference Image"), schema.NO_REFERENCE_IMAGE)
        for name in stale:
            self.assertIsNone(self.value(fid, name), name)
        self.edge.assert_not_called()
        self.contrast.assert_not_called()
        self.assertIsNone(self.value(fid, "Complexity"))
        self.assertIsNone(self.value(fid, "Contrast"))
        self.assertIsNotNone(self.value(fid, "Lat"))

    def test_centroid_in_wgs84(self):
        self.disable(plugin_settings.ALTITUDE, plugin_settings.SLOPE)
        fid = self.add_feature()
        pipeline.process_feature(fid, self.context())

        src, dst = osr.SpatialReference(), osr.SpatialReference()
        src.ImportFromEPSG(32633)
        dst.ImportFromEPSG(4326)
        src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        lon, lat, _ = osr.CoordinateTransformation(src, dst).TransformPoint((X0 + X1) / 2, (Y0 + Y1) / 2)
        self.assertAlmostEqual(self.value(fid, "Lat"), lat, places=7)
        self.assertAlmostEqual(self.value(fid, "Lon"), lon, places=7)
        self.assertAlmostEqual(lon, 15.0, places=2)  # UTM 33N central meridian

    def test_coordinates_stored_in_raster_crs(self):
        # annotation layer in EPSG:4326, reference raster in EPSG:32633
        self.layer = utilities.make_annotation_layer(crs="EPSG:4326")
        self.layer.startEditing()
        self.disable(plugin_settings.ALTITUDE, plugin_settings.SLOPE)
        scan = self.add_raster("scan")
        geom = QgsGeometry.fromWkt(RECT_WKT)
        geom.transform(QgsCoordinateTransform(scan.crs(), self.layer.crs(), self.project))
        fid = self.add_feature(geom.asWkt())

        result = pipeline.process_feature(fid, self.context())
        self.assertEqual(self.warnings, [])
        self.assertEqual(result.reference_image, scan.source())
        bbox = multipoint(self.value(fid, "Bounding Box"))
        for (x, y), (ex, ey) in zip(bbox, [(X0, Y0), (X1, Y1)]):
            self.assertAlmostEqual(x, ex, places=3)
            self.assertAlmostEqual(y, ey, places=3)
        lower = multipoint(self.value(fid, "Lower Bezier"))
        self.assertAlmostEqual(lower[0][0], X0, places=3)
        self.assertAlmostEqual(lower[0][1], Y0, places=3)
        # the statistics get the polygon in the raster's CRS too
        stats_bbox = QgsGeometry.fromWkt(self.contrast.call_args.args[1]).boundingBox()
        self.assertAlmostEqual(stats_bbox.xMinimum(), X0, places=3)
        self.assertAlmostEqual(stats_bbox.yMaximum(), Y1, places=3)

    def test_missing_feature_never_raises(self):
        result = pipeline.process_feature(123456, self.context())
        self.assertFalse(result.ok)
        self.assertEqual(self.warning_keys(), [pipeline.WARN_INVALID_GEOMETRY])

    def test_raising_warn_callback_never_raises(self):
        def warn(key, message):
            raise RuntimeError("broken callback")

        fid = self.add_feature(FIVE_WKT)
        result = pipeline.process_feature(fid, self.context(warn=warn))
        self.assertFalse(result.ok)

    def test_layer_without_stat_fields(self):
        fields = {name: schema.FIELDS[name] for name in schema.CORE_FIELDS}
        self.layer = utilities.make_annotation_layer(fields=fields)
        self.layer.startEditing()
        self.add_raster("scan")
        dem = self.add_raster("dem")
        fid = self.add_feature()
        result = pipeline.process_feature(
            fid, self.context(dem_layer=dem, excluded_layer_ids=frozenset({dem.id()})))
        self.assertIsNotNone(self.value(fid, "Lower Bezier"))
        self.assertEqual(self.warning_keys(), [pipeline.WARN_NO_SLOPE])
        self.assertEqual(result.stats["contrast"], 0.46)


class StoredValueTests(PipelineTestCase):
    def test_stored_stats(self):
        fid = self.add_feature(**{"Mean Altitude": 412.35, "Complexity": 0.12})
        stats = pipeline.stored_stats(self.layer.getFeature(fid))
        self.assertEqual(stats, {"altitude": 412.35, "slope": None, "edge_complexity": 0.12, "contrast": None})

    def test_stored_stats_missing_fields(self):
        fields = {name: schema.FIELDS[name] for name in schema.CORE_FIELDS}
        layer = utilities.make_annotation_layer(fields=fields)
        layer.startEditing()
        fid = self.add_feature(layer=layer)
        stats = pipeline.stored_stats(layer.getFeature(fid))
        self.assertEqual(stats, dict.fromkeys(pipeline.DISPLAY_STATS))

    def test_transcription(self):
        t0 = QDateTime.currentDateTime()
        a = self.add_feature(**{"Word Transcription": "Neusiedler", "Create Date": t0})
        b = self.add_feature(**{"Word Transcription": "See", "Create Date": t0.addSecs(10),
                                "Link to previous Word": True})
        c = self.add_feature(**{"Word Transcription": "Graz", "Create Date": t0.addSecs(5),
                                "Link to previous Word": False})
        # Graz was created between the two words, so "See" links to "Graz"
        self.assertEqual(pipeline.transcription_for(self.layer, b), ("See", "Graz See"))
        self.assertEqual(pipeline.transcription_for(self.layer, a), ("Neusiedler", "Neusiedler"))
        self.layer.changeAttributeValue(c, self.layer.fields().indexOf("Create Date"), t0.addSecs(20))
        self.assertEqual(pipeline.transcription_for(self.layer, b), ("See", "Neusiedler See"))

    def test_transcription_with_nulls(self):
        t0 = QDateTime.currentDateTime()
        a = self.add_feature(**{"Word Transcription": "Bad", "Create Date": t0})
        b = self.add_feature(**{"Word Transcription": "Ischl", "Link to previous Word": True})  # NULL date
        c = self.add_feature(**{"Create Date": t0.addSecs(5)})  # NULL word, NULL link
        # NULL dates sort last: Bad, <empty>, Ischl (linked to the empty word)
        self.assertEqual(pipeline.transcription_for(self.layer, c), (None, " Ischl"))
        self.assertEqual(pipeline.transcription_for(self.layer, b), ("Ischl", " Ischl"))
        self.assertEqual(pipeline.transcription_for(self.layer, a), ("Bad", "Bad"))
        self.assertEqual(pipeline.transcription_for(self.layer, 987654), (None, None))

    def test_dataset_counts(self):
        self.assertEqual(pipeline.dataset_counts(self.layer), (0, 0, 0))
        self.add_feature(**{"Reference Image": "/data/a.tif"})
        self.add_feature(**{"Reference Image": "/data/a.tif", "Link to previous Word": True})
        self.add_feature(**{"Reference Image": "/data/b.tif", "Link to previous Word": False})
        self.add_feature(**{"Reference Image": schema.NO_REFERENCE_IMAGE})
        self.add_feature(**{"Reference Image": ""})
        self.add_feature()  # all NULL
        self.assertEqual(pipeline.dataset_counts(self.layer), (6, 5, 2))


if __name__ == "__main__":
    unittest.main()
