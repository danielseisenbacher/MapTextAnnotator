# -*- coding: utf-8 -*-
"""
Pure geometry helpers for annotation polygons. No QGIS imports.

Points are (x, y) tuples in a y-up coordinate system (map / raster CRS).
Annotators draw the word polygon counter-clockwise starting at the
bottom-left corner, with the same number of vertices on the bottom and the
top edge.
"""

from typing import List, Sequence, Tuple

import numpy as np

Point = Tuple[float, float]
Bezier = Tuple[Point, Point, Point, Point]


class InvalidAnnotationGeometry(ValueError):
    """The polygon can't be turned into lower/upper bezier curves."""


def _as_points(points: Sequence[Point]) -> List[Point]:
    return [(float(p[0]), float(p[1])) for p in points]


def ring_vertices(points: Sequence[Point]) -> List[Point]:
    """Return the ring's vertices without the closing duplicate (if present)."""
    pts = _as_points(points)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    return pts


def signed_area(points: Sequence[Point]) -> float:
    """Shoelace signed area of the ring; > 0 for counter-clockwise rings (y up)."""
    pts = ring_vertices(points)
    area = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        area += x1 * y2 - x2 * y1
    return area / 2.0


def ensure_ccw(points: Sequence[Point]) -> List[Point]:
    """Return the ring (without closing vertex) in counter-clockwise order.
    A clockwise ring keeps its first vertex and has the rest reversed, so the
    drawing still starts at the same (bottom-left) corner."""
    pts = ring_vertices(points)
    if signed_area(pts) < 0:
        pts = pts[:1] + pts[:0:-1]
    return pts


def split_lower_upper(points: Sequence[Point]) -> Tuple[List[Point], List[Point]]:
    """Split a counter-clockwise ring (no closing vertex) drawn from the
    bottom-left corner into (lower, upper):
    lower = first half, bottom-left -> bottom-right;
    upper = second half, top-right -> top-left.
    Raises InvalidAnnotationGeometry for fewer than 4 vertices or an odd count."""
    pts = ring_vertices(points)
    n = len(pts)
    if n < 4:
        raise InvalidAnnotationGeometry(f"the polygon has {n} vertices, at least 4 are needed")
    if n % 2:
        raise InvalidAnnotationGeometry(
            f"the polygon has {n} vertices, the top and bottom edge need the same number of vertices"
        )
    half = n // 2
    return pts[:half], pts[half:]


def _least_squares_bezier(pts: List[Point]) -> Bezier:
    """Chord-length parameterised least-squares cubic with fixed end points."""
    xy = np.asarray(pts, dtype=float)
    lengths = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    cumulative = np.concatenate([[0.0], np.cumsum(lengths)])
    t = cumulative / cumulative[-1]

    p0, p3 = xy[0], xy[-1]
    # Bernstein weights of the free control points P1, P2
    a = np.column_stack([3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2])
    b = xy - np.outer((1 - t) ** 3, p0) - np.outer(t ** 3, p3)
    (p1, p2), *_ = np.linalg.lstsq(a, b, rcond=None)

    return tuple((float(p[0]), float(p[1])) for p in (p0, p1, p2, p3))


def fit_cubic_bezier(points: Sequence[Point]) -> Bezier:
    """Cubic bezier control points (P0, P1, P2, P3) approximating an open polyline.
    2 points: the line split into thirds. 3 points: the midpoint of the longer
    segment is inserted, then fitted. >= 4 points: chord-length parameterised
    least squares with P0 / P3 fixed to the end points.
    Raises InvalidAnnotationGeometry for fewer than 2 points or zero length."""
    pts = _as_points(points)
    if len(pts) < 2:
        raise InvalidAnnotationGeometry(f"an edge needs at least 2 vertices, got {len(pts)}")
    xy = np.asarray(pts, dtype=float)
    if not np.all(np.isfinite(xy)):
        raise InvalidAnnotationGeometry("an edge has non-finite coordinates")
    if float(np.sum(np.linalg.norm(np.diff(xy, axis=0), axis=1))) == 0.0:
        raise InvalidAnnotationGeometry("an edge has zero length")

    if len(pts) == 2:
        (x0, y0), (x3, y3) = pts
        dx, dy = x3 - x0, y3 - y0
        return ((x0, y0), (x0 + dx / 3, y0 + dy / 3), (x0 + 2 * dx / 3, y0 + 2 * dy / 3), (x3, y3))

    if len(pts) == 3:
        a, b, c = pts
        d1 = (b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2
        d2 = (c[0] - b[0]) ** 2 + (c[1] - b[1]) ** 2
        if d1 >= d2:
            pts = [a, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), b, c]
        else:
            pts = [a, b, ((b[0] + c[0]) / 2, (b[1] + c[1]) / 2), c]

    return _least_squares_bezier(pts)


def beziers_from_ring(points: Sequence[Point]) -> Tuple[Bezier, Bezier]:
    """(lower, upper) control points in storage order (see schema.py) for a
    polygon ring (closing vertex optional, either orientation)."""
    lower, upper = split_lower_upper(ensure_ccw(points))
    return fit_cubic_bezier(lower), fit_cubic_bezier(upper)
