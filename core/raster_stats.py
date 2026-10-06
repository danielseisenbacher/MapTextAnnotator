# -*- coding: utf-8 -*-
"""
Raster statistics for annotation polygons, using GDAL + numpy only.

All functions take a GDAL-readable raster path and a polygon WKT that is
already in the raster's CRS. They never call gdal.UseExceptions() (it is
process-global and would affect QGIS and other plugins).
"""

import math
from typing import Dict, Optional

import numpy as np
from osgeo import gdal, ogr


class RasterStatsError(Exception):
    """Raster can't be read: unopenable path, missing band, rotated geotransform."""


def _gdal_call(func, *args, **kwargs):
    """(func(*args, **kwargs), error message) with GDAL's error printing
    silenced. The result is None on failure, also when another plugin has
    enabled GDAL/OGR exceptions."""
    gdal.ErrorReset()
    gdal.PushErrorHandler("CPLQuietErrorHandler")
    try:
        return func(*args, **kwargs), gdal.GetLastErrorMsg()
    except RuntimeError as exc:
        return None, str(exc)
    finally:
        gdal.PopErrorHandler()


def _open_raster(path: str):
    """Open path read-only or raise RasterStatsError."""
    ds, msg = _gdal_call(gdal.Open, str(path)) if path else (None, "empty path")
    if ds is None:
        raise RasterStatsError(f"Cannot open raster '{path}': {msg or 'unknown error'}")
    return ds


def _geotransform(ds):
    """North-up (or south-up) geotransform of ds. Rasters without one get
    QGIS's convention (0, 1, 0, 0, 0, -1), so canvas coordinates match."""
    gt = ds.GetGeoTransform(can_return_null=True)
    if gt is None:
        if ds.GetGCPCount() > 0:
            raise RasterStatsError("Rasters georeferenced only by GCPs are not supported")
        return (0.0, 1.0, 0.0, 0.0, 0.0, -1.0)
    if gt[2] != 0 or gt[4] != 0:
        raise RasterStatsError("Rotated or sheared rasters are not supported")
    if gt[1] == 0 or gt[5] == 0:
        raise RasterStatsError("Raster has a zero pixel size")
    return tuple(gt)


def _parse_polygon(polygon_wkt: str):
    """ogr.Geometry of a (Multi)Polygon WKT or raise RasterStatsError."""
    geom = None
    if isinstance(polygon_wkt, str):
        geom, _ = _gdal_call(ogr.CreateGeometryFromWkt, polygon_wkt)
    if geom is None:
        raise RasterStatsError(f"Invalid polygon WKT: {str(polygon_wkt)[:80]}")
    if geom.GetDimension() != 2:
        raise RasterStatsError(f"Not a polygon: {geom.GetGeometryName()}")
    if geom.HasCurveGeometry():
        geom = geom.GetLinearGeometry()
    return geom


def _pixel_window(gt, x_size: int, y_size: int, envelope):
    """(xoff, yoff, width, height) of the pixels covering envelope
    (min_x, max_x, min_y, max_y), clamped to the raster, or None if there is
    no overlap. floor/ceil (not int()) so negative offsets are correct; sorting
    handles south-up (gt[5] > 0) rasters."""
    min_x, max_x, min_y, max_y = envelope
    cols = sorted(((min_x - gt[0]) / gt[1], (max_x - gt[0]) / gt[1]))
    rows = sorted(((max_y - gt[3]) / gt[5], (min_y - gt[3]) / gt[5]))
    col0 = max(math.floor(cols[0]), 0)
    col1 = min(math.ceil(cols[1]), x_size)
    row0 = max(math.floor(rows[0]), 0)
    row1 = min(math.ceil(rows[1]), y_size)
    if col1 <= col0 or row1 <= row0:
        return None
    return col0, row0, col1 - col0, row1 - row0


def _rasterize(geom, gt, window, all_touched: bool = False) -> np.ndarray:
    """Boolean (rows, cols) mask of geom on the pixel window of a raster with
    geotransform gt."""
    xoff, yoff, width, height = window
    window_gt = (gt[0] + xoff * gt[1], gt[1], 0.0, gt[3] + yoff * gt[5], 0.0, gt[5])
    mask_ds = gdal.GetDriverByName("MEM").Create("", width, height, 1, gdal.GDT_Byte)
    mask_ds.SetGeoTransform(window_gt)

    driver = ogr.GetDriverByName("Memory") or ogr.GetDriverByName("MEM")
    vector_ds = driver.CreateDataSource("mta_mask")
    layer = vector_ds.CreateLayer("polygon", srs=None)
    feature = ogr.Feature(layer.GetLayerDefn())
    feature.SetGeometry(geom)
    layer.CreateFeature(feature)

    options = ["ALL_TOUCHED=TRUE"] if all_touched else []
    # Neither side has a CRS: GDAL warns that it assumes matching systems,
    # which is exactly the contract (WKT is in the raster's CRS).
    err, msg = _gdal_call(gdal.RasterizeLayer, mask_ds, [1], layer,
                          burn_values=[1], options=options)
    if err != gdal.CE_None:
        raise RasterStatsError(f"Rasterizing the polygon failed: {msg}")
    return mask_ds.GetRasterBand(1).ReadAsArray().astype(bool)


def _polygon_mask(geom, gt, window) -> np.ndarray:
    """Pixels whose centre is inside geom; all touched pixels if there is none."""
    mask = _rasterize(geom, gt, window)
    if not mask.any():
        mask = _rasterize(geom, gt, window, all_touched=True)
    return mask


def _read_polygon_pixels(path: str, polygon_wkt: str, bands=None):
    """Shared helper: read bands (1-based indices; None = all bands except
    alpha) over the polygon's pixel window.

    Returns (arrays, valid, data_types): float64 (rows, cols) arrays, one per
    band, a boolean mask of pixels inside the polygon and valid (not nodata,
    not masked, not NaN) in every band, and the bands' GDAL data types.
    None if the polygon doesn't overlap the raster."""
    ds = _open_raster(path)
    gt = _geotransform(ds)
    geom = _parse_polygon(polygon_wkt)

    if bands is None:
        bands = [i for i in range(1, ds.RasterCount + 1)
                 if ds.GetRasterBand(i).GetColorInterpretation() != gdal.GCI_AlphaBand]
    for index in bands:
        if not isinstance(index, (int, np.integer)) or not 1 <= index <= ds.RasterCount:
            raise RasterStatsError(f"Band {index} does not exist (raster has {ds.RasterCount})")
    if not bands or geom.IsEmpty():
        return None

    window = _pixel_window(gt, ds.RasterXSize, ds.RasterYSize, geom.GetEnvelope())
    if window is None:
        return None
    valid = _polygon_mask(geom, gt, window)

    arrays, data_types = [], []
    for index in bands:
        band = ds.GetRasterBand(index)
        data, msg = _gdal_call(band.ReadAsArray, *window)
        # The mask band covers nodata values (compared in the band's own type),
        # alpha bands and per-dataset masks.
        band_mask, _ = _gdal_call(band.GetMaskBand().ReadAsArray, *window)
        if data is None or band_mask is None:
            raise RasterStatsError(f"Cannot read band {index} of '{path}': {msg}")
        data = data.astype(np.float64)
        valid &= band_mask > 0
        valid &= ~np.isnan(data)
        arrays.append(data)
        data_types.append(band.DataType)
    return arrays, valid, data_types


def masked_values(path: str, polygon_wkt: str, band: int = 1) -> np.ndarray:
    """1-D float64 array of the band's values whose pixel centres fall inside
    the polygon, nodata excluded. If no pixel centre is inside (polygon smaller
    than a pixel), all touched pixels are used. Empty if the polygon doesn't
    overlap the raster. Raises RasterStatsError."""
    result = _read_polygon_pixels(path, polygon_wkt, [band])
    if result is None:
        return np.empty(0, dtype=np.float64)
    arrays, valid, _ = result
    return arrays[0][valid]


def zonal_stats(path: str, polygon_wkt: str, band: int = 1) -> Optional[Dict[str, float]]:
    """{"mean", "median", "min", "max", "count"} of masked_values, or None if
    no valid pixel lies inside the polygon. Raises RasterStatsError."""
    values = masked_values(path, polygon_wkt, band)
    if values.size == 0:
        return None
    return {
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "count": int(values.size),
    }


# Full value range used to normalise contrast, by GDAL data type.
_NORMALISATION = {gdal.GDT_Byte: 255.0, gdal.GDT_UInt16: 65535.0}


def contrast(path: str, polygon_wkt: str, lower_pct: float = 5.0, upper_pct: float = 95.0,
             min_pixels: int = 10) -> Optional[float]:
    """Robust contrast inside the polygon: the largest (upper_pct - lower_pct)
    percentile range over all bands and, for >= 3 bands, the luminance
    0.299 R + 0.587 G + 0.114 B. Only pixels inside the polygon and valid in
    every band count. Normalised by 255 for Byte and 65535 for UInt16 rasters
    and capped at 1.0; other data types are returned unnormalised.
    None if fewer than min_pixels valid pixels. Raises RasterStatsError."""
    if not 0 <= lower_pct < upper_pct <= 100:
        raise ValueError(f"Need 0 <= lower_pct < upper_pct <= 100, got {lower_pct}, {upper_pct}")

    # Alpha bands are left out: they only flag which pixels are valid.
    result = _read_polygon_pixels(path, polygon_wkt)
    if result is None:
        return None
    arrays, valid, data_types = result
    if int(valid.sum()) < max(int(min_pixels), 1):
        return None

    channels = [data[valid] for data in arrays]
    if len(channels) >= 3:
        channels.append(0.299 * channels[0] + 0.587 * channels[1] + 0.114 * channels[2])
    value = max(float(np.percentile(c, upper_pct) - np.percentile(c, lower_pct))
                for c in channels)

    scale = _NORMALISATION.get(data_types[0])
    if scale is not None and all(t == data_types[0] for t in data_types):
        return min(value / scale, 1.0)
    return value
