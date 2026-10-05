# -*- coding: utf-8 -*-
"""Tests for coco/bbox_formats.py (pure Python, pixel coordinates with y down)."""

import unittest

import utilities

bbox_formats = utilities.import_plugin_module("coco.bbox_formats")
settings = utilities.import_plugin_module("settings")

# Corners of the box x 10..50, y 20..40 in scrambled order, plus an inner point.
POINTS = [(50.0, 40.0), (10.0, 20.0), (30.0, 30.0), (10.0, 40.0), (50.0, 20.0)]


def shoelace(flat):
    """Signed area of a flat [x0, y0, x1, y1, ...] ring. With y pointing down a
    positive value means clockwise on screen."""
    pts = list(zip(flat[0::2], flat[1::2]))
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1])) / 2.0


class BBoxFormatsTest(unittest.TestCase):

    def test_formats_match_settings(self):
        self.assertEqual(set(bbox_formats.FORMATS), set(settings.BBOX_FORMATS))

    def test_xyxy(self):
        self.assertEqual(bbox_formats.bbox_from_points(POINTS, "xyxy"), [10.0, 20.0, 50.0, 40.0])

    def test_xywh(self):
        self.assertEqual(bbox_formats.bbox_from_points(POINTS, "xywh"), [10.0, 20.0, 40.0, 20.0])

    def test_polygon(self):
        self.assertEqual(bbox_formats.bbox_from_points(POINTS, "polygon"),
                         [10.0, 20.0, 50.0, 20.0, 50.0, 40.0, 10.0, 40.0])

    def test_polygon_is_clockwise_from_top_left(self):
        poly = bbox_formats.bbox_from_points(POINTS, "polygon")
        self.assertEqual(poly[:2], [10.0, 20.0])  # top-left: smallest x and y
        self.assertGreater(shoelace(poly), 0)
        self.assertAlmostEqual(shoelace(poly), bbox_formats.bbox_area(POINTS))

    def test_y_min_before_y_max_in_every_format(self):
        # e.g. a box converted from geo coordinates, where the bottom corner comes first
        points = [(10.0, 80.0), (50.0, 60.0)]
        xyxy = bbox_formats.bbox_from_points(points, "xyxy")
        self.assertLess(xyxy[1], xyxy[3])
        xywh = bbox_formats.bbox_from_points(points, "xywh")
        self.assertEqual(xywh[1], 60.0)
        self.assertGreater(xywh[3], 0)
        poly = bbox_formats.bbox_from_points(points, "polygon")
        self.assertLess(poly[1], poly[5])
        self.assertEqual(poly[1], poly[3])
        self.assertEqual(poly[5], poly[7])

    def test_returns_floats(self):
        for fmt in bbox_formats.FORMATS:
            with self.subTest(fmt=fmt):
                values = bbox_formats.bbox_from_points([(1, 2), (3, 5)], fmt)
                self.assertTrue(all(type(v) is float for v in values))

    def test_single_point_gives_degenerate_box(self):
        self.assertEqual(bbox_formats.bbox_from_points([(3, 4)], "xywh"), [3.0, 4.0, 0.0, 0.0])
        self.assertEqual(bbox_formats.bbox_area([(3, 4)]), 0.0)

    def test_accepts_iterators(self):
        self.assertEqual(bbox_formats.bbox_from_points(iter(POINTS), "xyxy"), [10.0, 20.0, 50.0, 40.0])
        self.assertEqual(bbox_formats.bbox_area(iter(POINTS)), 800.0)

    def test_unknown_format_raises(self):
        with self.assertRaises(ValueError):
            bbox_formats.bbox_from_points(POINTS, "cxcywh")

    def test_no_points_raises(self):
        for fmt in bbox_formats.FORMATS:
            with self.subTest(fmt=fmt), self.assertRaises(ValueError):
                bbox_formats.bbox_from_points([], fmt)

    def test_area(self):
        self.assertEqual(bbox_formats.bbox_area(POINTS), 800.0)
        self.assertEqual(bbox_formats.bbox_area([(-5.0, -5.0), (5.0, 15.0)]), 200.0)
        self.assertEqual(bbox_formats.bbox_area([]), 0.0)


if __name__ == "__main__":
    unittest.main()
