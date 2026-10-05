# -*- coding: utf-8 -*-
"""Tests for core/geometry.py (pure python, no QGIS application needed)."""

import unittest

import utilities

geometry = utilities.import_plugin_module("core.geometry")

# A 10 x 2 word box drawn counter-clockwise from the bottom-left corner
RECT_CCW = [(0.0, 0.0), (10.0, 0.0), (10.0, 2.0), (0.0, 2.0)]
# The same box drawn clockwise from the bottom-left corner
RECT_CW = [(0.0, 0.0), (0.0, 2.0), (10.0, 2.0), (10.0, 0.0)]


def closed(points):
    return list(points) + [points[0]]


class AssertPointsMixin:
    def assertPointAlmostEqual(self, a, b, places=7):
        self.assertAlmostEqual(a[0], b[0], places=places, msg=f"{a} != {b}")
        self.assertAlmostEqual(a[1], b[1], places=places, msg=f"{a} != {b}")

    def assertPointsAlmostEqual(self, a, b, places=7):
        self.assertEqual(len(a), len(b))
        for p, q in zip(a, b):
            self.assertPointAlmostEqual(p, q, places)


class RingTests(AssertPointsMixin, unittest.TestCase):
    def test_ring_vertices_drops_closing_vertex(self):
        self.assertEqual(geometry.ring_vertices(closed(RECT_CCW)), RECT_CCW)

    def test_ring_vertices_without_closing_vertex_is_unchanged(self):
        self.assertEqual(geometry.ring_vertices(RECT_CCW), RECT_CCW)

    def test_ring_vertices_returns_float_tuples(self):
        result = geometry.ring_vertices([[0, 0], [1, 0], [1, 1]])
        self.assertEqual(result, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)])
        self.assertIsInstance(result[0][0], float)

    def test_signed_area_sign(self):
        self.assertAlmostEqual(geometry.signed_area(RECT_CCW), 20.0)
        self.assertAlmostEqual(geometry.signed_area(RECT_CW), -20.0)
        self.assertAlmostEqual(geometry.signed_area(closed(RECT_CCW)), 20.0)

    def test_ensure_ccw_keeps_ccw_ring(self):
        self.assertEqual(geometry.ensure_ccw(RECT_CCW), RECT_CCW)
        self.assertEqual(geometry.ensure_ccw(closed(RECT_CCW)), RECT_CCW)

    def test_ensure_ccw_reverses_cw_ring_keeping_start(self):
        self.assertEqual(geometry.ensure_ccw(RECT_CW), RECT_CCW)
        self.assertEqual(geometry.ensure_ccw(closed(RECT_CW)), RECT_CCW)


class SplitTests(unittest.TestCase):
    def test_split_4(self):
        lower, upper = geometry.split_lower_upper(RECT_CCW)
        self.assertEqual(lower, [(0, 0), (10, 0)])
        self.assertEqual(upper, [(10, 2), (0, 2)])

    def test_split_6_and_8(self):
        for n in (6, 8):
            half = n // 2
            bottom = [(float(i), 0.0) for i in range(half)]
            top = [(float(i), 1.0) for i in reversed(range(half))]
            lower, upper = geometry.split_lower_upper(bottom + top)
            self.assertEqual(lower, bottom)
            self.assertEqual(upper, top)

    def test_split_accepts_closing_vertex(self):
        lower, upper = geometry.split_lower_upper(closed(RECT_CCW))
        self.assertEqual(len(lower), 2)
        self.assertEqual(len(upper), 2)

    def test_odd_vertex_count_raises(self):
        five = [(0, 0), (5, 0), (10, 0), (10, 2), (0, 2)]
        with self.assertRaises(geometry.InvalidAnnotationGeometry):
            geometry.split_lower_upper(five)
        with self.assertRaises(geometry.InvalidAnnotationGeometry):
            geometry.beziers_from_ring(closed(five))

    def test_fewer_than_4_vertices_raises(self):
        triangle = [(0, 0), (10, 0), (5, 2)]
        with self.assertRaises(geometry.InvalidAnnotationGeometry):
            geometry.split_lower_upper(triangle)
        with self.assertRaises(geometry.InvalidAnnotationGeometry):
            geometry.split_lower_upper([(0, 0), (10, 0)])
        with self.assertRaises(geometry.InvalidAnnotationGeometry):
            geometry.beziers_from_ring(closed(triangle))

    def test_invalid_geometry_is_a_value_error(self):
        self.assertTrue(issubclass(geometry.InvalidAnnotationGeometry, ValueError))


class FitTests(AssertPointsMixin, unittest.TestCase):
    def test_two_points_split_into_thirds(self):
        bezier = geometry.fit_cubic_bezier([(0, 0), (9, 3)])
        self.assertPointsAlmostEqual(bezier, [(0, 0), (3, 1), (6, 2), (9, 3)])

    def test_three_points_reproduce_old_midpoint_rule(self):
        # first segment longer: midpoint inserted between point 0 and 1,
        # then least squares on [p0, mid, p1, p2] (old get_bezier_points + interpolate_bezier)
        pts = [(0.0, 0.0), (6.0, 2.0), (8.0, 0.0)]
        expected = geometry.fit_cubic_bezier([(0.0, 0.0), (3.0, 1.0), (6.0, 2.0), (8.0, 0.0)])
        self.assertPointsAlmostEqual(geometry.fit_cubic_bezier(pts), expected)
        # second segment longer: midpoint inserted between point 1 and 2
        pts = [(0.0, 0.0), (2.0, 2.0), (8.0, 0.0)]
        expected = geometry.fit_cubic_bezier([(0.0, 0.0), (2.0, 2.0), (5.0, 1.0), (8.0, 0.0)])
        self.assertPointsAlmostEqual(geometry.fit_cubic_bezier(pts), expected)

    def test_end_points_are_fixed(self):
        pts = [(0, 0), (2, 1.5), (5, 2), (7, 1), (9, -0.5)]
        bezier = geometry.fit_cubic_bezier(pts)
        self.assertPointAlmostEqual(bezier[0], pts[0])
        self.assertPointAlmostEqual(bezier[3], pts[-1])

    def test_straight_line_is_reproduced(self):
        # unevenly spaced points on a line: control points at thirds, all on the line
        pts = [(0, 0), (1, 0.5), (5, 2.5), (6, 3), (10, 5)]
        bezier = geometry.fit_cubic_bezier(pts)
        self.assertPointsAlmostEqual(bezier, [(0, 0), (10 / 3, 5 / 3), (20 / 3, 10 / 3), (10, 5)])

    def test_curve_through_cubic_samples_is_recovered(self):
        # samples of a known cubic at chord-length-like parameters of a symmetric arc
        ctrl = [(0.0, 0.0), (2.0, 4.0), (8.0, 4.0), (10.0, 0.0)]

        def point(t):
            b = [(1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3]
            return (sum(w * c[0] for w, c in zip(b, ctrl)), sum(w * c[1] for w, c in zip(b, ctrl)))

        pts = [point(t / 10) for t in range(11)]
        bezier = geometry.fit_cubic_bezier(pts)
        # chord-length parameterisation is not exact, but close for a smooth arc
        for got, want in zip(bezier, ctrl):
            self.assertAlmostEqual(got[0], want[0], delta=0.5)
            self.assertAlmostEqual(got[1], want[1], delta=0.5)

    def test_returns_tuples_of_floats(self):
        bezier = geometry.fit_cubic_bezier([(0, 0), (1, 1), (2, 1), (3, 0)])
        self.assertIsInstance(bezier, tuple)
        self.assertEqual(len(bezier), 4)
        for p in bezier:
            self.assertIsInstance(p, tuple)
            self.assertIsInstance(p[0], float)
            self.assertIsInstance(p[1], float)

    def test_fewer_than_2_points_raises(self):
        with self.assertRaises(geometry.InvalidAnnotationGeometry):
            geometry.fit_cubic_bezier([(0, 0)])
        with self.assertRaises(geometry.InvalidAnnotationGeometry):
            geometry.fit_cubic_bezier([])

    def test_zero_length_raises(self):
        for pts in ([(1, 1), (1, 1)], [(1, 1)] * 3, [(1, 1)] * 4):
            with self.assertRaises(geometry.InvalidAnnotationGeometry):
                geometry.fit_cubic_bezier(pts)

    def test_zero_length_edge_in_ring_raises(self):
        # bottom edge collapsed to a point
        ring = [(0, 0), (0, 0), (10, 2), (0, 2)]
        with self.assertRaises(geometry.InvalidAnnotationGeometry):
            geometry.beziers_from_ring(ring)


def old_interpolate_bezier(points):
    """MaptextAnnotator.interpolate_bezier from v0.1, with tuples instead of QgsPointXY."""
    import numpy as np
    pts = np.array(points, dtype=float)
    n = len(pts)
    dists = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cumdist = np.concatenate([[0.0], np.cumsum(dists)])
    t = cumdist / cumdist[-1]
    P0, P3 = pts[0], pts[-1]
    A = np.zeros((n, 2))
    b = np.zeros((n, 2))
    for i in range(n):
        ti = t[i]
        A[i] = [3 * (1 - ti) ** 2 * ti, 3 * (1 - ti) * ti ** 2]
        b[i] = pts[i] - ((1 - ti) ** 3) * P0 - (ti ** 3) * P3
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    return [tuple(P0), tuple(sol[0]), tuple(sol[1]), tuple(P3)]


class OldBehaviourTests(AssertPointsMixin, unittest.TestCase):
    def test_matches_v01_least_squares(self):
        for pts in (
            [(0, 0), (2, 1.5), (5, 2), (7, 1)],
            [(0, 0), (2, 1.5), (5, 2), (7, 1), (9, -0.5)],
            [(3, 1), (4, 3), (7, 4), (9, 4), (12, 2), (13, 0)],
        ):
            self.assertPointsAlmostEqual(geometry.fit_cubic_bezier(pts), old_interpolate_bezier(pts))

    def test_matches_v01_two_and_three_points(self):
        # v0.1: get_bezier_points (thirds / midpoint) followed by interpolate_bezier
        self.assertPointsAlmostEqual(
            geometry.fit_cubic_bezier([(1, 1), (7, 4)]),
            old_interpolate_bezier([(1, 1), (3, 2), (5, 3), (7, 4)]),
        )
        self.assertPointsAlmostEqual(
            geometry.fit_cubic_bezier([(0, 0), (6, 2), (8, 0)]),
            old_interpolate_bezier([(0, 0), (3, 1), (6, 2), (8, 0)]),
        )


class BeziersFromRingTests(AssertPointsMixin, unittest.TestCase):
    def test_rectangle_storage_order(self):
        lower, upper = geometry.beziers_from_ring(closed(RECT_CCW))
        # lower: bottom-left -> bottom-right
        self.assertPointsAlmostEqual(lower, [(0, 0), (10 / 3, 0), (20 / 3, 0), (10, 0)])
        # upper: top-right -> top-left
        self.assertPointsAlmostEqual(upper, [(10, 2), (20 / 3, 2), (10 / 3, 2), (0, 2)])

    def test_clockwise_gives_same_result(self):
        for ccw in (
            RECT_CCW,
            [(0, 0), (5, -1), (10, 0), (10, 2), (5, 1), (0, 2)],
            [(0, 0), (3, -1), (7, -1), (10, 0), (10, 2), (7, 1), (3, 1), (0, 2)],
        ):
            cw = [ccw[0]] + ccw[:0:-1]
            self.assertLess(geometry.signed_area(cw), 0)
            expected = geometry.beziers_from_ring(ccw)
            for ring in (cw, closed(cw), closed(ccw)):
                lower, upper = geometry.beziers_from_ring(ring)
                self.assertPointsAlmostEqual(lower, expected[0])
                self.assertPointsAlmostEqual(upper, expected[1])

    def test_6_and_8_vertices(self):
        six = [(0, 0), (5, -1), (10, 0), (10, 2), (5, 1), (0, 2)]
        lower, upper = geometry.beziers_from_ring(closed(six))
        self.assertPointAlmostEqual(lower[0], (0, 0))
        self.assertPointAlmostEqual(lower[3], (10, 0))
        self.assertPointAlmostEqual(upper[0], (10, 2))
        self.assertPointAlmostEqual(upper[3], (0, 2))
        # the bottom edge sags: control points below the chord
        self.assertLess(lower[1][1], 0)
        self.assertLess(lower[2][1], 0)

        eight = [(0, 0), (3, 0), (7, 0), (10, 0), (10, 2), (7, 2), (3, 2), (0, 2)]
        lower, upper = geometry.beziers_from_ring(eight)
        self.assertPointsAlmostEqual(lower, [(0, 0), (10 / 3, 0), (20 / 3, 0), (10, 0)])
        self.assertPointsAlmostEqual(upper, [(10, 2), (20 / 3, 2), (10 / 3, 2), (0, 2)])


if __name__ == "__main__":
    unittest.main()
