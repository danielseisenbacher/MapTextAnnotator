#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Overlay a MapText Annotator export (COCO-style JSON) on its image.

    python3 tools/draw_annotations.py IMAGE ANNOTATIONS.json [--image-id N] [--out FILE.png]

For every annotation of the image it draws the top (green) and bottom (red)
cubic bezier curves with their dashed control polygons, a square marker on the
first control point of each curve, the axis-aligned bbox (cyan) and the label
"#id: text" decoded from `rec`. The bbox layout and the bezier point order are
read from the file's `info` block; files without them (v0.1 exports) are read
as "xyxy" / "legacy".

Needs numpy, matplotlib and Pillow (GDAL, if installed, is the fallback image
reader). No QGIS required.
"""

import argparse
import json
import os
import sys
import warnings

import matplotlib
import numpy as np
from matplotlib import patches
from matplotlib.lines import Line2D
from matplotlib.path import Path

TOP_COLOR = "lime"
BOTTOM_COLOR = "red"
BBOX_COLOR = "cyan"

BBOX_FORMATS = ("xyxy", "xywh", "polygon")
BEZIER_ORDERS = ("abcnet", "legacy")
# Defaults for files written before the info block recorded the formats.
LEGACY_BBOX_FORMAT = "xyxy"
LEGACY_BEZIER_ORDER = "legacy"

REC_UNKNOWN = 95
REC_PADDING = 96

CUBIC_CODES = [Path.MOVETO, Path.CURVE4, Path.CURVE4, Path.CURVE4]


def decode_rec(rec):
    """Text of a `rec` list: 0-94 -> printable ASCII, 95 (or anything else) -> '?', 96 ends it."""
    chars = []
    for code in rec:
        code = int(code)
        if code == REC_PADDING:
            break
        chars.append(chr(code + 32) if 0 <= code <= 94 else "?")
    return "".join(chars)


def split_bezier(bezier_pts):
    """(top, bottom) curves as lists of 4 (x, y) control points, in file order.
    Both orders store the top curve first; they differ in direction:
    abcnet: top left -> right, bottom right -> left;
    legacy: both curves right -> left."""
    if len(bezier_pts) != 16:
        raise ValueError(f"expected 16 bezier values, got {len(bezier_pts)}")
    points = list(zip(bezier_pts[0::2], bezier_pts[1::2]))
    return points[:4], points[4:]


def bbox_patch(bbox, bbox_format):
    """Matplotlib patch for an exported bbox (pixel coordinates, y down)."""
    style = dict(fill=False, edgecolor=BBOX_COLOR, linewidth=1)
    if bbox_format == "polygon":
        if len(bbox) != 8:
            raise ValueError(f"expected 8 polygon bbox values, got {len(bbox)}")
        return patches.Polygon(np.reshape(bbox, (4, 2)), closed=True, **style)
    if len(bbox) != 4:
        raise ValueError(f"expected 4 bbox values, got {len(bbox)}")
    if bbox_format == "xywh":
        x, y, w, h = bbox
    else:
        # xyxy; sorted so v0.1 exports with swapped y values still draw correctly
        x0, x1 = sorted((bbox[0], bbox[2]))
        y0, y1 = sorted((bbox[1], bbox[3]))
        x, y, w, h = x0, y0, x1 - x0, y1 - y0
    return patches.Rectangle((x, y), w, h, **style)


def select_image(data, image_path, image_id=None):
    """The `images` entry to draw: by id if given, else by file name, else the first one."""
    images = data.get("images") or []
    if not images:
        raise LookupError("the JSON contains no images")
    if image_id is not None:
        for entry in images:
            if entry.get("id") == image_id:
                return entry
        ids = sorted(entry.get("id") for entry in images)
        raise LookupError(f"no image with id {image_id}; available ids: {ids}")
    name = os.path.basename(image_path)
    for entry in images:
        if entry.get("file_name") == name:
            return entry
    entry = images[0]
    print(f"{name} is not listed in the JSON, using the first image: "
          f"{entry.get('file_name')} (id {entry.get('id')})")
    return entry


def _read_with_gdal(path):
    try:
        from osgeo import gdal
    except ImportError:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)  # GDAL 4 exception-mode notice
        dataset = gdal.Open(path)
    if dataset is None:
        return None
    bands = [1, 2, 3] if dataset.RasterCount >= 3 else [1]
    array = np.dstack([dataset.GetRasterBand(b).ReadAsArray() for b in bands])
    return array[..., 0] if len(bands) == 1 else array


def load_image(path):
    """The image as an array imshow can display (uint8, or float scaled to 0..1)."""
    if not os.path.isfile(path):
        raise OSError(f"image not found: {path}")
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None  # map scans are often larger than Pillow's safety limit
        with Image.open(path) as img:
            if img.mode not in ("RGB", "RGBA", "L", "F") and not img.mode.startswith("I"):
                img = img.convert("RGB")
            array = np.asarray(img)
    except Exception as error:  # Pillow can't read every GeoTIFF layout
        array = _read_with_gdal(path)
        if array is None:
            raise OSError(f"cannot read image {path}: {error}") from error

    if array.dtype == np.uint8:
        return array
    array = array.astype(np.float64)
    finite = array[np.isfinite(array)]
    low, high = (finite.min(), finite.max()) if finite.size else (0.0, 1.0)
    return np.clip((array - low) / ((high - low) or 1.0), 0.0, 1.0)


def draw_annotation(ax, ann, bbox_format, bezier_order):
    top, bottom = split_bezier(ann["bezier_pts"])
    for curve, color in ((top, TOP_COLOR), (bottom, BOTTOM_COLOR)):
        ax.add_patch(patches.PathPatch(Path(curve, CUBIC_CODES), facecolor="none",
                                       edgecolor=color, linewidth=1.5))
        xs, ys = zip(*curve)
        ax.plot(xs, ys, "--", color=color, linewidth=0.7, alpha=0.6)
        ax.plot(xs[1:], ys[1:], "o", color=color, markersize=4)
        ax.plot(xs[0], ys[0], "s", color=color, markersize=8, markeredgecolor="white")

    ax.add_patch(bbox_patch(ann["bbox"], bbox_format))

    # Label at the start of the word: the left end of the top curve.
    anchor = top[0] if bezier_order == "abcnet" else top[-1]
    ax.annotate(f"#{ann.get('id')}: {decode_rec(ann.get('rec', []))}", anchor,
                xytext=(0, 6), textcoords="offset points", va="bottom",
                color="yellow", fontsize=8,
                bbox=dict(facecolor="black", alpha=0.7, edgecolor="none", pad=1))


def draw(image_path, json_path, image_id=None, out=None):
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    info = data.get("info") or {}
    bbox_format = info.get("bbox_format") or LEGACY_BBOX_FORMAT
    bezier_order = info.get("bezier_order") or LEGACY_BEZIER_ORDER
    if bbox_format not in BBOX_FORMATS:
        raise ValueError(f"unknown bbox_format {bbox_format!r}, expected one of {BBOX_FORMATS}")
    if bezier_order not in BEZIER_ORDERS:
        raise ValueError(f"unknown bezier_order {bezier_order!r}, expected one of {BEZIER_ORDERS}")

    image = load_image(image_path)
    entry = select_image(data, image_path, image_id)
    anns = [a for a in data.get("annotations", []) if a.get("image_id") == entry.get("id")]
    height, width = image.shape[:2]
    if (entry.get("width"), entry.get("height")) != (width, height):
        print(f"Warning: the JSON lists {entry.get('width')} x {entry.get('height')} px for "
              f"{entry.get('file_name')}, the image is {width} x {height} px; the overlay will be misaligned.")
    print(f"Image id {entry.get('id')} ({entry.get('file_name')}): annotations: {len(anns)}, "
          f"bbox {bbox_format}, bezier order {bezier_order}")

    import matplotlib.pyplot as plt

    fig_width = 16
    fig_height = min(32, max(4, fig_width * height / width))
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    # extent puts the image's top-left corner at (0, 0), like the exported pixel coordinates
    ax.imshow(image, extent=(0, width, height, 0), cmap="gray" if image.ndim == 2 else None)

    drawn = 0
    for ann in anns:
        try:
            draw_annotation(ax, ann, bbox_format, bezier_order)
            drawn += 1
        except (KeyError, TypeError, ValueError) as error:
            print(f"Skipping annotation {ann.get('id')}: {error}")

    ax.set_xlim(0, width)
    ax.set_ylim(height, 0)
    ax.set_title(f"{entry.get('file_name')} (image id {entry.get('id')}): annotations: {drawn}, "
                 f"bbox {bbox_format}, bezier order {bezier_order}")
    ax.legend(handles=[
        Line2D([], [], color=TOP_COLOR, label="top curve"),
        Line2D([], [], color=BOTTOM_COLOR, label="bottom curve"),
        Line2D([], [], color=BBOX_COLOR, label="bbox"),
        Line2D([], [], color="gray", marker="s", linestyle="none", markeredgecolor="white",
               label="first control point"),
    ], loc="upper right", fontsize=8)
    fig.tight_layout()

    if out:
        fig.savefig(out, dpi=min(300, max(100, width / fig_width)))
        plt.close(fig)
        print(f"Saved {out}")
    else:
        plt.show()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Overlay a MapText Annotator COCO-style export on its image.")
    parser.add_argument("image", help="the reference image the annotations belong to")
    parser.add_argument("json", help="the exported annotations JSON")
    parser.add_argument("--image-id", type=int,
                        help="image id in the JSON (default: match the image's file name, else the first image)")
    parser.add_argument("--out", help="save the figure to this PNG file instead of opening a window")
    args = parser.parse_args(argv)

    if args.out:
        matplotlib.use("Agg")
    try:
        draw(args.image, args.json, args.image_id, args.out)
    except (OSError, LookupError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
