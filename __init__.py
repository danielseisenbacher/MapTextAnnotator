# -*- coding: utf-8 -*-
"""
MapText Annotator: a QGIS plugin to annotate text on scanned maps.

(C) 2026 Daniel Seisenbacher, GPL-2.0-or-later.
"""


def classFactory(iface):  # pylint: disable=invalid-name
    """Entry point QGIS calls to load the plugin."""
    from .MaptextAnnotator import MaptextAnnotator
    return MaptextAnnotator(iface)
