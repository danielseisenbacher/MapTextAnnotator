# -*- coding: utf-8 -*-
"""
Attribute schema of an annotation layer.

Storage contract (what the per-feature pipeline writes, what the export reads):

- "Bounding Points", "Bounding Box" (2 corners: min, max) and
  "Oriented Bounding Box" (4 corners) are MultiPoint WKT in the CRS of the
  reference raster ("Reference Image").
- "Lower Bezier" holds 4 cubic control points in drawing order,
  bottom-left -> bottom-right. "Upper Bezier" holds 4 control points in drawing
  order, top-right -> top-left. Both are MultiPoint WKT in the reference
  raster's CRS. Re-ordering for a target format happens only at export time.
- "Lat" / "Lon" are the polygon centroid in EPSG:4326.
- "Reference Image" is the file path of the reference raster, or
  NO_REFERENCE_IMAGE when no suitable raster was found.
"""

from qgis.PyQt.QtCore import QVariant

NO_REFERENCE_IMAGE = "None found"

# Every field a newly generated annotation layer gets. Order matters for layer
# creation. "Phrase Transcription" is legacy: kept for compatibility, never written.
FIELDS = {
    "Word Transcription": QVariant.String,
    "Phrase Transcription": QVariant.String,
    "Reference Image": QVariant.String,
    "Lat": QVariant.Double,
    "Lon": QVariant.Double,
    "Bounding Points": QVariant.String,
    "Bounding Box": QVariant.String,
    "Oriented Bounding Box": QVariant.String,
    "Upper Bezier": QVariant.String,
    "Lower Bezier": QVariant.String,
    "Mean Altitude": QVariant.Double,
    "Median Altitude": QVariant.Double,
    "Max Altitude": QVariant.Double,
    "Min Altitude": QVariant.Double,
    "Mean Slope": QVariant.Double,
    "Median Slope": QVariant.Double,
    "Max Slope": QVariant.Double,
    "Min Slope": QVariant.Double,
    "Complexity": QVariant.Double,
    "Contrast": QVariant.Double,
    "Word uuid": QVariant.String,
    "Link to previous Word": QVariant.Bool,
    "Create Date": QVariant.DateTime,
    "Certainty": QVariant.Int,
}

# Fields a layer must have (with matching types) to be offered as an annotation
# layer. Stat fields are optional: the pipeline skips fields a layer lacks.
CORE_FIELDS = [
    "Word Transcription",
    "Reference Image",
    "Bounding Points",
    "Bounding Box",
    "Oriented Bounding Box",
    "Upper Bezier",
    "Lower Bezier",
    "Link to previous Word",
    "Create Date",
]

# Optional statistic groups -> layer fields. Keys match settings.STAT_TOGGLES.
STAT_FIELDS = {
    "altitude": ["Mean Altitude", "Median Altitude", "Max Altitude", "Min Altitude"],
    "slope": ["Mean Slope", "Median Slope", "Max Slope", "Min Slope"],
    "edge_complexity": ["Complexity"],
    "contrast": ["Contrast"],
    "centroid": ["Lat", "Lon"],
}

# Statistic groups -> {layer field: exported JSON key}. Groups disabled in the
# settings are omitted from the export entirely.
STAT_EXPORT_KEYS = {
    "altitude": {
        "Mean Altitude": "mean_altitude",
        "Median Altitude": "median_altitude",
        "Max Altitude": "max_altitude",
        "Min Altitude": "min_altitude",
    },
    "slope": {
        "Mean Slope": "mean_slope",
        "Median Slope": "median_slope",
        "Max Slope": "max_slope",
        "Min Slope": "min_slope",
    },
    "edge_complexity": {"Complexity": "complexity"},
    "contrast": {"Contrast": "contrast"},
    "centroid": {"Lat": "lat", "Lon": "lon"},
}
