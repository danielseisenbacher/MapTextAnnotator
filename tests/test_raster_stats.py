# -*- coding: utf-8 -*-
"""Tests for core.raster_stats (GDAL window + rasterized polygon mask)."""

import unittest
import uuid

import utilities

import numpy as np  # noqa: E402
from osgeo import gdal, ogr  # noqa: E402

rs = utilities.import_plugin_module("core.raster_stats")

# 10 m pixels; pixel (row r, col c) covers x 500000 + 10c .. +10, y 5000000 - 10r .. -10.
GT = (500000.0, 10.0, 0.0, 5000000.0, 0.0, -10.0)


def box_wkt(x0, y0, x1, y1):
    return f"POLYGON(({x0} {y0}, {x1} {y0}, {x1} {y1}, {x0} {y1}, {x0} {y0}))"


def pixel_box(col0, row0, col1, row1, gt=GT):
    """WKT rectangle covering columns col0..col1-1 and rows row0..row1-1 exactly."""
    x0, x1 = gt[0] + col0 * gt[1], gt[0] + col1 * gt[1]
    y0, y1 = gt[3] + row0 * gt[5], gt[3] + row1 * gt[5]
    return box_wkt(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def contrast_of(channels, lower=5.0, upper=95.0):
    """Reference: max percentile range over channels (float64)."""
    return max(float(np.percentile(c, upper) - np.percentile(c, lower)) for c in channels)


class RasterTestCase(unittest.TestCase):
    """Creates /vsimem rasters and unlinks them after each test."""

    def setUp(self):
        self._paths = []

    def tearDown(self):
        for path in self._paths:
            utilities.remove_raster(path)

    def raster(self, array, gt=GT, nodata=None):
        path = utilities.make_raster(array, gt, nodata=nodata)
        self._paths.append(path)
        return path


class ZonalStatsTest(RasterTestCase):

    def setUp(self):
        super().setUp()
        self.array = np.arange(100, dtype=np.float32).reshape(10, 10)
        self.path = self.raster(self.array)

    def test_known_pixels(self):
        stats = rs.zonal_stats(self.path, pixel_box(2, 3, 5, 6))
        expected = self.array[3:6, 2:5].astype(np.float64)
        self.assertEqual(stats["count"], 9)
        self.assertIsInstance(stats["count"], int)
        self.assertAlmostEqual(stats["mean"], float(expected.mean()))
        self.assertAlmostEqual(stats["median"], float(np.median(expected)))
        self.assertEqual(stats["min"], 32.0)
        self.assertEqual(stats["max"], 54.0)
        for key in ("mean", "median", "min", "max"):
            self.assertIsInstance(stats[key], float)

    def test_masked_values_are_float64_pixel_centres(self):
        # Right triangle from the bottom-left corner of pixel (5, 2): only
        # pixels whose centre is inside count.
        x0, y0 = GT[0] + 20, GT[3] - 60
        wkt = f"POLYGON(({x0} {y0}, {x0 + 45} {y0}, {x0} {y0 + 45}, {x0} {y0}))"
        values = rs.masked_values(self.path, wkt)
        self.assertEqual(values.dtype, np.float64)
        self.assertEqual(values.ndim, 1)
        # Centre offsets from the right angle are (10 k + 5); inside if dx + dy < 45.
        expected = [self.array[r, c] for r in range(1, 6) for c in range(2, 7)
                    if (c - 2) * 10 + 5 + (5 - r) * 10 + 5 < 45]
        self.assertEqual(sorted(values.tolist()), sorted(float(v) for v in expected))

    def test_multipolygon(self):
        wkt = ("MULTIPOLYGON(((500000 5000000, 500010 5000000, 500010 4999990, 500000 4999990, "
               "500000 5000000)), ((500090 4999910, 500100 4999910, 500100 4999900, "
               "500090 4999900, 500090 4999910)))")
        self.assertEqual(sorted(rs.masked_values(self.path, wkt).tolist()), [0.0, 99.0])

    def test_nodata_excluded(self):
        array = self.array.copy()
        array[4, 3] = -9999
        path = self.raster(array, nodata=-9999)
        stats = rs.zonal_stats(path, pixel_box(2, 3, 5, 6))
        self.assertEqual(stats["count"], 8)
        self.assertEqual(stats["min"], 32.0)
        self.assertNotIn(-9999.0, rs.masked_values(path, pixel_box(2, 3, 5, 6)))

    def test_all_nodata_returns_none(self):
        path = self.raster(np.full((10, 10), 7, dtype=np.uint8), nodata=7)
        self.assertIsNone(rs.zonal_stats(path, pixel_box(2, 3, 5, 6)))

    def test_nan_excluded_in_float_raster(self):
        array = self.array.copy()
        array[3, 2] = np.nan
        array[5, 4] = np.nan
        stats = rs.zonal_stats(self.raster(array), pixel_box(2, 3, 5, 6))
        self.assertEqual(stats["count"], 7)
        self.assertFalse(np.isnan(stats["mean"]))
        self.assertEqual(stats["min"], 33.0)
        self.assertEqual(stats["max"], 53.0)

    def test_partially_outside_uses_overlap_only(self):
        # Columns 8..12, rows 7..11 -> only columns 8..9 and rows 7..9 exist.
        stats = rs.zonal_stats(self.path, pixel_box(8, 7, 13, 12))
        expected = self.array[7:10, 8:10]
        self.assertEqual(stats["count"], expected.size)
        self.assertAlmostEqual(stats["mean"], float(expected.mean()))
        self.assertEqual(stats["max"], 99.0)

    def test_negative_window_offset(self):
        # Polygon starts left of and above the raster.
        stats = rs.zonal_stats(self.path, pixel_box(-3, -2, 2, 2))
        expected = self.array[0:2, 0:2]
        self.assertEqual(stats["count"], 4)
        self.assertEqual(sorted(rs.masked_values(self.path, pixel_box(-3, -2, 2, 2)).tolist()),
                         sorted(expected.ravel().tolist()))

    def test_fractional_negative_offset(self):
        # Edges half a pixel outside: floor() keeps the window aligned.
        wkt = box_wkt(GT[0] - 5, GT[3] - 24, GT[0] + 24, GT[3] + 5)
        values = rs.masked_values(self.path, wkt)
        self.assertEqual(sorted(values.tolist()), [0.0, 1.0, 10.0, 11.0])

    def test_fully_outside(self):
        for wkt in (pixel_box(12, 0, 15, 3), pixel_box(-5, -5, -1, -1), pixel_box(0, 10, 3, 14),
                    pixel_box(-3, 0, 0, 3)):
            self.assertIsNone(rs.zonal_stats(self.path, wkt), wkt)
            self.assertEqual(rs.masked_values(self.path, wkt).size, 0)

    def test_polygon_smaller_than_pixel_uses_all_touched(self):
        x0, y0 = GT[0] + 60 + 1, GT[3] - 50 + 1  # inside pixel row 4, col 6, off-centre
        wkt = box_wkt(x0, y0, x0 + 2, y0 + 2)
        values = rs.masked_values(self.path, wkt)
        self.assertEqual(values.tolist(), [float(self.array[4, 6])])
        self.assertEqual(rs.zonal_stats(self.path, wkt)["count"], 1)

    def test_south_up_raster(self):
        gt = (500000.0, 10.0, 0.0, 4999900.0, 0.0, 10.0)
        path = self.raster(self.array, gt=gt)
        # Row r covers y 4999900 + 10r .. +10 here.
        wkt = box_wkt(500010, 4999920, 500040, 4999950)
        values = rs.masked_values(path, wkt)
        self.assertEqual(sorted(values.tolist()), sorted(self.array[2:5, 1:4].ravel().tolist()))

    def test_ungeoreferenced_raster_uses_qgis_pixel_coordinates(self):
        path = f"/vsimem/mta_test_{uuid.uuid4().hex}.tif"
        ds = gdal.GetDriverByName("GTiff").Create(path, 10, 10, 1, gdal.GDT_Float32)
        ds.GetRasterBand(1).WriteArray(self.array)
        ds = None
        self._paths.append(path)
        # QGIS shows such rasters with y pointing down: row r spans y -r .. -(r + 1).
        values = rs.masked_values(path, box_wkt(2, -6, 5, -3))
        self.assertEqual(sorted(values.tolist()), sorted(self.array[3:6, 2:5].ravel().tolist()))

    def test_band_index(self):
        path = self.raster(np.stack([self.array, self.array + 1000]))
        self.assertEqual(rs.zonal_stats(path, pixel_box(0, 0, 1, 1), band=2)["max"], 1000.0)
        for band in (0, 3, -1):
            with self.assertRaises(rs.RasterStatsError):
                rs.masked_values(path, pixel_box(0, 0, 1, 1), band=band)

    def test_rotated_geotransform_raises(self):
        path = self.raster(self.array, gt=(500000.0, 10.0, 0.5, 5000000.0, 0.5, -10.0))
        with self.assertRaises(rs.RasterStatsError):
            rs.zonal_stats(path, pixel_box(2, 3, 5, 6))
        with self.assertRaises(rs.RasterStatsError):
            rs.contrast(path, pixel_box(2, 3, 5, 6))

    def test_unopenable_path_raises(self):
        for path in ("/nonexistent/dir/raster.tif", "/vsimem/missing.tif", ""):
            with self.assertRaises(rs.RasterStatsError):
                rs.zonal_stats(path, pixel_box(2, 3, 5, 6))
        with self.assertRaises(rs.RasterStatsError):
            rs.contrast("/nonexistent/dir/raster.tif", pixel_box(2, 3, 5, 6))

    def test_invalid_wkt_raises(self):
        for wkt in ("not a polygon", "POLYGON((1 2, 3", None, "POINT(500020 4999980)",
                    "LINESTRING(500000 5000000, 500050 4999950)"):
            with self.assertRaises(rs.RasterStatsError):
                rs.zonal_stats(self.path, wkt)

    def test_empty_polygon(self):
        self.assertIsNone(rs.zonal_stats(self.path, "POLYGON EMPTY"))

    @unittest.skipUnless(hasattr(gdal, "ExceptionMgr") and hasattr(ogr, "ExceptionMgr"),
                         "needs GDAL >= 3.7")
    def test_gdal_exceptions_enabled_elsewhere(self):
        # Another plugin may have called gdal.UseExceptions() / ogr.UseExceptions().
        with gdal.ExceptionMgr(useExceptions=True), ogr.ExceptionMgr(useExceptions=True):
            self.assertEqual(rs.zonal_stats(self.path, pixel_box(2, 3, 5, 6))["count"], 9)
            with self.assertRaises(rs.RasterStatsError):
                rs.zonal_stats("/nonexistent/dir/raster.tif", pixel_box(2, 3, 5, 6))
            with self.assertRaises(rs.RasterStatsError):
                rs.zonal_stats(self.path, "not a polygon")


class ContrastTest(RasterTestCase):

    def test_uniform_raster_is_zero(self):
        path = self.raster(np.full((10, 10), 100, dtype=np.uint8))
        self.assertEqual(rs.contrast(path, pixel_box(1, 1, 9, 9)), 0.0)

    def test_pixels_outside_polygon_ignored(self):
        array = np.where(np.indices((20, 20)).sum(axis=0) % 2, 255, 0).astype(np.uint8)
        array[5:15, 5:15] = 120
        path = self.raster(array)
        self.assertEqual(rs.contrast(path, pixel_box(5, 5, 15, 15)), 0.0)
        self.assertGreater(rs.contrast(path, pixel_box(3, 3, 17, 17)), 0.5)

    def test_byte_normalisation(self):
        ramp = np.arange(256, dtype=np.uint8).reshape(16, 16)
        path = self.raster(ramp)
        expected = contrast_of([ramp.astype(np.float64).ravel()]) / 255.0
        result = rs.contrast(path, pixel_box(0, 0, 16, 16))
        self.assertAlmostEqual(result, expected)
        self.assertAlmostEqual(result, 0.9, places=6)

    def test_uint16_normalisation(self):
        ramp = np.linspace(0, 65535, 256).astype(np.uint16).reshape(16, 16)
        path = self.raster(ramp)
        expected = contrast_of([ramp.astype(np.float64).ravel()]) / 65535.0
        self.assertAlmostEqual(rs.contrast(path, pixel_box(0, 0, 16, 16)), expected)

    def test_float_unnormalised(self):
        ramp = np.linspace(0, 1000, 256).astype(np.float32).reshape(16, 16)
        path = self.raster(ramp)
        expected = contrast_of([ramp.astype(np.float64).ravel()])
        result = rs.contrast(path, pixel_box(0, 0, 16, 16))
        self.assertGreater(result, 1.0)
        self.assertAlmostEqual(result, expected, places=3)

    def test_custom_percentiles(self):
        ramp = np.arange(256, dtype=np.uint8).reshape(16, 16)
        path = self.raster(ramp)
        self.assertAlmostEqual(rs.contrast(path, pixel_box(0, 0, 16, 16), 0, 100), 1.0)
        expected = contrast_of([ramp.astype(np.float64).ravel()], 25, 75) / 255.0
        self.assertAlmostEqual(rs.contrast(path, pixel_box(0, 0, 16, 16), 25, 75), expected)

    def test_rgb_luminance(self):
        # Each band is 0 except a disjoint 4 % of pixels at 255: every band's
        # 5..95 % range is 0, but the luminance range is not.
        bands = np.zeros((3, 10, 10), dtype=np.uint8)
        flat = bands.reshape(3, 100)
        flat[0, 0:4] = 255
        flat[1, 10:14] = 255
        flat[2, 20:24] = 255
        path = self.raster(bands)
        rgb = flat.astype(np.float64)
        luminance = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
        expected = contrast_of(list(rgb) + [luminance]) / 255.0
        self.assertGreater(expected, 0.0)
        self.assertAlmostEqual(rs.contrast(path, pixel_box(0, 0, 10, 10)), expected)

    def test_invalid_in_one_band_excludes_pixel_everywhere(self):
        bands = np.full((3, 10, 10), 100, dtype=np.uint8)
        bands[0, :, 0:2] = 255  # bright in band 1 ...
        bands[1, :, 0:2] = 0    # ... but nodata in band 2
        path = self.raster(bands, nodata=0)
        self.assertEqual(rs.contrast(path, pixel_box(0, 0, 10, 10)), 0.0)

    def test_alpha_band_masks_pixels_and_is_not_a_channel(self):
        path = f"/vsimem/mta_test_{uuid.uuid4().hex}.tif"
        ds = gdal.GetDriverByName("GTiff").Create(path, 10, 10, 4, gdal.GDT_Byte,
                                                  ["PHOTOMETRIC=RGB", "ALPHA=YES"])
        ds.SetGeoTransform(GT)
        alpha = np.full((10, 10), 255, dtype=np.uint8)
        alpha[:, 0:3] = 0
        rgb = np.full((10, 10), 90, dtype=np.uint8)
        rgb[:, 0:3] = 255  # transparent, must not count
        for i in (1, 2, 3):
            ds.GetRasterBand(i).WriteArray(rgb)
        ds.GetRasterBand(4).WriteArray(alpha)
        ds = None
        self._paths.append(path)
        self.assertEqual(rs.contrast(path, pixel_box(0, 0, 10, 10)), 0.0)

    def test_too_few_pixels(self):
        path = self.raster(np.arange(100, dtype=np.uint8).reshape(10, 10))
        self.assertIsNone(rs.contrast(path, pixel_box(0, 0, 3, 3)))  # 9 < 10
        self.assertIsNotNone(rs.contrast(path, pixel_box(0, 0, 3, 3), min_pixels=9))
        self.assertIsNone(rs.contrast(path, pixel_box(20, 20, 25, 25)))  # outside

    def test_bad_percentiles(self):
        path = self.raster(np.zeros((10, 10), dtype=np.uint8))
        for lower, upper in ((95, 5), (50, 50), (-1, 50), (5, 101)):
            with self.assertRaises(ValueError):
                rs.contrast(path, pixel_box(0, 0, 10, 10), lower, upper)


if __name__ == "__main__":
    unittest.main()
