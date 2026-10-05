# -*- coding: utf-8 -*-
"""
Pure geometry helpers for annotation polygons. No QGIS imports.

Points are (x, y) tuples in a y-up coordinate system (map / raster CRS).
Annotators draw the word polygon counter-clockwise starting at the
bottom-left corner, with the same number of vertices on the bottom and the
top edge.
"""

from typing import List, Sequence, Tuple

Point = Tuple[float, float]
Bezier = Tuple[Point, Point, Point, Point]


class InvalidAnnotationGeometry(ValueError):
    """The polygon can't be turned into lower/upper bezier curves."""


def ring_vertices(points: Sequence[Point]) -> List[Point]:
    """Return the ring's vertices without the closing duplicate (if present)."""
    raise NotImplementedError


def signed_area(points: Sequence[Point]) -> float:
    """Shoelace signed area of the ring; > 0 for counter-clockwise rings (y up)."""
    raise NotImplementedError


def ensure_ccw(points: Sequence[Point]) -> List[Point]:
    """Return the ring (without closing vertex) in counter-clockwise order.
    A clockwise ring keeps its first vertex and has the rest reversed, so the
    drawing still starts at the same (bottom-left) corner."""
    raise NotImplementedError


def split_lower_upper(points: Sequence[Point]) -> Tuple[List[Point], List[Point]]:
    """Split a counter-clockwise ring (no closing vertex) drawn from the
    bottom-left corner into (lower, upper):
    lower = first half, bottom-left -> bottom-right;
    upper = second half, top-right -> top-left.
    Raises InvalidAnnotationGeometry for fewer than 4 vertices or an odd count."""
    raise NotImplementedError


def fit_cubic_bezier(points: Sequence[Point]) -> Bezier:
    """Cubic bezier control points (P0, P1, P2, P3) approximating an open polyline.
    2 points: the line split into thirds. 3 points: the midpoint of the longer
    segment is inserted, then fitted. >= 4 points: chord-length parameterised
    least squares with P0 / P3 fixed to the end points.
    Raises InvalidAnnotationGeometry for fewer than 2 points or zero length."""
    raise NotImplementedError


def beziers_from_ring(points: Sequence[Point]) -> Tuple[Bezier, Bezier]:
    """(lower, upper) control points in storage order (see schema.py) for a
    polygon ring (closing vertex optional, either orientation)."""
    raise NotImplementedError
