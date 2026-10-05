# -*- coding: utf-8 -*-
"""
Raster statistics for annotation polygons, using GDAL + numpy only.

All functions take a GDAL-readable raster path and a polygon WKT that is
already in the raster's CRS. They never call gdal.UseExceptions() (it is
process-global and would affect QGIS and other plugins).
"""

from typing import Dict, Optional

import numpy as np


class RasterStatsError(Exception):
    """Raster can't be read: unopenable path, missing band, rotated geotransform."""


def masked_values(path: str, polygon_wkt: str, band: int = 1) -> np.ndarray:
    """1-D float64 array of the band's values whose pixel centres fall inside
    the polygon, nodata excluded. If no pixel centre is inside (polygon smaller
    than a pixel), all touched pixels are used. Empty if the polygon doesn't
    overlap the raster. Raises RasterStatsError."""
    raise NotImplementedError


def zonal_stats(path: str, polygon_wkt: str, band: int = 1) -> Optional[Dict[str, float]]:
    """{"mean", "median", "min", "max", "count"} of masked_values, or None if
    no valid pixel lies inside the polygon. Raises RasterStatsError."""
    raise NotImplementedError


def contrast(path: str, polygon_wkt: str, lower_pct: float = 5.0, upper_pct: float = 95.0,
             min_pixels: int = 10) -> Optional[float]:
    """Robust contrast inside the polygon: the largest (upper_pct - lower_pct)
    percentile range over all bands and, for >= 3 bands, the luminance
    0.299 R + 0.587 G + 0.114 B. Only pixels inside the polygon and valid in
    every band count. Normalised by 255 for Byte and 65535 for UInt16 rasters
    and capped at 1.0; other data types are returned unnormalised.
    None if fewer than min_pixels valid pixels. Raises RasterStatsError."""
    raise NotImplementedError
