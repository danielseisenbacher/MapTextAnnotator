# -*- coding: utf-8 -*-
"""
Templates and character encoding of the COCO export (ABCNet / DeepSolo flavour).

The templates are never mutated: annotation_creator deep-copies them for every
export.
"""

# ABCNet 96-symbol vocabulary: 0-94 are the characters of character_map,
# 95 marks an unknown character and 96 is the padding token.
MAX_TEXT_LENGTH = 50
UNKNOWN_TOKEN = 95
PAD_TOKEN = 96

coco_template = {
                    "licenses":
                        [],
                    "info":
                        {},
                    "categories":
                        [
                            {
                                "id": 1,
                                "name": "text",
                                "supercategory": "text",
                            }
                        ],
                    "images":
                        [
                        ],
                    "annotations":
                        [
                        ]
                    }


images_template = {
                        "coco_url": "",         # ignore
                        "date_captured": "",    # ignore
                        "file_name": "",        # e.g. 0000000.jpg
                        "flickr_url": "",       # ignore
                        "id": 0,                # unique img indentifier, preferably same as file_name
                        "license": 0,           # ignore
                        "width": 0,             # set to width in px eg. 506
                        "height": 0             # set to height in px eg. 500
                    }

annotations_template = {
                        "id": 0,            # unique annotation id, sequential over exported features
                        "image_id": 0,      # reference to image id
                        "category_id": 1,   # always 1 ("text")
                        "iscrowd": 0,       # always 0
                        "area": 0.0,        # area of bbox in px^2
                        "bbox": [],         # pixel coords, layout see info["bbox_format"]
                        "bezier_pts": [],   # 16 floats: 4 top + 4 bottom control points (x, y),
                                            # order see info["bezier_order"]
                        "rec": [],          # MAX_TEXT_LENGTH character ints, see character_map
                        "bounding_points": [],  # polygon vertices x0, y0, x1, y1, ...
                        "obbox": [],        # oriented bbox, 4 corners x0, y0, ..., x3, y3
                        "certainty": None,  # int or None
                        # statistic keys (schema.STAT_EXPORT_KEYS) are added per enabled group
                    }

character_map = {' ': 0,
                 '!': 1,
                 '"': 2,
                 '#': 3,
                 '$': 4,
                 '%': 5,
                 '&': 6,
                 "'": 7,
                 '(': 8,
                 ')': 9,
                 '*': 10,
                 '+': 11,
                 ',': 12,
                 '-': 13,
                 '.': 14,
                 '/': 15,
                 '0': 16,
                 '1': 17,
                 '2': 18,
                 '3': 19,
                 '4': 20,
                 '5': 21,
                 '6': 22,
                 '7': 23,
                 '8': 24,
                 '9': 25,
                 ':': 26,
                 ';': 27,
                 '<': 28,
                 '=': 29,
                 '>': 30,
                 '?': 31,
                 '@': 32,
                 'A': 33,
                 'B': 34,
                 'C': 35,
                 'D': 36,
                 'E': 37,
                 'F': 38,
                 'G': 39,
                 'H': 40,
                 'I': 41,
                 'J': 42,
                 'K': 43,
                 'L': 44,
                 'M': 45,
                 'N': 46,
                 'O': 47,
                 'P': 48,
                 'Q': 49,
                 'R': 50,
                 'S': 51,
                 'T': 52,
                 'U': 53,
                 'V': 54,
                 'W': 55,
                 'X': 56,
                 'Y': 57,
                 'Z': 58,
                 '[': 59,
                 '\\': 60,
                 ']': 61,
                 '^': 62,
                 '_': 63,
                 '`': 64,
                 'a': 65,
                 'b': 66,
                 'c': 67,
                 'd': 68,
                 'e': 69,
                 'f': 70,
                 'g': 71,
                 'h': 72,
                 'i': 73,
                 'j': 74,
                 'k': 75,
                 'l': 76,
                 'm': 77,
                 'n': 78,
                 'o': 79,
                 'p': 80,
                 'q': 81,
                 'r': 82,
                 's': 83,
                 't': 84,
                 'u': 85,
                 'v': 86,
                 'w': 87,
                 'x': 88,
                 'y': 89,
                 'z': 90,
                 '{': 91,
                 '|': 92,
                 '}': 93,
                 '~': 94,
                 'ß': 83,   # -> s (closest approximation, ss would need splitting)
                 'ü': 85,   # -> u
                 'ä': 65,   # -> a
                 'ö': 79,   # -> o
                 'Ü': 53,   # -> U
                 'Ä': 33,   # -> A
                 'Ö': 47,   # -> O
                 '´': 7    # -> ' (apostrophe)
                 }
