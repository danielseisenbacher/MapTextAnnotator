# -*- coding: utf-8 -*-
"""Edge complexity: share of zero-crossing edge pixels (GRASS i.zc) inside a polygon."""

import glob
import math
import os
from typing import Optional

from osgeo import gdal
from qgis.core import QgsApplication, QgsProcessingUtils

from .raster_stats import (RasterStatsError, _gdal_call, _geotransform, _open_raster,
                           _parse_polygon, _pixel_window, masked_values)

# QGIS >= 3.36 registers the GRASS provider as "grass", older versions as "grass7".
EDGE_ALGORITHM_IDS = ("grass:i.zc", "grass7:i.zc")


class EdgeDensityUnavailable(Exception):
    """No GRASS i.zc algorithm is registered in the processing framework."""


def edge_algorithm_id() -> Optional[str]:
    """The first registered id from EDGE_ALGORITHM_IDS, or None."""
    registry = QgsApplication.processingRegistry()
    for alg_id in EDGE_ALGORITHM_IDS:
        if registry.algorithmById(alg_id) is not None:
            return alg_id
    return None


def _remove_temp(path: str):
    """Remove path and its sidecars (.aux.xml, .tfw), then its directory if empty
    (generateTempFilename creates one directory per file)."""
    for name in glob.glob(glob.escape(os.path.splitext(path)[0]) + ".*"):
        try:
            os.remove(name)
        except OSError:
            pass
    try:
        os.rmdir(os.path.dirname(path))
    except OSError:
        pass


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
    alg_id = edge_algorithm_id()
    if alg_id is None:
        raise EdgeDensityUnavailable("GRASS i.zc is not available in the processing toolbox")

    ds = _open_raster(path)
    gt = _geotransform(ds)
    if gt[1] < 0 or gt[5] > 0:
        # r.in.gdal refuses flipped rasters ("flipped or rotated - cannot import").
        raise RasterStatsError("Edge complexity needs a north-up raster")
    geom = _parse_polygon(polygon_wkt)
    if geom.IsEmpty():
        return None

    buffered, _ = _gdal_call(geom.Buffer, max(buffer_ratio, 0.0) * math.sqrt(geom.GetArea()), 8)
    if buffered is None or buffered.IsEmpty():
        buffered = geom
    window = _pixel_window(gt, ds.RasterXSize, ds.RasterYSize, buffered.GetEnvelope())
    if window is None:
        return None

    from qgis import processing

    tmp_clip = QgsProcessingUtils.generateTempFilename("mta_clip.tif")
    tmp_edges = QgsProcessingUtils.generateTempFilename("mta_edges.tif")
    try:
        options = {"srcWin": list(window), "bandList": [1], "format": "GTiff"}
        if ds.GetGeoTransform(can_return_null=True) is None:
            # Ungeoreferenced scan: give the clip the pixel coordinates QGIS uses
            # (y pointing down), so the output lines up with polygon_wkt.
            xoff, yoff, cols, rows = window
            options["outputBounds"] = [xoff, -yoff, xoff + cols, -(yoff + rows)]
        clip_ds, msg = _gdal_call(gdal.Translate, tmp_clip, ds, **options)
        if clip_ds is None:
            raise RasterStatsError(f"Cannot cut the raster window: {msg}")
        clip_ds = None

        processing.run(alg_id, {
            "input": tmp_clip,
            "width": int(width),
            "threshold": float(threshold),
            "orientations": 1,
            "output": tmp_edges,
            "GRASS_REGION_PARAMETER": None,
            "GRASS_REGION_CELLSIZE_PARAMETER": 0,
            "GRASS_RASTER_FORMAT_OPT": "",
            "GRASS_RASTER_FORMAT_META": "",
        }, feedback=feedback)
        # GRASS failures don't raise; they just leave no output file.
        if not os.path.exists(tmp_edges):
            raise RasterStatsError("i.zc produced no output")

        # i.zc output (checked on 3.34 / GRASS 8): Byte, no nodata, 1 = edge
        # pixel, 0 = no edge; same grid as the clip. Any other value is ignored.
        values = masked_values(tmp_edges, polygon_wkt)
        edges = int((values == 1).sum())
        total = edges + int((values == 0).sum())
        return edges / total if total else None
    finally:
        _remove_temp(tmp_clip)
        _remove_temp(tmp_edges)
