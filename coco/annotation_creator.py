# -*- coding: utf-8 -*-
"""
Export of an annotation layer to a COCO-style JSON (ABCNet / DeepSolo flavour).

Coordinates are read from the stored WKT (reference raster CRS, see schema.py)
and converted to pixel coordinates of the reference image via its inverse
geotransform.
"""

from typing import Dict, FrozenSet, List, Tuple

from .. import schema

# (fid, reason) of a feature left out of the export
Skipped = Tuple[int, str]


def records_from_layer(layer) -> List[Dict]:
    """One plain dict per feature: {"fid": feature id, <field name>: value},
    NULL values converted to None. Decouples the export from QGIS objects."""
    raise NotImplementedError


def build_annotations(records: List[Dict], bbox_format: str = "xyxy", bezier_order: str = "abcnet",
                      enabled_stats: FrozenSet[str] = frozenset(schema.STAT_FIELDS)) -> Tuple[Dict, List[Skipped]]:
    """Build a fresh COCO dict from records (see records_from_layer).

    bbox_format: a key of settings.BBOX_FORMATS. bezier_order: a key of
    settings.BEZIER_ORDERS. Statistic groups not in enabled_stats are omitted.
    Features that can't be exported (no / unreadable reference image, missing
    or invalid beziers, empty transcription) are skipped and returned with a
    reason instead of raising."""
    raise NotImplementedError


def write_annotations(coco_dict: Dict, path: str) -> None:
    """Write JSON atomically (temp file in the same directory + os.replace)."""
    raise NotImplementedError
