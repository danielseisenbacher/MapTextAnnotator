# -*- coding: utf-8 -*-
"""Edge complexity: share of zero-crossing edge pixels (GRASS i.zc) inside a polygon."""

from typing import Optional

# QGIS >= 3.36 registers the GRASS provider as "grass", older versions as "grass7".
EDGE_ALGORITHM_IDS = ("grass:i.zc", "grass7:i.zc")


class EdgeDensityUnavailable(Exception):
    """No GRASS i.zc algorithm is registered in the processing framework."""


def edge_algorithm_id() -> Optional[str]:
    """The first registered id from EDGE_ALGORITHM_IDS, or None."""
    raise NotImplementedError


def edge_density(path: str, polygon_wkt: str, width: int = 3, threshold: float = 5.0,
                 buffer_ratio: float = 0.1, feedback=None) -> Optional[float]:
    """Share (0..1) of i.zc edge pixels inside the polygon, computed on band 1.

    The raster is cut to a window around the polygon buffered by
    buffer_ratio * sqrt(area) so edges at the polygon border are detected,
    i.zc runs on that window with an explicit .tif output, and edge pixels
    are counted inside the unbuffered polygon. Temporary files are removed.
    polygon_wkt must be in the raster's CRS.
    Raises EdgeDensityUnavailable if i.zc is missing, RasterStatsError for
    unreadable rasters. None if no pixel falls inside the polygon."""
    raise NotImplementedError
