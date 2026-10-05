# -*- coding: utf-8 -*-
"""
Export of an annotation layer to a COCO-style JSON (ABCNet / DeepSolo flavour).

Coordinates are read from the stored WKT (reference raster CRS, see schema.py)
and converted to pixel coordinates (x right, y down) of the reference image via
its inverse geotransform. Only records_from_layer touches QGIS objects; the
rest works on plain dicts.
"""

import configparser
import contextlib
import copy
import json
import math
import os
import unicodedata
import uuid
from datetime import datetime
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

from osgeo import gdal, ogr
from qgis.PyQt.QtCore import QVariant

from .. import schema, settings
from . import bbox_formats
from .coco_template import (
    MAX_TEXT_LENGTH,
    PAD_TOKEN,
    UNKNOWN_TOKEN,
    annotations_template,
    character_map,
    coco_template,
    images_template,
)

# (fid, reason) of a feature left out of the export
Skipped = Tuple[int, str]
Point = Tuple[float, float]

_METADATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "metadata.txt")

# Geotransform QGIS assumes for rasters without georeferencing (pixel size 1, -1).
_UNGEOREFERENCED_GT = (0.0, 1.0, 0.0, 0.0, 0.0, -1.0)

# Human-readable description of bezier_pts per settings.BEZIER_ORDERS key.
BEZIER_PTS_ORDER = {
    "abcnet": "16 floats, pixel coordinates (y down): 4 control points of the top curve from left to right, "
              "then 4 control points of the bottom curve from right to left",
    "legacy": "16 floats, pixel coordinates (y down): 4 control points of the top curve from right to left, "
              "then 4 control points of the bottom curve from right to left",
}


class _SkipFeature(Exception):
    """A record that can't be exported; the message is the reason."""


def records_from_layer(layer) -> List[Dict]:
    """One plain dict per feature: {"fid": feature id, <field name>: value},
    NULL values converted to None. Decouples the export from QGIS objects."""
    names = layer.fields().names()
    records = []
    for feature in layer.getFeatures():
        record = {"fid": feature.id()}
        for name, value in zip(names, feature.attributes()):
            record[name] = None if _is_null(value) else value
        records.append(record)
    return records


def build_annotations(records: List[Dict], bbox_format: str = "xyxy", bezier_order: str = "abcnet",
                      enabled_stats: FrozenSet[str] = frozenset(schema.STAT_FIELDS)) -> Tuple[Dict, List[Skipped]]:
    """Build a fresh COCO dict from records (see records_from_layer).

    bbox_format: a key of settings.BBOX_FORMATS. bezier_order: a key of
    settings.BEZIER_ORDERS. Statistic groups not in enabled_stats are omitted.
    Features that can't be exported (no / unreadable reference image, missing
    or invalid beziers, empty transcription) are skipped and returned with a
    reason instead of raising."""
    if bbox_format not in bbox_formats.FORMATS:
        raise ValueError(f"Unknown bbox format {bbox_format!r}, expected one of {sorted(bbox_formats.FORMATS)}")
    if bezier_order not in settings.BEZIER_ORDERS:
        raise ValueError(f"Unknown bezier order {bezier_order!r}, expected one of {sorted(settings.BEZIER_ORDERS)}")
    enabled_stats = frozenset(enabled_stats)
    unknown = enabled_stats - set(schema.STAT_EXPORT_KEYS)
    if unknown:
        raise ValueError(f"Unknown statistic groups {sorted(unknown)}, "
                         f"expected some of {sorted(schema.STAT_EXPORT_KEYS)}")

    coco = copy.deepcopy(coco_template)
    coco["info"] = {
        "description": "MapText Annotator export",
        "version": _plugin_version(),
        "date_created": datetime.now().astimezone().isoformat(timespec="seconds"),
        "bbox_format": bbox_format,
        "bezier_order": bezier_order,
        "bezier_pts_order": BEZIER_PTS_ORDER[bezier_order],
    }

    rasters = {}    # image path -> ((inverse geotransform, width, height) | None, error)
    image_ids = {}  # image path -> image id, in order of first exported appearance
    skipped = []

    for record in records:
        try:
            image_path = _reference_image(record)
            inv_gt, width, height = _raster_info(image_path, rasters)
            annotation = _annotation(record, inv_gt, bbox_format, bezier_order, enabled_stats)
        except _SkipFeature as e:
            skipped.append((record.get("fid"), str(e)))
            continue

        if image_path not in image_ids:
            image_ids[image_path] = len(image_ids)
            image = copy.deepcopy(images_template)
            image.update(file_name=os.path.basename(image_path), id=image_ids[image_path],
                         width=width, height=height)
            coco["images"].append(image)

        annotation["id"] = len(coco["annotations"])
        annotation["image_id"] = image_ids[image_path]
        coco["annotations"].append(annotation)

    return coco, skipped


def write_annotations(coco_dict: Dict, path: str) -> None:
    """Write JSON atomically (temp file in the same directory + os.replace)."""
    path = os.path.abspath(path)
    tmp_path = os.path.join(os.path.dirname(path), f".{os.path.basename(path)}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp_path, "x", encoding="utf-8") as f:
            json.dump(coco_dict, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp_path)
        raise


# --- records -> annotation --------------------------------------------------

def _annotation(record: Dict, inv_gt: Sequence[float], bbox_format: str, bezier_order: str,
                enabled_stats: FrozenSet[str]) -> Dict:
    """Annotation entry without id / image_id. Raises _SkipFeature."""
    upper = _bezier_pixels(record, "Upper Bezier", inv_gt)  # stored top-right -> top-left
    lower = _bezier_pixels(record, "Lower Bezier", inv_gt)  # stored bottom-left -> bottom-right

    word = record.get("Word Transcription")
    if word is None or not str(word).strip():
        raise _SkipFeature("empty word transcription")

    if bezier_order == "abcnet":
        top = upper[::-1]
    else:  # legacy: top curve as stored
        top = upper
    bottom = lower[::-1]

    # Axis-aligned box: all 4 corners of the stored box, so it also holds for
    # rotated rasters. Without a stored box fall back to the control points.
    bbox_geo = _parse_points(record.get("Bounding Box"))
    if bbox_geo:
        xs = [p[0] for p in bbox_geo]
        ys = [p[1] for p in bbox_geo]
        corners = [(min(xs), min(ys)), (max(xs), min(ys)), (max(xs), max(ys)), (min(xs), max(ys))]
        box_px = _to_pixels(corners, inv_gt)
    else:
        box_px = upper + lower

    annotation = copy.deepcopy(annotations_template)
    annotation.update(
        area=bbox_formats.bbox_area(box_px),
        bbox=bbox_formats.bbox_from_points(box_px, bbox_format),
        bezier_pts=_flatten(top + bottom),
        rec=_encode_word(str(word)),
        bounding_points=_flatten(_to_pixels(_parse_points(record.get("Bounding Points")) or [], inv_gt)),
        obbox=_flatten(_to_pixels(_parse_points(record.get("Oriented Bounding Box")) or [], inv_gt)),
        certainty=_json_value(record.get("Certainty")),
    )
    for group, keys in schema.STAT_EXPORT_KEYS.items():
        if group in enabled_stats:
            for field, key in keys.items():
                annotation[key] = _json_value(record.get(field))
    return annotation


def _reference_image(record: Dict) -> str:
    path = record.get("Reference Image")
    if path is None or str(path).strip() in ("", schema.NO_REFERENCE_IMAGE):
        raise _SkipFeature("no reference image")
    return str(path)


def _bezier_pixels(record: Dict, field: str, inv_gt: Sequence[float]) -> List[Point]:
    """The 4 control points of a stored bezier in pixel coordinates. Raises _SkipFeature."""
    points = _parse_points(record.get(field))
    if points is None:
        raise _SkipFeature(f'invalid "{field}" (not a WKT point list)')
    if not points:
        raise _SkipFeature(f'missing "{field}"')
    if len(points) != 4:
        raise _SkipFeature(f'invalid "{field}" ({len(points)} points instead of 4)')
    return _to_pixels(points, inv_gt)


def _encode_word(word: str) -> List[int]:
    """Character ids, unknown characters -> UNKNOWN_TOKEN, truncated / padded to MAX_TEXT_LENGTH."""
    word = unicodedata.normalize("NFC", word)  # a + combining diaeresis -> ä
    rec = [character_map.get(char, UNKNOWN_TOKEN) for char in word[:MAX_TEXT_LENGTH]]
    return rec + [PAD_TOKEN] * (MAX_TEXT_LENGTH - len(rec))


def _json_value(value):
    """NaN / infinity are not valid JSON: export them as null like NULL."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _flatten(points: Sequence[Point]) -> List[float]:
    return [float(c) for point in points for c in point]


def _is_null(value) -> bool:
    return value is None or (isinstance(value, QVariant) and value.isNull())


# --- geometry / raster helpers ----------------------------------------------

@contextlib.contextmanager
def _quiet_gdal():
    """Silence GDAL/OGR error messages; failures are reported as skip reasons."""
    gdal.PushErrorHandler("CPLQuietErrorHandler")
    try:
        yield
    finally:
        gdal.PopErrorHandler()


def _parse_points(wkt) -> Optional[List[Point]]:
    """Vertices of a (Multi)Point WKT. [] for NULL / empty, None if unparseable."""
    if wkt is None or not str(wkt).strip():
        return []
    with _quiet_gdal():
        try:
            geom = ogr.CreateGeometryFromWkt(str(wkt))
        except RuntimeError:  # gdal/ogr.UseExceptions() enabled elsewhere in the process
            geom = None
    if geom is None:
        return None
    return _vertices(geom)


def _vertices(geom) -> List[Point]:
    if geom.GetGeometryCount():
        points = []
        for i in range(geom.GetGeometryCount()):
            points.extend(_vertices(geom.GetGeometryRef(i)))
        return points
    return [(geom.GetX(i), geom.GetY(i)) for i in range(geom.GetPointCount())]


def _to_pixels(points: Sequence[Point], inv_gt: Sequence[float]) -> List[Point]:
    return [tuple(gdal.ApplyGeoTransform(inv_gt, x, y)) for x, y in points]


def _raster_info(path: str, cache: Dict) -> Tuple[Sequence[float], int, int]:
    """(inverse geotransform, width, height) of a raster, cached per export.
    Raises _SkipFeature if it can't be used."""
    if path not in cache:
        cache[path] = _open_raster(path)
    info, error = cache[path]
    if info is None:
        raise _SkipFeature(error)
    return info


def _open_raster(path: str):
    """GDAL only reads the header here, so this is cheap even for huge scans
    (unlike PIL, which refuses them as decompression bombs)."""
    with _quiet_gdal():
        try:
            ds = gdal.Open(path)
        except RuntimeError:
            ds = None
    if ds is None:
        return None, f"reference image can't be opened: {path}"
    gt = ds.GetGeoTransform(can_return_null=True)
    width, height = ds.RasterXSize, ds.RasterYSize
    ds = None
    inv_gt = gdal.InvGeoTransform(gt or _UNGEOREFERENCED_GT)
    if inv_gt is None:
        return None, f"geotransform of the reference image is not invertible: {path}"
    return (inv_gt, width, height), None


def _plugin_version() -> str:
    """Version from metadata.txt, "unknown" if it can't be read."""
    parser = configparser.RawConfigParser(strict=False)
    try:
        with open(_METADATA_PATH, encoding="utf-8") as f:
            parser.read_file(f)
        return parser.get("general", "version", fallback="").strip() or "unknown"
    except (OSError, UnicodeDecodeError, configparser.Error):
        return "unknown"
