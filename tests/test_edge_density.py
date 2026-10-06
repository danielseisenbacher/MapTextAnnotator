# -*- coding: utf-8 -*-
"""Tests for core.edge_density (GDAL window clip + GRASS i.zc).

Tests that run GRASS are skipped when i.zc isn't registered; the others patch
processing.run with a fake i.zc so the window, counting and clean-up logic is
checked without GRASS.
"""

import contextlib
import glob
import os
import shutil
import tempfile
import unittest
from unittest import mock

import utilities

utilities.init_processing()

import numpy as np  # noqa: E402
from osgeo import gdal  # noqa: E402
from qgis.core import QgsProcessingUtils  # noqa: E402

ed = utilities.import_plugin_module("core.edge_density")
rs = utilities.import_plugin_module("core.raster_stats")

ALG_ID = ed.edge_algorithm_id()
GRASS_MISSING = "GRASS i.zc is not registered"

# 10 m pixels, 40 x 40; pixel (row r, col c) covers x 500000 + 10c .., y 5000000 - 10r ..
GT = (500000.0, 10.0, 0.0, 5000000.0, 0.0, -10.0)


def pixel_box(col0, row0, col1, row1, gt=GT):
    """WKT rectangle covering columns col0..col1-1 and rows row0..row1-1 exactly."""
    x0, x1 = gt[0] + col0 * gt[1], gt[0] + col1 * gt[1]
    y0, y1 = gt[3] + row0 * gt[5], gt[3] + row1 * gt[5]
    x0, x1, y0, y1 = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
    return f"POLYGON(({x0} {y0}, {x1} {y0}, {x1} {y1}, {x0} {y1}, {x0} {y0}))"


@contextlib.contextmanager
def recorded_temp_files():
    """Record the mta_* paths edge_density gets from QgsProcessingUtils.generateTempFilename
    (the GRASS provider asks for its own temp files too)."""
    real = QgsProcessingUtils.generateTempFilename
    paths = []

    def record(basename, *args):
        path = real(basename, *args)
        if basename.startswith("mta_"):
            paths.append(path)
        return path

    with mock.patch.object(QgsProcessingUtils, "generateTempFilename", side_effect=record):
        yield paths


def leftover_mta_files():
    return set(glob.glob(os.path.join(QgsProcessingUtils.tempFolder(), "**", "mta_*"),
                         recursive=True))


class EdgeDensityTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.mkdtemp(prefix="mta-edge-test-")
        flat = np.full((40, 40), 100, dtype=np.uint8)
        step = np.zeros((40, 40), dtype=np.uint8)
        step[:, 20:] = 200
        cls.flat = utilities.make_raster(flat, GT, path=os.path.join(cls.tmp_dir, "flat.tif"))
        cls.step = utilities.make_raster(step, GT, path=os.path.join(cls.tmp_dir, "step.tif"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp_dir, ignore_errors=True)

    def assertTempFilesRemoved(self, paths):
        self.assertEqual(len(paths), 2)
        for path in paths:
            self.assertFalse(os.path.exists(path), path)
            self.assertFalse(os.path.exists(os.path.dirname(path)), path)


class EdgeAlgorithmIdTest(EdgeDensityTestCase):

    @unittest.skipUnless(ALG_ID, GRASS_MISSING)
    def test_registered_id(self):
        self.assertIn(ed.edge_algorithm_id(), ("grass7:i.zc", "grass:i.zc"))

    def test_first_registered_id_wins(self):
        with mock.patch.object(ed, "QgsApplication") as app:
            registry = app.processingRegistry.return_value
            registry.algorithmById.side_effect = lambda i: object() if i == "grass7:i.zc" else None
            self.assertEqual(ed.edge_algorithm_id(), "grass7:i.zc")
            registry.algorithmById.side_effect = lambda i: object()
            self.assertEqual(ed.edge_algorithm_id(), "grass:i.zc")

    def test_unavailable(self):
        with mock.patch.object(ed, "QgsApplication") as app, \
                mock.patch("qgis.processing.run") as run:
            app.processingRegistry.return_value.algorithmById.return_value = None
            self.assertIsNone(ed.edge_algorithm_id())
            with self.assertRaises(ed.EdgeDensityUnavailable):
                ed.edge_density(self.step, pixel_box(10, 10, 30, 30))
        run.assert_not_called()


class EdgeDensityFakeGrassTest(EdgeDensityTestCase):
    """processing.run replaced by a fake i.zc that writes a known edge raster."""

    def setUp(self):
        patcher = mock.patch.object(ed, "edge_algorithm_id", return_value="grass7:i.zc")
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_izc(self, edge_rows=(), edge_cols=()):
        """side_effect for processing.run: checks the clip and writes 1 on the
        given window rows/columns, 0 elsewhere, plus GRASS-like sidecar files."""
        def run(alg_id, params, feedback=None):
            self.assertEqual(alg_id, "grass7:i.zc")
            self.assertTrue(params["output"].endswith(".tif"))
            self.assertEqual((params["width"], params["threshold"], params["orientations"]),
                             (3, 5.0, 1))
            clip = gdal.Open(params["input"])
            self.assertEqual(clip.RasterCount, 1)
            self.calls.append((clip.GetGeoTransform(), clip.RasterXSize, clip.RasterYSize))
            edges = np.zeros((clip.RasterYSize, clip.RasterXSize), dtype=np.uint8)
            edges[list(edge_rows), :] = 1
            edges[:, list(edge_cols)] = 1
            out = gdal.GetDriverByName("GTiff").CreateCopy(
                params["output"], clip, options=["TFW=YES"])
            out.GetRasterBand(1).WriteArray(edges)
            out = clip = None
            with open(params["output"] + ".aux.xml", "w") as aux:
                aux.write("<PAMDataset/>")
            return {"output": params["output"]}
        self.calls = []
        return run

    def test_counts_edges_inside_unbuffered_polygon(self):
        # Polygon: 10 x 10 px (100 m side) -> buffer 0.1 * 100 m = 1 px, window 12 x 12.
        # Window row 0 lies in the buffer only; window column 1 is the polygon's first column.
        with recorded_temp_files() as paths, \
                mock.patch("qgis.processing.run", side_effect=self.fake_izc([0], [1])):
            density = ed.edge_density(self.step, pixel_box(10, 10, 20, 20), width=3,
                                      threshold=5.0, buffer_ratio=0.1)
        self.assertAlmostEqual(density, 10 / 100)
        gt, cols, rows = self.calls[0]
        self.assertEqual((cols, rows), (12, 12))
        self.assertEqual(gt, (GT[0] + 90, 10.0, 0.0, GT[3] - 90, 0.0, -10.0))
        self.assertTempFilesRemoved(paths)

    def test_window_clamped_to_raster(self):
        with mock.patch("qgis.processing.run", side_effect=self.fake_izc()):
            self.assertEqual(ed.edge_density(self.step, pixel_box(-5, -5, 5, 5)), 0.0)
        gt, cols, rows = self.calls[0]
        self.assertEqual((gt[0], gt[3], cols, rows), (GT[0], GT[3], 6, 6))

    def test_missing_output_raises_and_cleans_up(self):
        with recorded_temp_files() as paths, mock.patch("qgis.processing.run") as run:
            with self.assertRaises(rs.RasterStatsError):
                ed.edge_density(self.step, pixel_box(10, 10, 20, 20))
        run.assert_called_once()
        self.assertTempFilesRemoved(paths)

    def test_processing_error_cleans_up(self):
        with recorded_temp_files() as paths, \
                mock.patch("qgis.processing.run", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                ed.edge_density(self.step, pixel_box(10, 10, 20, 20))
        self.assertTempFilesRemoved(paths)

    def test_polygon_outside_raster(self):
        with mock.patch("qgis.processing.run") as run:
            self.assertIsNone(ed.edge_density(self.step, pixel_box(50, 50, 60, 60)))
        run.assert_not_called()

    def test_errors(self):
        south_up = utilities.make_raster(np.zeros((10, 10), dtype=np.uint8),
                                         (500000.0, 10.0, 0.0, 4999900.0, 0.0, 10.0))
        self.addCleanup(utilities.remove_raster, south_up)
        with mock.patch("qgis.processing.run") as run:
            for path, wkt in (("/nonexistent/dir/raster.tif", pixel_box(1, 1, 5, 5)),
                              (self.step, "not a polygon"),
                              (south_up, "POLYGON((500010 4999910, 500050 4999910, "
                                         "500050 4999950, 500010 4999910))")):
                with self.assertRaises(rs.RasterStatsError):
                    ed.edge_density(path, wkt)
        run.assert_not_called()


@unittest.skipUnless(ALG_ID, GRASS_MISSING)
class EdgeDensityGrassTest(EdgeDensityTestCase):
    """Real i.zc runs (a second or so each)."""

    def test_flat_raster_has_no_edges(self):
        self.assertEqual(ed.edge_density(self.flat, pixel_box(10, 10, 30, 30)), 0.0)

    def test_step_raster_has_edges_and_leaves_no_temp_files(self):
        before = leftover_mta_files()
        with recorded_temp_files() as paths:
            density = ed.edge_density(self.step, pixel_box(10, 10, 30, 30))
        self.assertGreater(density, 0.0)
        self.assertLessEqual(density, 1.0)
        self.assertTempFilesRemoved(paths)
        self.assertEqual(leftover_mta_files() - before, set())

    def test_ungeoreferenced_scan(self):
        # QGIS shows rasters without a geotransform with y pointing down.
        path = os.path.join(self.tmp_dir, "plain.tif")
        step = np.zeros((40, 40), dtype=np.uint8)
        step[:, 20:] = 200
        ds = gdal.GetDriverByName("GTiff").Create(path, 40, 40, 1, gdal.GDT_Byte)
        ds.GetRasterBand(1).WriteArray(step)
        ds = None
        wkt = "POLYGON((10 -30, 30 -30, 30 -10, 10 -10, 10 -30))"
        self.assertGreater(ed.edge_density(path, wkt), 0.0)
        self.assertEqual(ed.edge_density(path, "POLYGON((1 -39, 9 -39, 9 -31, 1 -31, 1 -39))"),
                         0.0)


if __name__ == "__main__":
    unittest.main()
