# -*- coding: utf-8 -*-
"""Axis-aligned bounding box formats for the export. No QGIS imports.

Input points are pixel coordinates (x right, y down). Keys match
settings.BBOX_FORMATS.
"""

from typing import List, Sequence, Tuple

FORMATS = ("xyxy", "xywh", "polygon")


def _extent(points_px: Sequence[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    """(x_min, y_min, x_max, y_max) of the points."""
    xs = [float(p[0]) for p in points_px]
    ys = [float(p[1]) for p in points_px]
    return min(xs), min(ys), max(xs), max(ys)


def bbox_from_points(points_px: Sequence[Tuple[float, float]], fmt: str) -> List[float]:
    """Axis-aligned box around the points (min / max taken in pixel space):
    xyxy    -> [x_min, y_min, x_max, y_max]
    xywh    -> [x_min, y_min, width, height]                 (COCO)
    polygon -> [x_min, y_min, x_max, y_min, x_max, y_max, x_min, y_max]
               (clockwise on screen, starting top-left)
    Raises ValueError for an unknown format or no points."""
    if fmt not in FORMATS:
        raise ValueError(f"Unknown bbox format {fmt!r}, expected one of {FORMATS}")
    points_px = list(points_px)
    if not points_px:
        raise ValueError("Cannot build a bounding box without points")

    x_min, y_min, x_max, y_max = _extent(points_px)
    if fmt == "xyxy":
        return [x_min, y_min, x_max, y_max]
    if fmt == "xywh":
        return [x_min, y_min, x_max - x_min, y_max - y_min]
    # top-left, top-right, bottom-right, bottom-left (y down: clockwise on screen)
    return [x_min, y_min, x_max, y_min, x_max, y_max, x_min, y_max]


def bbox_area(points_px: Sequence[Tuple[float, float]]) -> float:
    """Area (px^2) of the axis-aligned box around the points; 0.0 for no points."""
    points_px = list(points_px)
    if not points_px:
        return 0.0
    x_min, y_min, x_max, y_max = _extent(points_px)
    return (x_max - x_min) * (y_max - y_min)
