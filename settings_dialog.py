# -*- coding: utf-8 -*-
"""Settings dialog. Edits a settings.PluginSettings instance; Accept saves it."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from . import settings as plugin_settings

WINDOW_TITLE = "MapText Annotator Settings"
EDGE_UNAVAILABLE_TOOLTIP = "GRASS i.zc is not available — enable the GRASS provider in Processing"

# Settings without a widget that "Restore Defaults" also resets. LAST_DIR is
# remembered state, not a preference, and is left alone.
_HIDDEN_KEYS = (plugin_settings.EDGE_BUFFER,)


class SettingsDialog(QDialog):
    """Widgets (objectName): altitudeCheck, slopeCheck, contrastCheck, edgeCheck,
    centroidCheck, edgeWidthSpin, edgeThresholdSpin, contrastLowerSpin,
    contrastUpperSpin, bboxFormatCombo, bezierOrderCombo (itemData = enum key),
    showInstructionsCheck, restoreDefaultsButton, buttonBox.

    edge_available=False disables the edge complexity controls (GRASS missing)."""

    def __init__(self, settings, parent=None, edge_available=True):
        super().__init__(parent)
        self.settings = settings
        self.edge_available = bool(edge_available)
        self._restore_hidden_defaults = False

        self.setWindowTitle(WINDOW_TITLE)
        self._build_ui()
        self._load_values(settings.as_dict())

    # -- construction -------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Statistics
        stats_group = QGroupBox("Statistics", self)
        stats_layout = QVBoxLayout(stats_group)
        self.altitudeCheck = self._check("altitudeCheck", "Altitude (requires a DEM layer)", stats_group)
        self.slopeCheck = self._check("slopeCheck", "Slope (requires a slope layer)", stats_group)
        self.edgeCheck = self._check("edgeCheck", "Edge complexity (requires GRASS)", stats_group)
        self.contrastCheck = self._check("contrastCheck", "Contrast", stats_group)
        self.centroidCheck = self._check("centroidCheck", "Centroid (Lat/Lon, WGS 84)", stats_group)
        for check in (self.altitudeCheck, self.slopeCheck, self.edgeCheck, self.contrastCheck,
                      self.centroidCheck):
            stats_layout.addWidget(check)
        hint = QLabel("Disabled statistics are neither computed nor exported.", stats_group)
        hint.setWordWrap(True)
        stats_layout.addWidget(hint)
        layout.addWidget(stats_group)

        # Edge complexity
        self.edgeGroup = QGroupBox("Edge complexity", self)
        edge_layout = QFormLayout(self.edgeGroup)
        self.edgeWidthSpin = QSpinBox(self.edgeGroup)
        self.edgeWidthSpin.setObjectName("edgeWidthSpin")
        self.edgeWidthSpin.setRange(1, 15)
        self.edgeWidthSpin.setToolTip("Width of the Gaussian filter of GRASS i.zc (odd values recommended)")
        self.edgeThresholdSpin = QDoubleSpinBox(self.edgeGroup)
        self.edgeThresholdSpin.setObjectName("edgeThresholdSpin")
        self.edgeThresholdSpin.setRange(0.0, 1000.0)
        self.edgeThresholdSpin.setDecimals(2)
        self.edgeThresholdSpin.setSingleStep(0.5)
        self.edgeThresholdSpin.setToolTip("Sensitivity threshold of the GRASS i.zc zero-crossing edge detection")
        edge_layout.addRow("Filter width:", self.edgeWidthSpin)
        edge_layout.addRow("Threshold:", self.edgeThresholdSpin)
        layout.addWidget(self.edgeGroup)

        # Contrast
        contrast_group = QGroupBox("Contrast", self)
        contrast_layout = QFormLayout(contrast_group)
        self.contrastLowerSpin = self._percentile_spin("contrastLowerSpin", contrast_group)
        self.contrastUpperSpin = self._percentile_spin("contrastUpperSpin", contrast_group)
        contrast_layout.addRow("Lower percentile:", self.contrastLowerSpin)
        contrast_layout.addRow("Upper percentile:", self.contrastUpperSpin)
        layout.addWidget(contrast_group)

        # Export
        export_group = QGroupBox("Export", self)
        export_layout = QFormLayout(export_group)
        self.bboxFormatCombo = self._enum_combo("bboxFormatCombo", plugin_settings.BBOX_FORMATS, export_group)
        self.bezierOrderCombo = self._enum_combo("bezierOrderCombo", plugin_settings.BEZIER_ORDERS, export_group)
        export_layout.addRow("Bounding box format:", self.bboxFormatCombo)
        export_layout.addRow("Bezier point order:", self.bezierOrderCombo)
        layout.addWidget(export_group)

        # Interface
        interface_group = QGroupBox("Interface", self)
        interface_layout = QVBoxLayout(interface_group)
        self.showInstructionsCheck = self._check("showInstructionsCheck", "Show drawing instructions",
                                                 interface_group)
        interface_layout.addWidget(self.showInstructionsCheck)
        layout.addWidget(interface_group)

        layout.addStretch(1)

        self.buttonBox = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults, self
        )
        self.buttonBox.setObjectName("buttonBox")
        self.restoreDefaultsButton = self.buttonBox.button(QDialogButtonBox.RestoreDefaults)
        self.restoreDefaultsButton.setObjectName("restoreDefaultsButton")
        self.restoreDefaultsButton.setToolTip("Reset all fields to their defaults (applied on OK)")
        layout.addWidget(self.buttonBox)

        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.restoreDefaultsButton.clicked.connect(self.restore_defaults)
        self.edgeCheck.toggled.connect(self._update_enabled_state)
        self.contrastCheck.toggled.connect(self._update_enabled_state)

        if not self.edge_available:
            for widget in (self.edgeCheck, self.edgeGroup, self.edgeWidthSpin, self.edgeThresholdSpin):
                widget.setToolTip(EDGE_UNAVAILABLE_TOOLTIP)

    @staticmethod
    def _check(name, text, parent):
        check = QCheckBox(text, parent)
        check.setObjectName(name)
        return check

    @staticmethod
    def _percentile_spin(name, parent):
        spin = QDoubleSpinBox(parent)
        spin.setObjectName(name)
        spin.setRange(0.0, 100.0)
        spin.setDecimals(2)
        spin.setSingleStep(1.0)
        spin.setToolTip("Contrast is the spread between the lower and upper percentile "
                        "of the pixel values inside the polygon")
        return spin

    @staticmethod
    def _enum_combo(name, choices, parent):
        combo = QComboBox(parent)
        combo.setObjectName(name)
        for key, label in choices.items():
            combo.addItem(label, key)
            combo.setItemData(combo.count() - 1, label, Qt.ToolTipRole)
        return combo

    # -- values ---------------------------------------------------------------

    def _load_values(self, values):
        """Show `values` ({settings key: value}) in the widgets."""
        self.altitudeCheck.setChecked(bool(values[plugin_settings.ALTITUDE]))
        self.slopeCheck.setChecked(bool(values[plugin_settings.SLOPE]))
        self.edgeCheck.setChecked(bool(values[plugin_settings.EDGE]))
        self.contrastCheck.setChecked(bool(values[plugin_settings.CONTRAST]))
        self.centroidCheck.setChecked(bool(values[plugin_settings.CENTROID]))
        self.edgeWidthSpin.setValue(int(values[plugin_settings.EDGE_WIDTH]))
        self.edgeThresholdSpin.setValue(float(values[plugin_settings.EDGE_THRESHOLD]))
        self.contrastLowerSpin.setValue(float(values[plugin_settings.CONTRAST_LOWER]))
        self.contrastUpperSpin.setValue(float(values[plugin_settings.CONTRAST_UPPER]))
        self._select_data(self.bboxFormatCombo, values[plugin_settings.BBOX_FORMAT])
        self._select_data(self.bezierOrderCombo, values[plugin_settings.BEZIER_ORDER])
        self.showInstructionsCheck.setChecked(bool(values[plugin_settings.SHOW_INSTRUCTIONS]))
        self._update_enabled_state()

    @staticmethod
    def _select_data(combo, key):
        index = combo.findData(key)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def values(self):
        """The widget values as {settings key: value}. Keys without a widget are not included."""
        return {
            plugin_settings.ALTITUDE: self.altitudeCheck.isChecked(),
            plugin_settings.SLOPE: self.slopeCheck.isChecked(),
            plugin_settings.EDGE: self.edgeCheck.isChecked(),
            plugin_settings.CONTRAST: self.contrastCheck.isChecked(),
            plugin_settings.CENTROID: self.centroidCheck.isChecked(),
            plugin_settings.EDGE_WIDTH: self.edgeWidthSpin.value(),
            plugin_settings.EDGE_THRESHOLD: self.edgeThresholdSpin.value(),
            plugin_settings.CONTRAST_LOWER: self.contrastLowerSpin.value(),
            plugin_settings.CONTRAST_UPPER: self.contrastUpperSpin.value(),
            plugin_settings.BBOX_FORMAT: self.bboxFormatCombo.currentData(),
            plugin_settings.BEZIER_ORDER: self.bezierOrderCombo.currentData(),
            plugin_settings.SHOW_INSTRUCTIONS: self.showInstructionsCheck.isChecked(),
        }

    def validate(self):
        """Return an error message for invalid widget values, or None if they are valid."""
        if self.contrastCheck.isChecked() and self.contrastLowerSpin.value() >= self.contrastUpperSpin.value():
            return "The lower contrast percentile must be smaller than the upper percentile."
        return None

    # -- slots ------------------------------------------------------------------

    def _update_enabled_state(self, *args):
        self.edgeCheck.setEnabled(self.edge_available)
        edge_on = self.edge_available and self.edgeCheck.isChecked()
        self.edgeWidthSpin.setEnabled(edge_on)
        self.edgeThresholdSpin.setEnabled(edge_on)
        contrast_on = self.contrastCheck.isChecked()
        self.contrastLowerSpin.setEnabled(contrast_on)
        self.contrastUpperSpin.setEnabled(contrast_on)

    def restore_defaults(self):
        """Reset the widgets to the defaults. Nothing is stored until OK."""
        self._load_values(plugin_settings.DEFAULTS)
        self._restore_hidden_defaults = True

    def show_validation_error(self, message):
        """Tell the user why OK was refused. Tests override this to avoid a modal box."""
        QMessageBox.warning(self, WINDOW_TITLE, message)

    def accept(self):
        error = self.validate()
        if error:
            self.show_validation_error(error)
            return

        values = self.values()
        if self._restore_hidden_defaults:
            values.update({key: plugin_settings.DEFAULTS[key] for key in _HIDDEN_KEYS})
        try:
            # Coerce everything first so an invalid value leaves the settings untouched.
            coerced = {key: plugin_settings.coerce(key, value) for key, value in values.items()}
        except ValueError as e:
            self.show_validation_error(str(e))
            return
        for key, value in coerced.items():
            self.settings.set(key, value)
        self.settings.save()
        super().accept()
