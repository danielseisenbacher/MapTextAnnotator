# -*- coding: utf-8 -*-
"""Axis-aligned bounding box formats for the export. No QGIS imports.

Input points are pixel coordinates (x right, y down). Keys match
settings.BBOX_FORMATS.
"""

from typing import List, Sequence, Tuple

FORMATS = ("xyxy", "xywh", "polygon")


def bbox_from_points(points_px: Sequence[Tuple[float, float]], fmt: str) -> List[float]:
    """Axis-aligned box around the points (min / max taken in pixel space):
    xyxy    -> [x_min, y_min, x_max, y_max]
    xywh    -> [x_min, y_min, width, height]                 (COCO)
    polygon -> [x_min, y_min, x_max, y_min, x_max, y_max, x_min, y_max]
               (clockwise on screen, starting top-left)
    Raises ValueError for an unknown format or no points."""
    raise NotImplementedError


def bbox_area(points_px: Sequence[Tuple[float, float]]) -> float:
    """Area (px^2) of the axis-aligned box around the points; 0.0 for no points."""
    raise NotImplementedError
