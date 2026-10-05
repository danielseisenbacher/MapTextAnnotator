# -*- coding: utf-8 -*-
"""
Per-feature processing: everything that is computed and written into an
annotation feature's attributes when it is added or its geometry changes.

Core computations are called through module attributes
(raster_stats.zonal_stats, edge_density.edge_density, ...) so tests can patch them.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, FrozenSet, Optional, Tuple

from qgis.core import QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry, QgsRasterLayer, QgsVectorLayer

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


def set_attr(layer: QgsVectorLayer, fid: int, name: str, value) -> bool:
    """Write one attribute into the layer's edit buffer. Returns False (without
    raising) if the layer isn't editable or has no such field."""
    raise NotImplementedError


def find_reference_raster(geom: QgsGeometry, ctx: PipelineContext) -> Optional[QgsRasterLayer]:
    """Top-most visible GDAL raster layer backed by an existing file that
    intersects `geom` (in ctx.layer's CRS), excluding ctx.excluded_layer_ids."""
    raise NotImplementedError


def process_feature(fid: int, ctx: PipelineContext) -> FeatureResult:
    """Compute and write all enabled attributes of feature `fid` into the
    layer's edit buffer. Never raises: each step is isolated, failures are
    reported through ctx.warn and leave ok=False."""
    raise NotImplementedError


def stored_stats(feature: QgsFeature) -> Dict[str, Optional[float]]:
    """Headline values (DISPLAY_STATS keys) already stored in the feature;
    None for missing fields or NULL values."""
    raise NotImplementedError


def transcription_for(layer: QgsVectorLayer, fid: int) -> Tuple[Optional[str], Optional[str]]:
    """(word, phrase) of feature `fid`; NULL-safe (core.phrases)."""
    raise NotImplementedError


def dataset_counts(layer: QgsVectorLayer) -> Tuple[int, int, int]:
    """(label count, phrase count, distinct reference image count) of the layer.
    Features without a reference image (schema.NO_REFERENCE_IMAGE / NULL) are
    not counted as images."""
    raise NotImplementedError
