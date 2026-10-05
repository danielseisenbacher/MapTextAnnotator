# -*- coding: utf-8 -*-
"""
User settings, persisted in the QGIS user profile via QgsSettings so they are
remembered across sessions. Layer choices (DEM, slope, annotation layer) are
project-specific and stored in the project instead, see PROJECT_* below.
"""

import math

from qgis.core import QgsSettings

PREFIX = "MaptextAnnotator/"

ALTITUDE = "stats/altitude"
SLOPE = "stats/slope"
CONTRAST = "stats/contrast"
EDGE = "stats/edge_complexity"
CENTROID = "stats/centroid"
EDGE_WIDTH = "edge/width"
EDGE_THRESHOLD = "edge/threshold"
EDGE_BUFFER = "edge/buffer_ratio"
CONTRAST_LOWER = "contrast/lower_pct"
CONTRAST_UPPER = "contrast/upper_pct"
BBOX_FORMAT = "export/bbox_format"
BEZIER_ORDER = "export/bezier_order"
LAST_DIR = "export/last_dir"
SHOW_INSTRUCTIONS = "ui/show_instructions"

DEFAULTS = {
    ALTITUDE: True,
    SLOPE: True,
    CONTRAST: True,
    EDGE: True,
    CENTROID: True,
    EDGE_WIDTH: 3,
    EDGE_THRESHOLD: 5.0,
    EDGE_BUFFER: 0.1,
    CONTRAST_LOWER: 5.0,
    CONTRAST_UPPER: 95.0,
    BBOX_FORMAT: "xyxy",
    BEZIER_ORDER: "abcnet",
    LAST_DIR: "",
    SHOW_INSTRUCTIONS: True,
}

# Statistic group (schema.STAT_FIELDS key) -> settings key that enables it.
STAT_TOGGLES = {
    "altitude": ALTITUDE,
    "slope": SLOPE,
    "edge_complexity": EDGE,
    "contrast": CONTRAST,
    "centroid": CENTROID,
}

# Export bbox formats, all in pixel coordinates with y pointing down.
BBOX_FORMATS = {
    "xyxy": "[x_min, y_min, x_max, y_max]",
    "xywh": "COCO [x, y, width, height]",
    "polygon": "4 corners [x1, y1, ..., x4, y4], clockwise from top-left",
}

BEZIER_ORDERS = {
    "abcnet": "ABCNet / DeepSolo: top curve left to right, bottom curve right to left",
    "legacy": "Legacy (v0.1): both curves right to left",
}

ENUMS = {
    BBOX_FORMAT: BBOX_FORMATS,
    BEZIER_ORDER: BEZIER_ORDERS,
}

# Per-project layer memory: QgsProject.writeEntry(PROJECT_SCOPE, PROJECT_*_LAYER, layer.id())
PROJECT_SCOPE = "MaptextAnnotator"
PROJECT_DEM_LAYER = "/dem_layer_id"
PROJECT_SLOPE_LAYER = "/slope_layer_id"
PROJECT_ANNOTATION_LAYER = "/annotation_layer_id"

_TRUE = ("true", "1", "yes", "on")
_FALSE = ("false", "0", "no", "off", "")


def coerce(key, value):
    """Convert value to the type of the key's default. Raises KeyError for an
    unknown key and ValueError if the value can't be converted or is not an
    allowed enum value."""
    default = DEFAULTS[key]
    try:
        if isinstance(default, bool):
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in _TRUE:
                    return True
                if lowered in _FALSE:
                    return False
                raise ValueError(value)
            return bool(value)
        if isinstance(default, int):
            number = float(value)
            if not number.is_integer():
                raise ValueError(value)
            return int(number)
        if isinstance(default, float):
            result = float(value)
            if not math.isfinite(result):
                raise ValueError(value)
            return result
        result = "" if value is None else str(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Invalid value for {key!r}: {value!r}") from e

    if key in ENUMS and result not in ENUMS[key]:
        raise ValueError(f"Invalid value for {key!r}: {value!r}, expected one of {sorted(ENUMS[key])}")
    return result


class PluginSettings:
    """In-memory view of the plugin settings, backed by a QgsSettings store.

    Values are loaded on construction. set() only changes the in-memory value;
    call save() to persist.
    """

    def __init__(self, store=None):
        self._store = store if store is not None else QgsSettings()
        self._values = dict(DEFAULTS)
        self.load()

    def load(self):
        """Read all values from the store. Missing or invalid values fall back to defaults."""
        for key, default in DEFAULTS.items():
            raw = self._store.value(PREFIX + key, default)
            try:
                self._values[key] = coerce(key, raw)
            except ValueError:
                self._values[key] = default

    def save(self):
        for key, value in self._values.items():
            self._store.setValue(PREFIX + key, value)
        self._store.sync()

    def get(self, key):
        return self._values[key]

    def set(self, key, value):
        if key not in DEFAULTS:
            raise KeyError(key)
        self._values[key] = coerce(key, value)

    def reset(self):
        """Restore defaults in memory. Call save() to persist."""
        self._values = dict(DEFAULTS)

    def as_dict(self):
        return dict(self._values)

    def stat_enabled(self, group):
        """Whether a statistic group (schema.STAT_FIELDS key) is enabled."""
        return bool(self._values[STAT_TOGGLES[group]])

    def enabled_stats(self):
        return frozenset(group for group in STAT_TOGGLES if self.stat_enabled(group))
