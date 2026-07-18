from .coco_template import character_map, coco_template, annotations_template, images_template
from itertools import chain
from PIL import Image
from qgis.core import QgsGeometry
from osgeo import gdal
import os
import copy


def build_annotations(annotation_layer):

    label_count = 0
    image_dict = {}

    for feature in annotation_layer.getFeatures():
        image_path = feature["Reference Image"]

        if image_dict.get(image_path):
            img_id = image_dict[image_path]["img_id"]
        else:
            img_id = max([x["img_id"] for x in image_dict.values()], default=-1) + 1
            image_dict[image_path] = {"img_id": img_id, "features": []}

        # Build annotation entry
        annotation_entry = copy.deepcopy(annotations_template)
        annotation_entry["image_id"] = img_id       # the id of the photo
        annotation_entry["id"] = label_count        # the id of the label

        # enter bezier coordinates translated from geolocated coordinates to image coordinates
        annotation_entry["bezier_pts"] = []
        upper_px = translate_to_img_coords(feature["Upper Bezier"], image_path)
        lower_px = translate_to_img_coords(feature["Lower Bezier"], image_path)
        lower_px = lower_px[::-1]  # clockwise
        annotation_entry["bezier_pts"].extend([c for pt in upper_px for c in pt])
        annotation_entry["bezier_pts"].extend([c for pt in lower_px for c in pt])

        # Text Transcription
        annotation_entry["rec"] = []
        MAX_LEN = 50
        NULL_CHAR = 96  # padding token
        rec = [character_map.get(letter, 96) for letter in feature["Word Transcription"]]
        rec = rec[:MAX_LEN]
        rec = rec + [NULL_CHAR] * (MAX_LEN - len(rec))
        annotation_entry["rec"] = rec

        # Geometry
        annotation_entry["bbox"] =  list(chain.from_iterable(translate_to_img_coords(feature["Bounding Box"], image_path)))
        annotation_entry["obbox"] = list(chain.from_iterable(translate_to_img_coords(feature["Oriented Bounding Box"], image_path)))

        # Geographic Stats
        annotation_entry["mean_altitude"] = feature["Mean Altitude"]            # altitude stats
        annotation_entry["median_altitude"] = feature["Median Altitude"]
        annotation_entry["max_altitude"] = feature["Max Altitude"]
        annotation_entry["min_altitude"] = feature["Min Altitude"]

        annotation_entry["mean_slope"] = feature["Mean Slope"]               # slope stats
        annotation_entry["median_slope"] = feature["Median Slope"]
        annotation_entry["max_slope"] = feature["Max Slope"]
        annotation_entry["min_slope"] = feature["Min Slope"]

        # Visual Stats
        annotation_entry["complexity"] = feature["Complexity"]
        annotation_entry["contrast"] = feature["Contrast"]

        label_count += 1       # increase label count after feature

        image_dict[image_path]["features"].append(annotation_entry)


    # return coco dict
    return insert_into_coco_template(image_dict)


def insert_into_coco_template(image_dict):
    for image_path, image_data in image_dict.items():
        image_entry = copy.deepcopy(images_template)        # copy template to fill

        image_entry["file_name"] = os.path.basename(image_path)         # file name with extension

        img = Image.open(image_path)                                    # image w and h
        width, height = img.size
        image_entry["width"] = width
        image_entry["height"] = height

        image_entry["id"] = image_data["img_id"]                        # read image id from image data

        # extend coco template
        coco_template["images"].append(image_entry)
        coco_template["annotations"].extend(image_data["features"])

    return coco_template


_geotransform_cache = {}


def get_inverse_geotransform(image_path):
    """Opens the raster once per image_path and caches its inverse geotransform."""
    if image_path not in _geotransform_cache:
        ds = gdal.Open(image_path)
        if ds is None:
            raise ValueError(f"Could not open raster for georeferencing: {image_path}")
        gt = ds.GetGeoTransform()
        inv_gt = gdal.InvGeoTransform(gt)
        if inv_gt is None:
            raise ValueError(f"Geotransform is not invertible for: {image_path}")
        _geotransform_cache[image_path] = inv_gt
    return _geotransform_cache[image_path]


def translate_to_img_coords(coord, image_path):
    """
    Converts real-world coordinates (already in the raster's projected CRS,
    e.g. UTM metres) into pixel coordinates of the referenced image.

    `coord` is expected to be a WKT string (as now stored by insert_vertices,
    insert_bboxes, and insert_beziers) representing a Point or MultiPoint.

    Returns a list of (px, py) tuples, one per point found in the WKT.
    """
    if not coord:
        return []

    geom = QgsGeometry.fromWkt(coord)
    if geom.isEmpty():
        raise ValueError(f"Could not parse WKT: {coord!r}")

    inv_gt = get_inverse_geotransform(image_path)

    pixel_points = []
    for vertex in geom.vertices():
        px, py = gdal.ApplyGeoTransform(inv_gt, vertex.x(), vertex.y())
        pixel_points.append((px, py))

    return pixel_points























