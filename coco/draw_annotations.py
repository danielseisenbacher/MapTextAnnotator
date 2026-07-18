import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from PIL import Image

def draw_annotations(image_path, annotation_json, image_id=None):
    # Load image
    img = Image.open(image_path)
    img_array = np.array(img)

    # Load annotations
    with open(annotation_json, 'r') as f:
        data = json.load(f)

    # Find image entry
    if image_id is None:
        # Try to match by filename
        import os
        filename = os.path.basename(image_path)
        image_entry = next((i for i in data['images'] if i['file_name'] == filename), None)
        if image_entry is None:
            # Just use first image
            image_entry = data['images'][0]
            print(f"Could not find image by filename, using first image: {image_entry['file_name']}")
    else:
        image_entry = next((i for i in data['images'] if i['id'] == image_id), None)

    if image_entry is None:
        print("Image not found in annotations!")
        return

    img_id = image_entry['id']
    print(f"Showing annotations for image id={img_id}, file={image_entry['file_name']}")

    # Get annotations for this image
    anns = [a for a in data['annotations'] if a['image_id'] == img_id]
    print(f"Found {len(anns)} annotations")

    fig, ax = plt.subplots(1, 1, figsize=(16, 16))
    ax.imshow(img_array)

    colors_upper = 'lime'
    colors_lower = 'red'

    for i, ann in enumerate(anns):
        pts = ann['bezier_pts']
        # upper bezier: pts 0-7 (4 control points, x,y pairs)
        upper = [(pts[j], pts[j + 1]) for j in range(0, 8, 2)]
        # lower bezier: pts 8-15 (4 control points, x,y pairs)
        lower = [(pts[j], pts[j + 1]) for j in range(8, 16, 2)]

        # Draw upper bezier control points
        for k, (x, y) in enumerate(upper):
            ax.plot(x, y, 'o', color=colors_upper, markersize=6)
            ax.annotate(f'U{k}', (x, y), color=colors_upper, fontsize=7,
                        xytext=(3, 3), textcoords='offset points')

        # Draw lower bezier control points
        for k, (x, y) in enumerate(lower):
            ax.plot(x, y, 'o', color=colors_lower, markersize=6)
            ax.annotate(f'L{k}', (x, y), color=colors_lower, fontsize=7,
                        xytext=(3, 3), textcoords='offset points')

        # Connect upper points with line
        upper_x = [p[0] for p in upper]
        upper_y = [p[1] for p in upper]
        ax.plot(upper_x, upper_y, '-', color=colors_upper, linewidth=1.5)

        # Connect lower points with line
        lower_x = [p[0] for p in lower]
        lower_y = [p[1] for p in lower]
        ax.plot(lower_x, lower_y, '-', color=colors_lower, linewidth=1.5)

        # Draw bbox
        bbox = ann['bbox']  # x, y, w, h
        rect = patches.Rectangle((bbox[0], bbox[1]), bbox[2], bbox[3],
                                 linewidth=1, edgecolor='cyan', facecolor='none')
        ax.add_patch(rect)

        # Decode rec to text
        rec = ann['rec']
        chars = []
        for c in rec:
            if c == 96:
                break
            if 0 <= c <= 94:
                chars.append(chr(c + 32))  # ASCII offset
        text = ''.join(chars)

        # Label annotation number and text
        cx = upper_x[0]
        cy = upper_y[0] - 10
        ax.annotate(f'#{i}: {text}', (cx, cy), color='yellow', fontsize=8,
                    backgroundcolor='black')

    ax.set_title(f"Annotations for {image_entry['file_name']} — Green=Upper bezier, Red=Lower bezier, Cyan=BBox")
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    draw_annotations(
        r"/home/seisi/Desktop/Masterarbeit/Masterarbeit/Data/JPG/3LA_4751-3_1874_ref.jpg",
        r"/home/seisi/Desktop/annotations.json"
    )
