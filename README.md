# MapText Annotator

A QGIS plugin for annotating text on scanned maps. You draw word polygons and transcribe them. The plugin stores bezier curves and bounding boxes for each word, plus optional geographic and visual statistics. The annotations export to a COCO-style JSON that text spotting models such as ABCNet or DeepSolo can read. The statistics let you check how the terrain and the image content around a label relate to text spotting performance.

- Draw each word as a polygon and enter its transcription and a certainty level.
- Link consecutive words into phrases (multi-word place names).
- Each label gets two cubic bezier curves (top and bottom edge), an axis-aligned and an oriented bounding box, and the polygon vertices.
- Optional per-label statistics:
  - altitude and slope, from a DEM and a slope raster you supply
  - edge complexity, via GRASS `i.zc`
  - contrast
  - centroid (Lat/Lon, WGS 84)
- Export to COCO-style JSON in the pixel coordinates of the map image. The bbox format and bezier point order are selectable.

## Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Drawing rules](#drawing-rules)
- [When statistics are computed](#when-statistics-are-computed)
- [Settings](#settings)
- [Attribute schema](#attribute-schema)
- [Export format](#export-format)
- [Metric definitions](#metric-definitions)
- [Visualising an export](#visualising-an-export)
- [Development and tests](#development-and-tests)
- [Troubleshooting](#troubleshooting)
- [License and links](#license-and-links)

## Requirements

- QGIS 3.34 or newer. numpy and GDAL ship with QGIS.
- A georeferenced raster map: a local file GDAL can read, such as a GeoTIFF.
- Optional: a DEM raster for altitude and a slope raster for slope. The plugin does not derive slope from the DEM. You can create a slope raster with *Raster > Analysis > Slope*.
- Optional: the **GRASS GIS provider** with GRASS installed. It is needed only for edge complexity.
- Optional, for `tools/draw_annotations.py`: matplotlib and Pillow.

## Installation

Put the plugin folder into the `python/plugins` directory of your QGIS profile:

| OS | Plugin directory (default profile) |
|---|---|
| Linux | `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/` |
| Windows | `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\` |
| macOS | `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/` |

If your profile is elsewhere, *Settings > User Profiles > Open Active Profile Folder* opens it.

For development, clone the repository and symlink it into the plugin directory:

```bash
git clone https://github.com/danielseisenbacher/MapTextAnnotator.git
ln -s "$PWD/MapTextAnnotator" ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/MapTextAnnotator
```

Alternatively, copy the folder there, or build a zip and use *Plugins > Manage and Install Plugins > Install from ZIP*:

```bash
git archive --prefix=MapTextAnnotator/ -o MapTextAnnotator.zip HEAD
```

Then restart QGIS and enable **MapText Annotator** under *Plugins > Manage and Install Plugins > Installed*.

`resources.py` (the compiled icon and example image) is checked in. Rebuild it only if you change `icon.png` or `example.png`:

```bash
pyrcc5 resources.qrc -o resources.py
```

## Quick start

1. **Load the map.** Open the map raster with *Layer > Add Layer > Add Raster Layer*. Optionally add a DEM and a slope raster.
2. **Open the dock.** Click the **Annotate MapText** toolbar icon, or use *Plugins > MapText Annotator > Annotate MapText*.
3. **Create the annotation layer.** Click **Generate Layer**. This creates a polygon layer named "Annotation Layer" in the project CRS, with all attribute fields and the annotation style. Make sure it is selected under **Annotation Polygon Layer**.
   - The layer is a **temporary scratch layer**. Its contents are lost when QGIS closes.
   - To keep the annotations, save the layer to disk: right-click it and choose *Make Permanent…*, or *Export > Save Features As…*. Use GeoPackage (see [Troubleshooting](#troubleshooting)).
4. **Optional: choose the DEM and slope layers.** Select them under **DEM Layer** and **Slope Layer**. Both can stay empty. Altitude and slope are then not computed, and the plugin warns once if the statistic is enabled. If you don't need them, turn the statistics off in the settings; the pickers are then hidden.
5. **Draw.** Toggle editing on the annotation layer and use *Add Polygon Feature* to draw a word, following the [drawing rules](#drawing-rules). In the attribute form that opens:
   - **Word Transcription**: the text of the word.
   - **Link to previous Word**: tick it if this word continues the phrase of the previously drawn word.
   - **Certainty**: how confident you are in the transcription.

   Statistics are computed as soon as the feature is added.
6. **Save the edits** (*Save Layer Edits*).
7. **Export.** Click **Export Annotations** and choose a `.json` file. The plugin remembers the last export folder.

The dock shows the word, the phrase and the headline statistics of the selected or last created annotation. Below them are the dataset counts: labels, phrases and distinct reference images.

## Drawing rules

The bezier curves are derived from the polygon. This only works if the polygon follows these rules, which the instruction panel in the dock also shows:

1. **Start at the bottom-left corner of the word**, measured along its baseline. For rotated or curved labels, this is the bottom corner where the text starts.
2. **Draw the vertices counter-clockwise**: along the bottom edge to the right, then back along the top edge. If you draw clockwise from the bottom-left corner, the plugin corrects the order automatically.
3. **Use the same number of vertices on the top and bottom edges.** Each edge needs at least 2 vertices, so a polygon has at least 4 vertices and always an even count. For curved text, add more vertices to both edges; with 4 or more per edge, the curve is a least-squares fit.

If a polygon breaks these rules, the label is kept but its bezier fields stay empty and a warning is shown. The export then skips that label. To fix it, redraw the polygon or edit its vertices; the beziers are recomputed after the edit.

## When statistics are computed

- **Automatically**, when you add a polygon or change its geometry (vertex tool, move, reshape) while the layer is in edit mode.
- **Not** on undo or redo, or when you save edits.
- **Not** when you only select a feature. The dock then shows the values already stored in the feature.
- **On demand**, with the **Recompute Selected** button. The layer must be in edit mode. Use it after changing settings, the DEM or slope layer, or the map raster. Existing annotations keep their stored values until you recompute them.

Values are written into the layer's edit buffer, so save your edits to keep them. Repeated problems, such as a missing DEM, are reported once per kind of warning rather than once per feature. The warnings appear again after you change the settings or layers.

**Reference image.** Pixel coordinates, edge complexity and contrast are computed on the *reference image*: the top-most visible raster in the Layers panel that lies under the polygon and is a local file read by GDAL. The following are never used as the reference image:

- the layers selected as DEM or slope layer
- web, XYZ and WMS layers, because they have no local file

The reference image's file path is stored in the **Reference Image** field. If no suitable raster is found, the field is `None found`.

## Settings

Open the settings with the **Settings** button in the dock, or with *Plugins > MapText Annotator > Settings…*.

Settings are stored in your QGIS user profile under the `MaptextAnnotator/` prefix, so they persist across sessions and projects. The layer choices (DEM layer, slope layer, annotation layer) are stored per project and saved with the `.qgz`/`.qgs` file.

| Setting (dialog) | Key | Default | Effect |
|---|---|---|---|
| Statistics > Altitude | `stats/altitude` | on | Mean/median/min/max altitude from the DEM layer. When off, the DEM picker and the *Mean Altitude* row are hidden. |
| Statistics > Slope | `stats/slope` | on | Same as altitude, using the slope layer. |
| Statistics > Edge complexity | `stats/edge_complexity` | on | Edge density via GRASS `i.zc`. Greyed out if `i.zc` is not available. |
| Statistics > Contrast | `stats/contrast` | on | Robust contrast inside the polygon. |
| Statistics > Centroid | `stats/centroid` | on | Polygon centroid as Lat/Lon in EPSG:4326. |
| Edge complexity > Filter width | `edge/width` | `3` | `width` of `i.zc`: size of the Gaussian filter. Odd values are recommended. |
| Edge complexity > Threshold | `edge/threshold` | `5.0` | `threshold` of `i.zc`: sensitivity of the zero-crossing detection. |
| (no widget) | `edge/buffer_ratio` | `0.1` | The `i.zc` window is the polygon buffered by `buffer_ratio * sqrt(area)`. You can change it in *Settings > Options > Advanced*. *Restore Defaults* resets it. |
| Contrast > Lower percentile | `contrast/lower_pct` | `5.0` | Lower percentile of the contrast range. Must be below the upper percentile. |
| Contrast > Upper percentile | `contrast/upper_pct` | `95.0` | Upper percentile of the contrast range. |
| Export > Bounding box format | `export/bbox_format` | `xyxy` | `xyxy`, `xywh` (COCO) or `polygon`. See [Export format](#export-format). |
| Export > Bezier point order | `export/bezier_order` | `abcnet` | `abcnet` or `legacy` (the v0.1 order). |
| (no widget) | `export/last_dir` | empty | Last export folder, remembered automatically. |
| Interface > Show drawing instructions | `ui/show_instructions` | on | Shows the instruction panel in the dock. |

Disabled statistics are neither computed nor exported: their JSON keys are left out. Their dock rows are hidden. Values already stored in the layer are kept.

The dialog also has **Restore Defaults**, which is applied on OK.

## Attribute schema

**Generate Layer** creates the fields below.

- A polygon layer appears in the **Annotation Polygon Layer** list if it has the *core* fields with matching types. Core fields are marked "core" in the table.
- The statistic fields are optional. A layer without them is still annotated, and the missing values are skipped.

Storage conventions:

- All WKT fields are `MULTIPOINT` geometries in the CRS of the reference raster, not the layer CRS.
- The bezier fields keep the drawing order. The order is converted for the chosen export format only at export time.

| Field | Type | Content |
|---|---|---|
| Word Transcription | String | Transcription of the word. Core. |
| Phrase Transcription | String | Legacy, never written. The phrase is rebuilt on the fly (see "Link to previous Word"). |
| Reference Image | String | File path of the reference raster, or `None found`. Core. |
| Lat, Lon | Double | Polygon centroid in EPSG:4326 (degrees). Statistic group *centroid*. |
| Bounding Points | String | WKT: the polygon vertices. Core. |
| Bounding Box | String | WKT: 2 corners of the axis-aligned box (min, max). Core. |
| Oriented Bounding Box | String | WKT: 4 corners of the oriented minimum bounding box. Core. |
| Upper Bezier | String | WKT: 4 cubic control points of the top edge, top-right to top-left. Core. |
| Lower Bezier | String | WKT: 4 cubic control points of the bottom edge, bottom-left to bottom-right. Core. |
| Mean / Median / Max / Min Altitude | Double | DEM statistics. Statistic group *altitude*. |
| Mean / Median / Max / Min Slope | Double | Slope raster statistics. Statistic group *slope*. |
| Complexity | Double | Edge complexity, 0 to 1. Statistic group *edge_complexity*. |
| Contrast | Double | Contrast, 0 to 1 for 8- and 16-bit rasters. Statistic group *contrast*. |
| Word uuid | String | Unique id, set to `uuid()` when the feature is created. |
| Link to previous Word | Bool | Checked: the word continues the phrase of the previous word. Core. |
| Create Date | DateTime | Set to `now()` when the feature is created. Core. |
| Certainty | Int | Value map: `0` illegible, `1` low confidence, `2` medium confidence, `3` high confidence (default). |

**Phrases.** Words are ordered by *Create Date*, then feature id. A word with *Link to previous Word* checked continues the phrase of the word before it. To annotate a multi-word name, draw its words in reading order and tick the box for every word after the first.

The default values of *Word uuid*, *Create Date* and *Certainty*, and the Certainty value map, come from `annotator_style.qml`. That style is applied by **Generate Layer**.

## Export format

**Export Annotations** writes one JSON file for the current annotation layer. The file contains all features, including unsaved edits. Coordinates are in **pixels of each feature's reference image**:

- The origin is the top-left corner of the image. x points right, y points down.
- Values are floats.

Skipped features. A feature is skipped if any of the conditions below applies. After the export, the message bar shows how many were skipped and lists the first three with their feature id and reason:

- it has no reference image, or the image cannot be opened
- its Upper Bezier or Lower Bezier is missing or invalid (the polygon broke the drawing rules)
- its word transcription is empty

### Top-level structure

| Key | Content |
|---|---|
| `licenses` | Always an empty list. |
| `info` | Export metadata (see below). |
| `categories` | A single category, `{"id": 1, "name": "text", "supercategory": "text"}`. |
| `images` | One entry per distinct reference image. Image ids start at 0, in order of first appearance. |
| `annotations` | One entry per exported feature. Annotation ids are sequential from 0. |

The `info` block contains:

| Key | Content |
|---|---|
| `description` | Always `"MapText Annotator export"`. |
| `version` | Plugin version that wrote the file. |
| `date_created` | ISO 8601 timestamp. |
| `bbox_format` | The bbox format used. |
| `bezier_order` | The bezier point order used. |
| `bezier_pts_order` | A plain-text description of `bezier_pts`. |

Each `images` entry has:

- `file_name`: the base name of the reference image
- `width` and `height` in pixels
- `id`
- the empty COCO placeholders `coco_url`, `date_captured`, `flickr_url` and `license`

### Annotation keys

| Key | Content |
|---|---|
| `id`, `image_id`, `category_id`, `iscrowd` | Ids. `category_id` is always 1 and `iscrowd` is always 0. |
| `bbox` | Axis-aligned box. The layout depends on `bbox_format`:<br>`xyxy` (default): `[x_min, y_min, x_max, y_max]`<br>`xywh` (COCO): `[x_min, y_min, width, height]`<br>`polygon`: `[x_min, y_min, x_max, y_min, x_max, y_max, x_min, y_max]`, the 4 corners clockwise from the top-left |
| `area` | Area of the axis-aligned box in px². |
| `obbox` | Oriented minimum bounding box: 4 corners as `[x1, y1, ..., x4, y4]`. |
| `bounding_points` | Polygon vertices as `[x1, y1, x2, y2, ...]`. |
| `bezier_pts` | 16 values: 4 control points of the top curve, then 4 of the bottom curve. The direction depends on `bezier_order`:<br>`abcnet` (default): top curve left to right, bottom curve right to left (ABCNet and DeepSolo convention)<br>`legacy`: both curves right to left (the v0.1 order) |
| `rec` | The transcription as exactly 50 integers:<br>`0`–`94`: the printable ASCII characters from space (32) to `~` (126), i.e. character code − 32<br>`95`: an unknown character<br>`96`: padding<br>German umlauts map to their base letter (`ä` → `a`, `Ö` → `O`), `ß` maps to `s` and `´` to `'`. Words longer than 50 characters are truncated. |
| `certainty` | The Certainty value (0–3), or `null`. |
| Statistic keys | Only for enabled statistic groups. Values are `null` if not computed.<br>altitude: `mean_altitude`, `median_altitude`, `max_altitude`, `min_altitude`<br>slope: `mean_slope`, `median_slope`, `max_slope`, `min_slope`<br>edge complexity: `complexity`<br>contrast: `contrast`<br>centroid: `lat`, `lon` |

### Example

This example uses `xyxy` and `abcnet` for the word "Wien", drawn as a 4-vertex rectangle. The `bezier_pts_order` text is shortened.

```json
{
  "licenses": [],
  "info": {
    "description": "MapText Annotator export",
    "version": "0.2.0",
    "date_created": "2026-10-05T21:30:00+02:00",
    "bbox_format": "xyxy",
    "bezier_order": "abcnet",
    "bezier_pts_order": "16 floats, pixel coordinates (y down): ..."
  },
  "categories": [{"id": 1, "name": "text", "supercategory": "text"}],
  "images": [
    {"coco_url": "", "date_captured": "", "file_name": "sheet_4751.tif", "flickr_url": "",
     "id": 0, "license": 0, "width": 8000, "height": 6000}
  ],
  "annotations": [
    {
      "id": 0, "image_id": 0, "category_id": 1, "iscrowd": 0,
      "area": 7896.0,
      "bbox": [1204.0, 880.0, 1392.0, 922.0],
      "bezier_pts": [1204.0, 880.0, 1266.67, 880.0, 1329.33, 880.0, 1392.0, 880.0,
                     1392.0, 922.0, 1329.33, 922.0, 1266.67, 922.0, 1204.0, 922.0],
      "rec": [55, 73, 69, 78, 96, 96, 96, 96, 96, 96, 96, 96, 96, 96, 96, 96, 96,
              96, 96, 96, 96, 96, 96, 96, 96, 96, 96, 96, 96, 96, 96, 96, 96, 96,
              96, 96, 96, 96, 96, 96, 96, 96, 96, 96, 96, 96, 96, 96, 96, 96],
      "bounding_points": [1204.0, 922.0, 1392.0, 922.0, 1392.0, 880.0, 1204.0, 880.0],
      "obbox": [1204.0, 880.0, 1392.0, 880.0, 1392.0, 922.0, 1204.0, 922.0],
      "certainty": 3,
      "mean_altitude": 171.4, "median_altitude": 171.0, "max_altitude": 176.2, "min_altitude": 168.9,
      "mean_slope": 2.1, "median_slope": 1.9, "max_slope": 5.4, "min_slope": 0.3,
      "complexity": 0.18,
      "contrast": 0.62,
      "lat": 48.2082, "lon": 16.3738
    }
  ]
}
```

## Metric definitions

All rasters are sampled with the polygon transformed into the raster's CRS.

**Altitude / slope**
- The mean, median, min and max of the DEM or slope raster (band 1) over the pixels whose centres lie inside the polygon. Nodata pixels are excluded.
- If the polygon is smaller than a pixel and no centre falls inside it, every pixel it touches is used instead.
- The units are those of the raster: metres for most DEMs, and degrees or percent for slope, depending on how the slope raster was made.

**Edge complexity** (`Complexity`): the share of edge pixels inside the polygon, from 0 to 1.
1. Band 1 of the reference image is cut to a window around the polygon. The window is the polygon buffered by `buffer_ratio * sqrt(area)` (in raster CRS units), so edges along the polygon border are detected too.
2. GRASS `i.zc` runs on that window, using the *Filter width* and *Threshold* settings and one orientation.
3. The result is the number of zero-crossing edge pixels inside the unbuffered polygon, divided by all pixels inside it.

For RGB scans, band 1 is the red band.

**Contrast**
- For each band of the reference image, the plugin takes the spread between the lower and upper percentile (default 5th–95th) of the pixels inside the polygon. Pixels that are nodata in any band are excluded.
- For images with 3 or more bands, the same spread is also computed on the luminance `0.299 R + 0.587 G + 0.114 B`.
- The largest spread wins. It is normalised by 255 for 8-bit (Byte) rasters and by 65535 for 16-bit (UInt16) rasters, then capped at 1. Other data types (such as Float32) are not normalised.
- The value is empty if fewer than 10 valid pixels lie inside the polygon.

For paletted (indexed-colour) scans, contrast and edge complexity work on the palette indices, not the displayed colours. Convert such scans to RGB first (*Raster > Conversion > Translate* with "Expand to RGB") if these metrics matter.

**Centroid**: the polygon centroid, transformed to WGS 84 (EPSG:4326). It is stored in `Lat` and `Lon`.

## Visualising an export

`tools/draw_annotations.py` draws an export on top of its image, without needing QGIS. It needs numpy, matplotlib and Pillow; GDAL is used as a fallback reader for GeoTIFFs Pillow can't open.

```bash
python3 tools/draw_annotations.py <image> <annotations.json> [--image-id N] [--out file.png]
```

- It draws the top curve (green), the bottom curve (red), their control polygons, and the bbox (cyan) in the file's `bbox_format`.
- A square marks the first control point of each curve.
- Each label shows `#id: text`, decoded from `rec`. Unknown characters appear as `?`.
- Without `--image-id`, the image is matched by file name. If no name matches, the first image is used.
- `--out` saves a PNG instead of opening a window.
- Exports from v0.1, which have no `bbox_format` or `bezier_order` in `info`, are read as `xyxy` / `legacy`.

## Development and tests

Run the tests from the plugin directory with the Python that ships with QGIS. That is the system Python on Linux, or any Python that can `import qgis.core`.

```bash
/usr/bin/python3 -B -m unittest discover -s tests -v
/usr/bin/python3 -B -m unittest discover -s tests -p 'test_export.py' -v   # a single module
```

- The tests run headless (`QT_QPA_PLATFORM=offscreen`) against a temporary QGIS profile, so your real profile is never touched.
- Tests that need GRASS `i.zc` are skipped when it is not available.
- The suite also runs under pytest: `python3 -m pytest tests`.

Project layout:

| Path | Purpose |
|---|---|
| `MaptextAnnotator.py` | Plugin controller: actions, dock, layer signals, project layer memory, export. |
| `MaptextAnnotator_dockwidget.py`, `MaptextAnnotator_dockwidget_base.ui` | Dock widget and its Qt Designer form. |
| `settings.py` | Setting keys, defaults and `PluginSettings` (QgsSettings-backed). |
| `settings_dialog.py` | The settings dialog. |
| `schema.py` | Attribute fields, core/statistic field groups, storage contract. |
| `annotation_pipeline.py` | Per-feature processing: reference image, geometry fields, statistics. |
| `core/geometry.py` | Ring orientation, lower/upper split, cubic bezier fit (pure Python). |
| `core/phrases.py` | Phrase reconstruction from linked words. |
| `core/raster_stats.py` | Zonal statistics and contrast with GDAL and numpy. |
| `core/edge_density.py` | Edge complexity via GRASS `i.zc`. |
| `coco/annotation_creator.py` | JSON export (records, pixel conversion, skipping, atomic write). |
| `coco/bbox_formats.py` | `xyxy`, `xywh` and `polygon` bbox layouts. |
| `coco/coco_template.py` | COCO templates and the character map. |
| `tools/draw_annotations.py` | Standalone export viewer. |
| `tests/` | Unit and integration tests (`tests/utilities.py` sets up headless QGIS). |
| `annotator_style.qml` | Layer style: attribute form, defaults, Certainty value map. |
| `resources.qrc`, `resources.py` | Qt resources (icon, example image). |

## Troubleshooting

**Edge complexity is unavailable, or the checkbox is greyed out.** GRASS `i.zc` was not found. To fix it:
1. Install GRASS. It is included in the OSGeo4W and macOS installers; on Linux, install the `grass` package.
2. Enable *GRASS GIS provider* under *Plugins > Manage and Install Plugins > Installed*.
3. Check that `i.zc` appears in the Processing Toolbox.

Alternatively, disable the statistic in the settings.

**"No reference image" / Reference Image is `None found`.** The polygon must lie over a visible raster that is a local file read by GDAL, such as a GeoTIFF. Web, XYZ and WMS layers, and the layers selected as DEM or slope, never count. Make the map layer visible, then click **Recompute Selected**.

**Altitude or slope values are empty.** Possible causes:
- No DEM or slope layer is selected.
- The polygon lies outside the raster, or only covers nodata pixels.
- The raster has a wrong or missing CRS, so the polygon is transformed to the wrong place. Check the raster's CRS in *Layer Properties > Source*.

**The annotations are gone after restarting QGIS.** The layer from **Generate Layer** is a temporary scratch layer. QGIS warns about this when you close a project that contains one. Save the layer with *Make Permanent…* before closing.

**The layer is missing from the Annotation Polygon Layer list.** The list only shows polygon layers that have all core fields with the right types. Create layers with **Generate Layer**, and save them as GeoPackage. Shapefile truncates field names to 10 characters and changes the date type, so the plugin no longer recognises the layer.

**The export skips features with "reference image can't be opened".** The path in *Reference Image* no longer exists, for example because the scans were moved or the project was opened on another machine. Either restore the files, or update the paths with the Field Calculator, then export again.

## License and links

- License: GNU General Public License, version 2 or (at your option) any later version. See the source file headers.
- Author: Daniel Seisenbacher (dasebdu@gmail.com).
- Repository: https://github.com/danielseisenbacher/MapTextAnnotator
- Issue tracker: https://github.com/danielseisenbacher/MapTextAnnotator/issues
