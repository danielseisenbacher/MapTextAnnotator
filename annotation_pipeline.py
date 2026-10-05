# -*- coding: utf-8 -*-
"""
Per-feature processing: everything that is computed and written into an
annotation feature's attributes when it is added or its geometry changes.

Core computations are called through module attributes
(raster_stats.zonal_stats, edge_density.edge_density, ...) so tests can patch them.
"""

import math
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, FrozenSet, List, Optional, Tuple

from osgeo import gdal
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCsException,
    QgsFeature,
    QgsFeatureRequest,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QDate, QDateTime, Qt, QTime, QVariant

from .core import edge_density, geometry, phrases, raster_stats
from . import schema
from . import settings as plugin_settings

# Keys of the headline values shown in the dock (FeatureResult.stats,
# stored_stats, MaptextAnnotatorDockWidget.show_stats):
# altitude -> Mean Altitude, slope -> Mean Slope,
# edge_complexity -> Complexity, contrast -> Contrast.
DISPLAY_STATS = {
    "altitude": "Mean Altitude",
    "slope": "Mean Slope",
    "edge_complexity": "Complexity",
    "contrast": "Contrast",
}

# Keys passed to PipelineContext.warn(key, message). The controller shows each
# key at most once until settings or layers change.
WARN_NO_DEM = "no_dem"
WARN_NO_SLOPE = "no_slope"
WARN_NO_REFERENCE = "no_reference"
WARN_INVALID_GEOMETRY = "invalid_geometry"
WARN_EDGE_UNAVAILABLE = "edge_unavailable"
WARN_STAT_FAILED = "stat_failed"

# Layer field -> raster_stats.zonal_stats key, per zonal statistic group
ZONAL_FIELDS = {
    "altitude": {
        "Mean Altitude": "mean",
        "Median Altitude": "median",
        "Max Altitude": "max",
        "Min Altitude": "min",
    },
    "slope": {
        "Mean Slope": "mean",
        "Median Slope": "median",
        "Max Slope": "max",
        "Min Slope": "min",
    },
}

BOUNDING_FIELDS = ("Bounding Points", "Bounding Box", "Oriented Bounding Box")
BEZIER_FIELDS = ("Lower Bezier", "Upper Bezier")

# GDAL virtual file systems that are local (checked with VSIStatL, no network access)
_LOCAL_VSI_PREFIXES = ("/vsimem/", "/vsizip/", "/vsitar/", "/vsigzip/", "/vsi7z/", "/vsirar/")

_INVALID_GEOMETRY_HINT = (
    "Draw at least 4 vertices counter-clockwise from the bottom-left corner, with the same "
    "number of vertices on the bottom and the top edge. The annotation is left out of the "
    "export until it is fixed."
)


@dataclass
class PipelineContext:
    layer: QgsVectorLayer
    settings: plugin_settings.PluginSettings
    dem_layer: Optional[QgsRasterLayer] = None
    slope_layer: Optional[QgsRasterLayer] = None
    # Never used as reference image (the DEM / slope layers, whether or not their stats are enabled)
    excluded_layer_ids: FrozenSet[str] = frozenset()
    # Used when a raster or the layer has an invalid CRS (canvas destination CRS)
    fallback_crs: Optional[QgsCoordinateReferenceSystem] = None
    warn: Callable[[str, str], None] = lambda key, message: None


@dataclass
class FeatureResult:
    reference_image: Optional[str] = None
    # DISPLAY_STATS key -> headline value (None if not computed)
    stats: Dict[str, Optional[float]] = field(default_factory=dict)
    ok: bool = True


# ---------------------------------------------------------------------------
# helpers

def _is_null(value) -> bool:
    return value is None or (isinstance(value, QVariant) and value.isNull())


def _clean(value):
    """NULL / empty string -> None, anything else unchanged."""
    return None if _is_null(value) or value == "" else value


def _truthy(value) -> bool:
    value = _clean(value)
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in ("true", "t", "yes", "y", "1")
    return bool(value)


def _round(value) -> Optional[float]:
    if value is None:
        return None
    value = float(value)
    return round(value, 2) if math.isfinite(value) else None


def _date_key(value) -> Optional[float]:
    """A comparable sort key (ms since epoch) for a date / datetime value, or None."""
    value = _clean(value)
    if value is None:
        return None
    if isinstance(value, QDateTime):
        return float(value.toMSecsSinceEpoch()) if value.isValid() else None
    if isinstance(value, QDate):
        return float(QDateTime(value, QTime(0, 0)).toMSecsSinceEpoch()) if value.isValid() else None
    if isinstance(value, str):
        parsed = QDateTime.fromString(value, Qt.ISODate)
        return float(parsed.toMSecsSinceEpoch()) if parsed.isValid() else None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _valid_crs(crs, fallback) -> Optional[QgsCoordinateReferenceSystem]:
    if crs is not None and crs.isValid():
        return crs
    if fallback is not None and fallback.isValid():
        return fallback
    return None


def _transformed(geom: QgsGeometry, source_crs, dest_crs) -> QgsGeometry:
    """Copy of geom transformed between two CRSs. A missing CRS on either side
    means the coordinates are taken as they are. Raises QgsCsException."""
    result = QgsGeometry(geom)
    if source_crs is None or dest_crs is None or source_crs == dest_crs:
        return result
    result.transform(QgsCoordinateTransform(source_crs, dest_crs, QgsProject.instance()))
    return result


def _raster_path(layer: QgsRasterLayer) -> str:
    """GDAL path of a raster layer, without "|option" suffixes."""
    return layer.source().split("|")[0]


def _existing_path(layer: QgsRasterLayer) -> Optional[str]:
    """The layer's file path if it exists locally, else None (web services, missing files)."""
    path = _raster_path(layer)
    if not path:
        return None
    if path.startswith(_LOCAL_VSI_PREFIXES):
        return path if gdal.VSIStatL(path) is not None else None
    return path if os.path.exists(path) else None


def _exterior_ring(geom: QgsGeometry) -> List[geometry.Point]:
    """Exterior ring vertices of a single-part polygon (closing vertex included)."""
    if geom.isMultipart():
        parts = geom.asMultiPolygon()
        if len(parts) != 1:
            raise geometry.InvalidAnnotationGeometry(
                f"the annotation has {len(parts)} parts, a single polygon is needed"
            )
        rings = parts[0]
    else:
        rings = geom.asPolygon()
    if not rings:
        raise geometry.InvalidAnnotationGeometry("the annotation is not a polygon")
    return [(p.x(), p.y()) for p in rings[0]]


def _multipoint_wkt(points) -> Optional[str]:
    if not points:
        return None
    return QgsGeometry.fromMultiPointXY([QgsPointXY(x, y) for x, y in points]).asWkt()


def _write(layer: QgsVectorLayer, fid: int, values: Dict[str, object]) -> None:
    for name, value in values.items():
        set_attr(layer, fid, name, value)


def _warn(ctx: PipelineContext, result: FeatureResult, key: str, message: str) -> None:
    result.ok = False
    try:
        ctx.warn(key, message)
    except Exception:
        pass


def _field_value(feature: QgsFeature, name: str):
    idx = feature.fields().indexOf(name)
    return None if idx == -1 else _clean(feature.attribute(idx))


def _features(layer: QgsVectorLayer, names):
    """Iterate the layer's features (edit buffer included) without geometry,
    fetching only the given fields that exist."""
    fields = layer.fields()
    request = QgsFeatureRequest().setFlags(QgsFeatureRequest.NoGeometry)
    request.setSubsetOfAttributes([n for n in names if fields.indexOf(n) != -1], fields)
    return layer.getFeatures(request)


# ---------------------------------------------------------------------------
# public API

def set_attr(layer: QgsVectorLayer, fid: int, name: str, value) -> bool:
    """Write one attribute into the layer's edit buffer. Returns False (without
    raising) if the layer isn't editable or has no such field."""
    try:
        if layer is None or not layer.isEditable():
            return False
        idx = layer.fields().indexOf(name)
        if idx == -1:
            return False
        return bool(layer.changeAttributeValue(fid, idx, value))
    except (RuntimeError, TypeError):
        return False


def find_reference_raster(geom: QgsGeometry, ctx: PipelineContext) -> Optional[QgsRasterLayer]:
    """Top-most visible GDAL raster layer backed by an existing file that
    intersects `geom` (in ctx.layer's CRS), excluding ctx.excluded_layer_ids."""
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    # layerOrder() lists the rendered layers top-most first
    order = {layer.id(): i for i, layer in enumerate(root.layerOrder())}
    layer_crs = _valid_crs(ctx.layer.crs(), ctx.fallback_crs)

    candidates = []
    for raster in project.mapLayers().values():
        if not isinstance(raster, QgsRasterLayer) or raster.providerType() != "gdal":
            continue
        if not raster.isValid() or raster.id() in ctx.excluded_layer_ids:
            continue
        node = root.findLayer(raster.id())
        if node is None or not node.isVisible():
            continue
        if _existing_path(raster) is None:
            continue
        try:
            raster_geom = _transformed(geom, layer_crs, _valid_crs(raster.crs(), ctx.fallback_crs))
        except QgsCsException:
            continue
        if raster_geom.intersects(raster.extent()):
            candidates.append(raster)

    if not candidates:
        return None
    return min(candidates, key=lambda layer: order.get(layer.id(), len(order)))


def process_feature(fid: int, ctx: PipelineContext) -> FeatureResult:
    """Compute and write all enabled attributes of feature `fid` into the
    layer's edit buffer. Never raises: each step is isolated, failures are
    reported through ctx.warn and leave ok=False."""
    result = FeatureResult()
    try:
        _process(fid, ctx, result)
    except Exception as e:  # last resort, the steps below handle their own errors
        _warn(ctx, result, WARN_STAT_FAILED, f"Processing annotation {fid} failed: {e}")
    return result


def _process(fid: int, ctx: PipelineContext, result: FeatureResult) -> None:
    layer = ctx.layer
    settings = ctx.settings

    feature = layer.getFeature(fid)
    geom = feature.geometry() if feature.isValid() else None
    if geom is None or geom.isEmpty():
        _warn(ctx, result, WARN_INVALID_GEOMETRY, f"Annotation {fid} has no geometry.")
        return
    geom = QgsGeometry(geom)
    layer_crs = _valid_crs(layer.crs(), ctx.fallback_crs)

    # 1. reference image: the top-most visible raster under the annotation
    raster = None
    try:
        raster = find_reference_raster(geom, ctx)
    except Exception as e:
        _warn(ctx, result, WARN_STAT_FAILED, f"Looking up the reference image failed: {e}")
    raster_path = _raster_path(raster) if raster is not None else None
    result.reference_image = raster_path
    set_attr(layer, fid, "Reference Image", raster_path or schema.NO_REFERENCE_IMAGE)

    # 2. bounding geometries in the reference raster's CRS
    raster_geom = None
    bounds = dict.fromkeys(BOUNDING_FIELDS)
    if raster is None:
        _warn(ctx, result, WARN_NO_REFERENCE,
              "No visible raster image lies below the annotation. Annotations without a "
              "reference image are left out of the export.")
    else:
        try:
            raster_geom = _transformed(geom, layer_crs, _valid_crs(raster.crs(), ctx.fallback_crs))
            bbox = raster_geom.boundingBox()
            bounds["Bounding Box"] = _multipoint_wkt(
                [(bbox.xMinimum(), bbox.yMinimum()), (bbox.xMaximum(), bbox.yMaximum())]
            )
            obb = raster_geom.orientedMinimumBoundingBox()[0].asPolygon()
            if obb:
                bounds["Oriented Bounding Box"] = _multipoint_wkt(
                    geometry.ring_vertices([(p.x(), p.y()) for p in obb[0]])
                )
            try:
                bounds["Bounding Points"] = _multipoint_wkt(geometry.ring_vertices(_exterior_ring(raster_geom)))
            except geometry.InvalidAnnotationGeometry:
                pass  # reported by the bezier step
        except Exception as e:
            _warn(ctx, result, WARN_STAT_FAILED, f"Bounding boxes of annotation {fid} failed: {e}")
    _write(layer, fid, bounds)

    # 3. beziers: the drawing is validated in any case, the curves are stored
    # (in raster coordinates) only with a reference image. NULL otherwise, so
    # stale curves never survive a geometry edit.
    beziers = dict.fromkeys(BEZIER_FIELDS)
    try:
        lower, upper = geometry.beziers_from_ring(_exterior_ring(raster_geom if raster_geom is not None else geom))
        if raster_geom is not None:
            beziers = {"Lower Bezier": _multipoint_wkt(lower), "Upper Bezier": _multipoint_wkt(upper)}
    except geometry.InvalidAnnotationGeometry as e:
        _warn(ctx, result, WARN_INVALID_GEOMETRY,
              f"Annotation {fid} can't be turned into bezier curves: {e}. {_INVALID_GEOMETRY_HINT}")
    except Exception as e:
        _warn(ctx, result, WARN_STAT_FAILED, f"Bezier curves of annotation {fid} failed: {e}")
    _write(layer, fid, beziers)

    # 4. centroid in WGS84
    if settings.stat_enabled("centroid"):
        lat = lon = None
        try:
            if layer_crs is None:
                raise ValueError("the annotation layer has no valid CRS")
            point = _transformed(geom.centroid(), layer_crs, QgsCoordinateReferenceSystem("EPSG:4326")).asPoint()
            lat, lon = point.y(), point.x()
        except Exception as e:
            _warn(ctx, result, WARN_STAT_FAILED, f"Centroid of annotation {fid} failed: {e}")
        _write(layer, fid, {"Lat": lat, "Lon": lon})

    # 5. altitude / slope from the chosen DEM / slope layers
    for group, zonal_layer, warn_key, label in (
        ("altitude", ctx.dem_layer, WARN_NO_DEM, "DEM"),
        ("slope", ctx.slope_layer, WARN_NO_SLOPE, "slope"),
    ):
        if not settings.stat_enabled(group):
            continue
        if zonal_layer is None:
            _warn(ctx, result, warn_key,
                  f"No {label} layer selected, {group} statistics are skipped. Choose a "
                  f"{label} layer or disable {group} statistics in the settings.")
            continue
        values = dict.fromkeys(ZONAL_FIELDS[group])
        try:
            zonal_crs = _valid_crs(zonal_layer.crs(), ctx.fallback_crs)
            wkt = _transformed(geom, layer_crs, zonal_crs).asWkt()
            stats = raster_stats.zonal_stats(_raster_path(zonal_layer), wkt)
            if stats:
                values = {name: _round(stats.get(key)) for name, key in ZONAL_FIELDS[group].items()}
        except Exception as e:
            _warn(ctx, result, WARN_STAT_FAILED, f"{label.capitalize()} statistics of annotation {fid} failed: {e}")
        _write(layer, fid, values)
        result.stats[group] = values[DISPLAY_STATS[group]]

    # 6. edge complexity on the reference image
    if settings.stat_enabled("edge_complexity"):
        value, write = None, True
        if raster_geom is not None:
            try:
                value = _round(edge_density.edge_density(
                    raster_path,
                    raster_geom.asWkt(),
                    width=settings.get(plugin_settings.EDGE_WIDTH),
                    threshold=settings.get(plugin_settings.EDGE_THRESHOLD),
                    buffer_ratio=settings.get(plugin_settings.EDGE_BUFFER),
                ))
            except edge_density.EdgeDensityUnavailable:
                write = False  # a setup problem: keep what is stored
                _warn(ctx, result, WARN_EDGE_UNAVAILABLE,
                      "GRASS i.zc is not available, edge complexity is skipped. Enable the GRASS "
                      "processing provider or disable edge complexity in the settings.")
            except Exception as e:
                _warn(ctx, result, WARN_STAT_FAILED, f"Edge complexity of annotation {fid} failed: {e}")
        if write:
            set_attr(layer, fid, "Complexity", value)
            result.stats["edge_complexity"] = value

    # 7. contrast on the reference image
    if settings.stat_enabled("contrast"):
        value = None
        if raster_geom is not None:
            try:
                value = _round(raster_stats.contrast(
                    raster_path,
                    raster_geom.asWkt(),
                    settings.get(plugin_settings.CONTRAST_LOWER),
                    settings.get(plugin_settings.CONTRAST_UPPER),
                ))
            except Exception as e:
                _warn(ctx, result, WARN_STAT_FAILED, f"Contrast of annotation {fid} failed: {e}")
        set_attr(layer, fid, "Contrast", value)
        result.stats["contrast"] = value


def stored_stats(feature: QgsFeature) -> Dict[str, Optional[float]]:
    """Headline values (DISPLAY_STATS keys) already stored in the feature;
    None for missing fields or NULL values."""
    values = {}
    for key, name in DISPLAY_STATS.items():
        value = _field_value(feature, name)
        try:
            values[key] = None if value is None else float(value)
        except (TypeError, ValueError):
            values[key] = None
    return values


def transcription_for(layer: QgsVectorLayer, fid: int) -> Tuple[Optional[str], Optional[str]]:
    """(word, phrase) of feature `fid`; NULL-safe (core.phrases)."""
    feature = layer.getFeature(fid)
    if not feature.isValid():
        return None, None
    word = _field_value(feature, "Word Transcription")

    records = []
    for f in _features(layer, ("Word Transcription", "Create Date", "Link to previous Word")):
        text = _field_value(f, "Word Transcription")
        records.append((
            f.id(),
            _date_key(_field_value(f, "Create Date")),
            None if text is None else str(text),
            _truthy(_field_value(f, "Link to previous Word")),
        ))
    return (None if word is None else str(word)), phrases.phrase_for(records, fid)


def dataset_counts(layer: QgsVectorLayer) -> Tuple[int, int, int]:
    """(label count, phrase count, distinct reference image count) of the layer.
    Features without a reference image (schema.NO_REFERENCE_IMAGE / NULL) are
    not counted as images."""
    labels = phrase_count = 0
    images = set()
    for f in _features(layer, ("Link to previous Word", "Reference Image")):
        labels += 1
        if not _truthy(_field_value(f, "Link to previous Word")):
            phrase_count += 1
        image = _field_value(f, "Reference Image")
        if image is not None and image != schema.NO_REFERENCE_IMAGE:
            images.add(image)
    return labels, phrase_count, len(images)
