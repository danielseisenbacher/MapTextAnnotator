# MapText Annotator

A QGIS plugin for annotating text on scanned maps. Draw a polygon around each word, transcribe it, and export the annotations as COCO-style JSON for text spotting models such as ABCNet or DeepSolo. Each label can also get statistics: altitude and slope (from your DEM and slope rasters), edge complexity, contrast and centroid.

## Requirements

- QGIS 3.34 or newer
- A georeferenced map raster stored as a local file (e.g. GeoTIFF)
- Optional: DEM and slope rasters, and the GRASS provider (only needed for edge complexity)

## Installation

Copy or symlink this folder into your QGIS plugin directory, then enable **MapText Annotator** in *Plugins > Manage and Install Plugins*.

- Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
- Windows: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
- macOS: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`

## Usage

1. Load your map raster. Optionally add a DEM and a slope raster.
2. Click the **Annotate MapText** toolbar icon to open the dock.
3. Click **Generate Layer**. This creates a temporary layer, so save it (*Make Permanent…*, as GeoPackage) or your annotations are lost when QGIS closes.
4. Optionally pick a **DEM Layer** and a **Slope Layer**. Both can stay empty.
5. Toggle editing and draw one polygon per word. In the form, enter the transcription. Tick **Link to previous Word** if the word continues a phrase.
6. Save your edits, then click **Export Annotations**.

Statistics are computed when you add a polygon or edit its vertices. **Recompute Selected** recomputes the selected annotation.

### Drawing rules

1. Start at the **bottom-left corner** of the word.
2. Draw the vertices **counter-clockwise**: along the bottom edge, then back along the top edge.
3. Use the **same number of vertices** on the top and bottom edges (at least 2 each).

Polygons that break these rules are kept, but they are skipped at export.

## Settings

Open them with the gear button in the dock or *Plugins > MapText Annotator > Settings…*. They are remembered between sessions.

- Turn each statistic on or off: altitude, slope, edge complexity, contrast, centroid. Disabled statistics are not computed or exported, and their layer pickers are hidden.
- Edge complexity filter width and threshold; contrast percentiles.
- Bounding box format: `xyxy` (default), COCO `xywh`, or a 4-corner `polygon`.
- Bezier point order: `abcnet` (default) or `legacy` (the v0.1 order).

## Export

The JSON follows the COCO layout (`images`, `annotations`). All coordinates are pixels of the map image, with the origin at the top-left. Each annotation contains:

- `bbox`, `obbox`
- `bezier_pts` (16 values: top curve, then bottom curve)
- `rec` (the transcription as 50 character codes)
- `certainty`
- the enabled statistics

Features without a map raster underneath, with invalid polygons, or without a transcription are skipped and listed after the export.

To check an export visually:

```bash
python3 tools/draw_annotations.py <image> <annotations.json> [--out preview.png]
```

## Tests

Run with the Python that ships QGIS:

```bash
/usr/bin/python3 -B -m unittest discover -s tests -v
```

## License

GPL v2 or later. Author: Daniel Seisenbacher. Issues: https://github.com/danielseisenbacher/MapTextAnnotator/issues
