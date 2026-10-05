# -*- coding: utf-8 -*-
"""Settings dialog. Edits a settings.PluginSettings instance; Accept saves it."""

from qgis.PyQt.QtWidgets import QDialog


class SettingsDialog(QDialog):
    """Widgets (objectName): altitudeCheck, slopeCheck, contrastCheck, edgeCheck,
    centroidCheck, edgeWidthSpin, edgeThresholdSpin, contrastLowerSpin,
    contrastUpperSpin, bboxFormatCombo, bezierOrderCombo (itemData = enum key),
    showInstructionsCheck, restoreDefaultsButton, buttonBox.

    edge_available=False disables the edge complexity controls (GRASS missing)."""

    def __init__(self, settings, parent=None, edge_available=True):
        super().__init__(parent)
        raise NotImplementedError
