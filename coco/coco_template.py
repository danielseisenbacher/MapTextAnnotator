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
                        "area": 0,          # float
                        "category_id": 1,   # ignore
                        "id": 0,            # unique annotation id int
                        "image_id": 0,      # reference to image id
                        "iscrowd": 0,       # ignore
                        "bezier_pts":
                        [
                            "x0_top", "y0_top",             # all float values
                            "x1_top", "y1_top",
                            "x2_top", "y2_top",
                            "x3_top", "y3_top",
                            "x0_bottom", "y0_bottom",
                            "x1_bottom", "y1_bottom",
                            "x2_bottom", "y2_bottom",
                            "x3_bottom", "y3_bottom"
                        ],
                        "rec":
                        [
                            0,      # fill with character ints according to character map
                            0,
                        ],
                        "bbox":
                        [
                            153.0,  # float bbox - 2 points
                            305.0,
                            42.0,
                            52.0
                        ],
                        "obbox":
                        [
                            153.0,  # float bbox - 4 points
                        ],
                        "mean_altitude": 9999.0,  # float
                        "median_altitude": 9999.0,  # float
                        "max_altitude": 9999.0,  # float
                        "min_altitude": 9999.0,  # float
                        "mean_slope": 9999.0,  # float
                        "median_slope": 9999.0,  # float
                        "max_slope": 9999.0,  # float
                        "min_slope": 9999.0,  # float
                        "complexity": 9999.0,  # float
                        "contrast": 9999.0,  # float
                    }

deepsolo_character_map = {' ': 0,
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
                 'ß': 999,
                 'ü': 999,
                 'ä': 999,
                 'ö': 999,
                 'Ü': 999,
                 'Ä': 999,
                 'Ö': 999,
                 '´': 999
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
