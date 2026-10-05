# -*- coding: utf-8 -*-
"""
Shared test helpers. Import this module before anything from qgis: it points
QGIS at a throwaway profile directory so tests never touch the real user profile.

Run the suite with the system Python that ships QGIS:

    /usr/bin/python3 -B -m unittest discover -s tests -v
"""

import atexit
import importlib
import importlib.util
import os
import shutil
import sys
import tempfile
import uuid
import warnings

warnings.filterwarnings("ignore", message="Neither gdal.UseExceptions", category=FutureWarning)

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE_NAME = "maptextannotator"

_CONFIG_DIR = tempfile.mkdtemp(prefix="mta-test-profile-")
atexit.register(shutil.rmtree, _CONFIG_DIR, True)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QGIS_CUSTOM_CONFIG_PATH"] = _CONFIG_DIR

_QGIS_APP = None
_PROCESSING_READY = False


def load_plugin_package():
    """Import the plugin under the fixed package name 'maptextannotator',
    independent of the repository folder name."""
    if PACKAGE_NAME in sys.modules:
        return sys.modules[PACKAGE_NAME]
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        os.path.join(REPO_DIR, "__init__.py"),
        submodule_search_locations=[REPO_DIR],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)
    return module


def import_plugin_module(name):
    """Import a plugin submodule, e.g. import_plugin_module("core.geometry")."""
    load_plugin_package()
    return importlib.import_module(f"{PACKAGE_NAME}.{name}")


def start_qgis():
    """Start (once) a headless QgsApplication and return it."""
    global _QGIS_APP
    if _QGIS_APP is None:
        from qgis.testing import start_app
        # cleanup=False: exitQgis() at exit tears down GDAL while GDAL datasets
        # may still be alive, which segfaults the interpreter on shutdown.
        _QGIS_APP = start_app(cleanup=False)
    return _QGIS_APP


def init_processing():
    """Initialize the processing framework (native, GDAL and, if installed, GRASS providers)."""
    global _PROCESSING_READY
    start_qgis()
    if _PROCESSING_READY:
        return
    from qgis.core import QgsApplication
    plugins_dir = os.path.join(QgsApplication.pkgDataPath(), "python", "plugins")
    if plugins_dir not in sys.path:
        sys.path.append(plugins_dir)
    from processing.core.Processing import Processing
    Processing.initialize()
    if QgsApplication.processingRegistry().providerById("native") is None:
        from qgis.analysis import QgsNativeAlgorithms
        QgsApplication.processingRegistry().addProvider(QgsNativeAlgorithms())
    _PROCESSING_READY = True


def make_raster(array, geotransform, epsg=32633, nodata=None, path=None):
    """Write a GeoTIFF from a 2D (rows, cols) or 3D (bands, rows, cols) numpy
    array and return its path. Defaults to an in-memory /vsimem/ path; pass a
    real path for code that needs a file on disk (e.g. GRASS)."""
    import numpy as np
    from osgeo import gdal, gdal_array, osr

    data = np.asarray(array)
    if data.ndim == 2:
        data = data[np.newaxis, ...]
    bands, rows, cols = data.shape
    if path is None:
        path = f"/vsimem/mta_test_{uuid.uuid4().hex}.tif"

    ds = gdal.GetDriverByName("GTiff").Create(
        path, cols, rows, bands, gdal_array.NumericTypeCodeToGDALTypeCode(data.dtype)
    )
    ds.SetGeoTransform(geotransform)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    ds.SetProjection(srs.ExportToWkt())
    for i in range(bands):
        band = ds.GetRasterBand(i + 1)
        band.WriteArray(data[i])
        if nodata is not None:
            band.SetNoDataValue(nodata)
    ds.FlushCache()
    ds = None
    return path


def remove_raster(path):
    from osgeo import gdal
    if path.startswith("/vsimem/"):
        gdal.Unlink(path)
    elif os.path.exists(path):
        os.remove(path)


def make_annotation_layer(crs="EPSG:32633", name="Annotation Layer", fields=None):
    """Create a memory polygon layer with the annotation schema (schema.FIELDS by default)."""
    start_qgis()
    from qgis.core import QgsCoordinateReferenceSystem, QgsField, QgsVectorLayer
    schema = import_plugin_module("schema")
    layer = QgsVectorLayer("Polygon", name, "memory")
    layer.setCrs(QgsCoordinateReferenceSystem(crs))
    field_types = schema.FIELDS if fields is None else fields
    layer.dataProvider().addAttributes([QgsField(n, t) for n, t in field_types.items()])
    layer.updateFields()
    return layer


def temp_settings_store():
    """Return (QgsSettings backed by a temporary ini file, path) for settings tests."""
    start_qgis()
    from qgis.core import QgsSettings
    from qgis.PyQt.QtCore import QSettings
    path = os.path.join(_CONFIG_DIR, f"settings_{uuid.uuid4().hex}.ini")
    return QgsSettings(path, QSettings.IniFormat), path
