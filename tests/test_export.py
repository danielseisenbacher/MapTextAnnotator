# -*- coding: utf-8 -*-
"""
Tests for the COCO export (coco/annotation_creator.py).

Main scan: EPSG:32633, origin (500000, 5000100), 1 m pixels, 200 x 100 px,
so pixel x = X - 500000 and pixel y = 5000100 - Y. Records are mostly built
directly as dicts in the storage format of schema.py.
"""

import configparser
import copy
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime

import utilities

utilities.start_qgis()

import numpy as np  # noqa: E402
from osgeo import gdal  # noqa: E402
from qgis.core import QgsFeature, QgsGeometry  # noqa: E402
from qgis.PyQt.QtCore import QDateTime  # noqa: E402

creator = utilities.import_plugin_module("coco.annotation_creator")
coco_template = utilities.import_plugin_module("coco.coco_template")
schema = utilities.import_plugin_module("schema")
settings = utilities.import_plugin_module("settings")

GT = (500000.0, 1.0, 0.0, 5000100.0, 0.0, -1.0)
GT2 = (600000.0, 2.0, 0.0, 6000000.0, 0.0, -2.0)  # second scan: 2 m pixels, 300 x 150 px
SINGULAR_GT = (500000.0, 1.0, 1.0, 5000100.0, 1.0, 1.0)  # determinant 0

# Word rectangle in pixel space: x 10..50, y 20..40, stored as in schema.py.
UPPER_PX = [(50, 20), (40, 20), (20, 20), (10, 20)]  # top-right -> top-left
LOWER_PX = [(10, 40), (20, 40), (40, 40), (50, 40)]  # bottom-left -> bottom-right
BOX_PX = [(10, 40), (50, 20)]                        # geo (min, max) corners
OBB_PX = [(10, 40), (50, 40), (50, 20), (10, 20)]
POINTS_PX = [(10, 40), (30, 40), (50, 40), (50, 20), (30, 20), (10, 20)]

STATS = {
    "Mean Altitude": 512.0, "Median Altitude": 511.0, "Max Altitude": 530.0, "Min Altitude": 500.0,
    "Mean Slope": 10.0, "Median Slope": 9.0, "Max Slope": 20.0, "Min Slope": 1.0,
    "Complexity": 0.25, "Contrast": 0.5, "Lat": 45.1, "Lon": 15.2,
}
ALL_STAT_KEYS = {key for keys in schema.STAT_EXPORT_KEYS.values() for key in keys.values()}


def to_geo(px, py, gt=GT):
    return gt[0] + px * gt[1] + py * gt[2], gt[3] + px * gt[4] + py * gt[5]


def multipoint(pixels, gt=GT):
    """MultiPoint WKT (QGIS asWkt style) of pixel positions converted to geo coordinates."""
    return "MultiPoint (" + ",".join("({} {})".format(*to_geo(px, py, gt)) for px, py in pixels) + ")"


def make_record(fid, image, word="Wort", gt=GT, **overrides):
    record = {
        "fid": fid,
        "Word Transcription": word,
        "Reference Image": image,
        "Upper Bezier": multipoint(UPPER_PX, gt),
        "Lower Bezier": multipoint(LOWER_PX, gt),
        "Bounding Box": multipoint(BOX_PX, gt),
        "Oriented Bounding Box": multipoint(OBB_PX, gt),
        "Bounding Points": multipoint(POINTS_PX, gt),
        "Certainty": 2,
    }
    record.update(STATS)
    record.update(overrides)
    return record


def flat(points):
    return [float(c) for p in points for c in p]


class ExportTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.scan = utilities.make_raster(np.zeros((100, 200), dtype=np.uint8), GT)
        cls.scan2 = utilities.make_raster(np.zeros((150, 300), dtype=np.uint8), GT2)
        cls.singular = utilities.make_raster(np.zeros((10, 10), dtype=np.uint8), SINGULAR_GT)
        cls.ungeoreferenced = "/vsimem/mta_test_export_no_gt.tif"
        ds = gdal.GetDriverByName("GTiff").Create(cls.ungeoreferenced, 60, 50, 1)
        ds = None

    @classmethod
    def tearDownClass(cls):
        for path in (cls.scan, cls.scan2, cls.singular, cls.ungeoreferenced):
            utilities.remove_raster(path)

    def build_one(self, record=None, **kwargs):
        coco, skipped = creator.build_annotations([record or make_record(1, self.scan)], **kwargs)
        self.assertEqual(skipped, [])
        self.assertEqual(len(coco["annotations"]), 1)
        return coco, coco["annotations"][0]

    def assertPoints(self, actual, expected_points):
        np.testing.assert_allclose(actual, flat(expected_points), atol=1e-6)

    # --- coordinates --------------------------------------------------------

    def test_pixel_coordinates_follow_geotransform(self):
        coco, ann = self.build_one()
        self.assertPoints(ann["bounding_points"], POINTS_PX)
        self.assertPoints(ann["obbox"], OBB_PX)
        self.assertEqual(coco["images"], [{
            "coco_url": "", "date_captured": "", "file_name": os.path.basename(self.scan), "flickr_url": "",
            "id": 0, "license": 0, "width": 200, "height": 100,
        }])
        self.assertEqual(ann["image_id"], 0)
        self.assertEqual(ann["category_id"], 1)
        self.assertEqual(ann["iscrowd"], 0)

    def test_abcnet_order(self):
        _, ann = self.build_one(bezier_order="abcnet")
        pts = np.array(ann["bezier_pts"]).reshape(8, 2)
        np.testing.assert_allclose(pts[0], (10, 20), atol=1e-6)  # starts top-left
        self.assertTrue(np.all(np.diff(pts[:4, 0]) > 0))         # top: left -> right
        self.assertTrue(np.all(np.diff(pts[4:, 0]) < 0))         # bottom: right -> left
        self.assertPoints(ann["bezier_pts"], UPPER_PX[::-1] + LOWER_PX[::-1])
        self.assertTrue(np.all(pts[:4, 1] < pts[4:, 1]))          # top curve above bottom (y down)

    def test_legacy_order_matches_old_export(self):
        _, ann = self.build_one(bezier_order="legacy")
        # v0.1: upper as stored, then lower reversed
        self.assertPoints(ann["bezier_pts"], UPPER_PX + LOWER_PX[::-1])

    def test_bbox_in_all_formats(self):
        expected = {
            "xyxy": [10, 20, 50, 40],
            "xywh": [10, 20, 40, 20],
            "polygon": [10, 20, 50, 20, 50, 40, 10, 40],
        }
        for fmt, bbox in expected.items():
            with self.subTest(fmt=fmt):
                coco, ann = self.build_one(bbox_format=fmt)
                np.testing.assert_allclose(ann["bbox"], bbox, atol=1e-6)
                self.assertAlmostEqual(ann["area"], 800.0)
                self.assertEqual(coco["info"]["bbox_format"], fmt)

    def test_bbox_falls_back_to_bezier_points(self):
        curved_upper = [(50, 20), (40, 15), (20, 15), (10, 20)]
        for box in (None, "", "garbage"):
            with self.subTest(box=box):
                record = make_record(1, self.scan, **{"Bounding Box": box, "Upper Bezier": multipoint(curved_upper)})
                _, ann = self.build_one(record)
                np.testing.assert_allclose(ann["bbox"], [10, 15, 50, 40], atol=1e-6)
                self.assertAlmostEqual(ann["area"], 1000.0)

    def test_missing_optional_geometries_give_empty_lists(self):
        record = make_record(1, self.scan, **{"Bounding Points": None, "Oriented Bounding Box": "garbage"})
        _, ann = self.build_one(record)
        self.assertEqual(ann["bounding_points"], [])
        self.assertEqual(ann["obbox"], [])

    def test_ungeoreferenced_raster_uses_qgis_convention(self):
        # QGIS shows rasters without geotransform with pixel size (1, -1): Y = -row
        pixels = lambda pts: "MultiPoint (" + ",".join(f"({x} {-y})" for x, y in pts) + ")"
        record = make_record(1, self.ungeoreferenced, **{
            "Upper Bezier": pixels(UPPER_PX), "Lower Bezier": pixels(LOWER_PX),
            "Bounding Box": pixels(BOX_PX), "Bounding Points": None, "Oriented Bounding Box": None,
        })
        coco, ann = self.build_one(record)
        np.testing.assert_allclose(ann["bbox"], [10, 20, 50, 40], atol=1e-6)
        self.assertPoints(ann["bezier_pts"], UPPER_PX[::-1] + LOWER_PX[::-1])
        self.assertEqual((coco["images"][0]["width"], coco["images"][0]["height"]), (60, 50))

    # --- repeated builds, images, ids ---------------------------------------

    def test_repeated_builds_do_not_accumulate(self):
        templates = {name: copy.deepcopy(getattr(coco_template, name))
                     for name in ("coco_template", "images_template", "annotations_template", "character_map")}
        records = [make_record(fid, self.scan) for fid in (1, 2, 3)]

        first, _ = creator.build_annotations(records)
        second, _ = creator.build_annotations(records)

        for coco in (first, second):
            self.assertEqual(len(coco["images"]), 1)
            self.assertEqual([a["id"] for a in coco["annotations"]], [0, 1, 2])
        self.assertIsNot(first, second)
        first["annotations"][0]["bbox"].append(-1)
        first["images"].clear()
        self.assertEqual(len(second["images"]), 1)
        self.assertEqual(len(second["annotations"][0]["bbox"]), 4)
        for name, snapshot in templates.items():
            self.assertEqual(getattr(coco_template, name), snapshot, name)

    def test_multiple_images(self):
        records = [
            make_record(10, self.scan2, gt=GT2),
            make_record(11, self.scan),
            make_record(12, None),  # skipped, must not consume an id
            make_record(13, self.scan2, gt=GT2),
            make_record(14, self.scan),
        ]
        coco, skipped = creator.build_annotations(records)
        self.assertEqual([fid for fid, _ in skipped], [12])
        self.assertEqual([(i["id"], i["file_name"], i["width"], i["height"]) for i in coco["images"]], [
            (0, os.path.basename(self.scan2), 300, 150),
            (1, os.path.basename(self.scan), 200, 100),
        ])
        self.assertEqual([a["id"] for a in coco["annotations"]], [0, 1, 2, 3])
        self.assertEqual([a["image_id"] for a in coco["annotations"]], [0, 1, 0, 1])
        # same pixel geometry in both scans despite different geotransforms
        for ann in coco["annotations"]:
            np.testing.assert_allclose(ann["bbox"], [10, 20, 50, 40], atol=1e-6)
            self.assertPoints(ann["bounding_points"], POINTS_PX)

    def test_no_records(self):
        coco, skipped = creator.build_annotations([])
        self.assertEqual((coco["images"], coco["annotations"], skipped), ([], [], []))
        self.assertEqual(coco["categories"], [{"id": 1, "name": "text", "supercategory": "text"}])

    # --- skipped features ---------------------------------------------------

    def test_skip_reasons(self):
        cases = [
            (1, "no reference image", {"Reference Image": None}),
            (2, "no reference image", {"Reference Image": ""}),
            (3, "no reference image", {"Reference Image": schema.NO_REFERENCE_IMAGE}),
            (4, "can't be opened", {"Reference Image": "/vsimem/mta_test_does_not_exist.tif"}),
            (5, "not invertible", {"Reference Image": self.singular}),
            (6, 'missing "Upper Bezier"', {"Upper Bezier": None}),
            (7, 'missing "Lower Bezier"', {"Lower Bezier": ""}),
            (8, 'invalid "Upper Bezier"', {"Upper Bezier": "not wkt"}),
            (9, '"Lower Bezier" (3 points', {"Lower Bezier": multipoint(LOWER_PX[:3])}),
            (10, '"Upper Bezier" (5 points', {"Upper Bezier": multipoint(UPPER_PX + [(5, 20)])}),
            (11, "empty word", {"Word Transcription": None}),
            (12, "empty word", {"Word Transcription": ""}),
            (13, "empty word", {"Word Transcription": "   "}),
        ]
        records = [make_record(fid, self.scan, **overrides) for fid, _, overrides in cases]
        records.append(make_record(99, self.scan))

        coco, skipped = creator.build_annotations(records)

        self.assertEqual([fid for fid, _ in skipped], [fid for fid, _, _ in cases])
        for (fid, reason), (_, expected, _) in zip(skipped, cases):
            with self.subTest(fid=fid):
                self.assertIsInstance(reason, str)
                self.assertIn(expected, reason)
        self.assertEqual(len(coco["annotations"]), 1)
        self.assertEqual(coco["annotations"][0]["id"], 0)
        self.assertEqual([i["file_name"] for i in coco["images"]], [os.path.basename(self.scan)])

    def test_unknown_options_raise(self):
        records = [make_record(1, self.scan)]
        with self.assertRaises(ValueError):
            creator.build_annotations(records, bbox_format="cxcywh")
        with self.assertRaises(ValueError):
            creator.build_annotations(records, bezier_order="clockwise")
        with self.assertRaises(ValueError):
            creator.build_annotations(records, enabled_stats={"altitude", "humidity"})

    # --- statistics ---------------------------------------------------------

    def test_all_stats_exported_by_default(self):
        _, ann = self.build_one()
        self.assertTrue(ALL_STAT_KEYS <= set(ann))
        self.assertEqual(ann["mean_altitude"], 512.0)
        self.assertEqual(ann["lat"], 45.1)
        self.assertEqual(ann["complexity"], 0.25)

    def test_disabled_stat_groups_are_omitted(self):
        record = make_record(1, self.scan, **{"Contrast": None})
        _, ann = self.build_one(record, enabled_stats=frozenset({"altitude", "contrast"}))
        expected = set(schema.STAT_EXPORT_KEYS["altitude"].values()) | {"contrast"}
        self.assertEqual(ALL_STAT_KEYS & set(ann), expected)
        self.assertIsNone(ann["contrast"])  # enabled but NULL -> null
        self.assertEqual(ann["max_altitude"], 530.0)
        for key in ("mean_slope", "complexity", "lat", "lon"):
            self.assertNotIn(key, ann)
        self.assertNotIn(9999.0, ann.values())

    def test_no_stats(self):
        _, ann = self.build_one(enabled_stats=frozenset())
        self.assertEqual(ALL_STAT_KEYS & set(ann), set())

    def test_missing_stat_fields_and_nan_become_null(self):
        record = make_record(1, self.scan, **{"Mean Slope": float("nan"), "Max Slope": float("inf")})
        del record["Lat"], record["Certainty"]
        coco, ann = self.build_one(record)
        self.assertIsNone(ann["mean_slope"])
        self.assertIsNone(ann["max_slope"])
        self.assertIsNone(ann["lat"])
        self.assertIsNone(ann["certainty"])
        json.dumps(coco, allow_nan=False)

    def test_certainty(self):
        _, ann = self.build_one()
        self.assertEqual(ann["certainty"], 2)

    # --- transcription ------------------------------------------------------

    def rec(self, word):
        return self.build_one(make_record(1, self.scan, word=word))[1]["rec"]

    def test_rec_padding(self):
        rec = self.rec("Wort")
        self.assertEqual(len(rec), coco_template.MAX_TEXT_LENGTH)
        self.assertEqual(rec[:4], [55, 79, 82, 84])
        self.assertEqual(rec[4:], [96] * 46)

    def test_unknown_character(self):
        rec = self.rec("a€b")
        self.assertEqual(rec[:4], [65, 95, 66, 96])
        self.assertEqual(coco_template.UNKNOWN_TOKEN, 95)
        self.assertEqual(coco_template.PAD_TOKEN, 96)

    def test_truncation(self):
        rec = self.rec("x" * 49 + "yz" + "x" * 9)
        self.assertEqual(len(rec), 50)
        self.assertEqual(rec[48:], [88, 89])
        self.assertNotIn(96, rec)

    def test_umlauts(self):
        self.assertEqual(self.rec("äöüÄÖÜß´")[:8], [65, 79, 85, 33, 47, 53, 83, 7])
        self.assertEqual(self.rec("ä")[:2], [65, 96])  # decomposed ä

    # --- info, JSON ---------------------------------------------------------

    def test_info_block(self):
        coco, _ = self.build_one(bbox_format="polygon", bezier_order="legacy")
        info = coco["info"]
        self.assertEqual(set(info), {"description", "version", "date_created", "bbox_format",
                                     "bezier_order", "bezier_pts_order"})
        self.assertEqual(info["description"], "MapText Annotator export")
        self.assertEqual(info["bbox_format"], "polygon")
        self.assertEqual(info["bezier_order"], "legacy")
        self.assertIn("right to left", info["bezier_pts_order"])
        datetime.fromisoformat(info["date_created"])

        parser = configparser.RawConfigParser(strict=False)
        parser.read(os.path.join(utilities.REPO_DIR, "metadata.txt"), encoding="utf-8")
        self.assertEqual(info["version"], parser.get("general", "version").strip())

    def test_every_bezier_order_has_a_description(self):
        self.assertEqual(set(creator.BEZIER_PTS_ORDER), set(settings.BEZIER_ORDERS))

    def test_json_round_trip(self):
        records = [make_record(1, self.scan), make_record(2, self.scan2, gt=GT2, word="Straße")]
        coco, _ = creator.build_annotations(records)
        text = json.dumps(coco, allow_nan=False)
        self.assertEqual(json.loads(text), coco)

    # --- records_from_layer -------------------------------------------------

    def test_records_from_layer(self):
        layer = utilities.make_annotation_layer()
        geometry = QgsGeometry.fromWkt("POLYGON((500010 5000060, 500050 5000060, 500050 5000080, "
                                       "500010 5000080, 500010 5000060))")
        features = []
        for word in ("Wort", None):
            feature = QgsFeature(layer.fields())
            feature.setGeometry(geometry)
            for name, value in make_record(0, self.scan, word=word).items():
                if name != "fid":
                    feature.setAttribute(name, value)
            feature.setAttribute("Create Date", QDateTime.currentDateTime())
            features.append(feature)
        ok, added = layer.dataProvider().addFeatures(features)
        self.assertTrue(ok)

        records = creator.records_from_layer(layer)

        self.assertEqual([r["fid"] for r in records], [f.id() for f in added])
        for record in records:
            self.assertEqual(set(record), {"fid"} | set(schema.FIELDS))
            self.assertIsNone(record["Phrase Transcription"])  # NULL -> None
            self.assertIsNone(record["Word uuid"])
        self.assertIsNone(records[1]["Word Transcription"])

        coco, skipped = creator.build_annotations(records, bbox_format="xywh")
        self.assertEqual(skipped, [(added[1].id(), "empty word transcription")])
        self.assertEqual(len(coco["annotations"]), 1)
        ann = coco["annotations"][0]
        np.testing.assert_allclose(ann["bbox"], [10, 20, 40, 20], atol=1e-6)
        self.assertEqual(ann["certainty"], 2)
        json.dumps(coco, allow_nan=False)


class WriteAnnotationsTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mta-export-test-")
        self.path = os.path.join(self.tmp, "annotations.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_write_and_overwrite(self):
        creator.write_annotations({"word": "Straße", "values": [1, 2.5, None]}, self.path)
        creator.write_annotations({"word": "Wört"}, self.path)
        with open(self.path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Wört", text)  # ensure_ascii=False
        self.assertEqual(json.loads(text), {"word": "Wört"})
        self.assertEqual(os.listdir(self.tmp), ["annotations.json"])

    def test_failed_write_keeps_target(self):
        creator.write_annotations({"ok": True}, self.path)
        with open(self.path, encoding="utf-8") as f:
            before = f.read()

        with self.assertRaises(TypeError):
            creator.write_annotations({"ok": True, "bad": object()}, self.path)

        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(os.listdir(self.tmp), ["annotations.json"])

    def test_failed_first_write_leaves_nothing(self):
        with self.assertRaises(TypeError):
            creator.write_annotations({"bad": {1, 2}}, self.path)
        self.assertEqual(os.listdir(self.tmp), [])

    def test_missing_directory_raises(self):
        with self.assertRaises(OSError):
            creator.write_annotations({}, os.path.join(self.tmp, "missing", "annotations.json"))
        self.assertEqual(os.listdir(self.tmp), [])


if __name__ == "__main__":
    unittest.main()
