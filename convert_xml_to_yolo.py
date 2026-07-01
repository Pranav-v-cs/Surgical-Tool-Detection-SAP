"""
convert_xml_to_yolo.py
======================
Converts Pascal VOC XML annotations → YOLOv8 TXT format.

Dataset structure expected:
  dataset1-pic-xml/
    images/train/  val/  test/
    labels/train/  val/  test/  ← XML files here

Output structure (created automatically):
  dataset_yolo/
    images/train/  val/  test/  ← same images (symlinked/copied)
    labels/train/  val/  test/  ← converted .txt files
    data.yaml

Classes 1–26 → tool_1 to tool_26  (class index 0–25)
"""

import os
import glob
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
DATASET_XML_DIR = Path("dataset1-pic-xml")
OUTPUT_DIR      = Path("dataset_yolo")
SPLITS          = ["train", "val", "test"]

# 26 classes: numeric labels 1–26 become index 0–25
NUM_CLASSES = 26
CLASS_NAMES = {str(i): i - 1 for i in range(1, NUM_CLASSES + 1)}  # "1"→0, "2"→1 ...
CLASS_LIST  = [f"tool_{i}" for i in range(1, NUM_CLASSES + 1)]     # tool_1 … tool_26
# ─────────────────────────────────────────────────────────────────────────────


def xml_to_yolo(xml_path: Path, img_w: int, img_h: int) -> list[str]:
    """Parse a Pascal VOC XML and return a list of YOLO annotation lines."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Use size from XML if caller passes 0
    if img_w == 0 or img_h == 0:
        size = root.find("size")
        img_w = int(size.find("width").text)
        img_h = int(size.find("height").text)

    lines = []
    for obj in root.findall("object"):
        name = obj.find("name").text.strip()
        if name not in CLASS_NAMES:
            print(f"  ⚠  Unknown class '{name}' in {xml_path.name} — skipped")
            continue

        class_id = CLASS_NAMES[name]
        bb = obj.find("bndbox")
        xmin = float(bb.find("xmin").text)
        ymin = float(bb.find("ymin").text)
        xmax = float(bb.find("xmax").text)
        ymax = float(bb.find("ymax").text)

        # YOLO format: cx cy w h  (all normalized 0–1)
        cx = (xmin + xmax) / 2.0 / img_w
        cy = (ymin + ymax) / 2.0 / img_h
        w  = (xmax - xmin) / img_w
        h  = (ymax - ymin) / img_h

        # Clamp to [0, 1] just in case
        cx, cy, w, h = [max(0.0, min(1.0, v)) for v in (cx, cy, w, h)]
        lines.append(f"{class_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")

    return lines


def convert_split(split: str, stats: dict):
    img_in_dir  = DATASET_XML_DIR / "images" / split
    xml_in_dir  = DATASET_XML_DIR / "labels" / split
    img_out_dir = OUTPUT_DIR / "images" / split
    lbl_out_dir = OUTPUT_DIR / "labels" / split

    img_out_dir.mkdir(parents=True, exist_ok=True)
    lbl_out_dir.mkdir(parents=True, exist_ok=True)

    xml_files = [f for f in xml_in_dir.glob("*.xml") if not f.name.startswith("._")]
    ok = skip = 0

    for xml_path in xml_files:
        stem = xml_path.stem  # e.g. "a_1_2_3"

        # Find matching image (jpg / jpeg / png)
        img_path = None
        for ext in (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"):
            candidate = img_in_dir / (stem + ext)
            if candidate.exists():
                img_path = candidate
                break

        if img_path is None:
            print(f"  ⚠  No image for {xml_path.name} — skipped")
            skip += 1
            continue

        # Parse XML — get image dimensions from XML header (avoids loading img)
        tree = ET.parse(xml_path)
        root = tree.getroot()
        size = root.find("size")
        img_w = int(size.find("width").text)
        img_h = int(size.find("height").text)

        yolo_lines = xml_to_yolo(xml_path, img_w, img_h)
        if not yolo_lines:
            skip += 1
            continue

        # Copy image
        shutil.copy2(img_path, img_out_dir / img_path.name)

        # Write YOLO label
        txt_path = lbl_out_dir / (stem + ".txt")
        txt_path.write_text("\n".join(yolo_lines) + "\n")
        ok += 1

    stats[split] = {"converted": ok, "skipped": skip}
    print(f"  [{split:5s}]  ✅ {ok} converted  |  ⚠ {skip} skipped")


def write_data_yaml():
    yaml_path = OUTPUT_DIR / "data.yaml"
    lines = [
        f"path: {OUTPUT_DIR.resolve()}  # dataset root",
        "train: images/train",
        "val:   images/val",
        "test:  images/test",
        "",
        f"nc: {NUM_CLASSES}",
        "names:",
    ]
    for name in CLASS_LIST:
        lines.append(f"  - {name}")

    yaml_path.write_text("\n".join(lines) + "\n")
    print(f"\n✅ data.yaml written → {yaml_path.resolve()}")


def main():
    print("=" * 60)
    print("  Pascal VOC XML  →  YOLOv8 TXT Converter")
    print("=" * 60)

    stats = {}
    for split in SPLITS:
        convert_split(split, stats)

    write_data_yaml()

    print("\n📊 Summary:")
    for split, s in stats.items():
        print(f"  {split:5s}: {s['converted']} images converted, {s['skipped']} skipped")

    total = sum(s["converted"] for s in stats.values())
    print(f"\n🎯 Total: {total} annotated images ready for training")
    print(f"📁 Output: {OUTPUT_DIR.resolve()}")
    print("\nNext step → run:  python train.py")


if __name__ == "__main__":
    main()
