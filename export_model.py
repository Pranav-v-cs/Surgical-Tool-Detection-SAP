"""
export_model.py
===============
Export trained YOLOv8 best.pt to:
  1. ONNX  — for general inference / testing
  2. NCNN  — optimized for Raspberry Pi 5 (ARM CPU)

Run AFTER training:
  python export_model.py
"""

from pathlib import Path
from ultralytics import YOLO

# ── Config ────────────────────────────────────────────────────────────────────
BEST_PT  = Path("runs/surgical/yolov8s_instruments/weights/best.pt")
IMG_SIZE = 640
# ─────────────────────────────────────────────────────────────────────────────

assert BEST_PT.exists(), f"❌ {BEST_PT} not found! Run train.py first."

model = YOLO(str(BEST_PT))
print(f"✅ Loaded: {BEST_PT}")

# ── 1. Export to ONNX ────────────────────────────────────────────────────────
print("\n⚙  Exporting to ONNX...")
model.export(
    format   = "onnx",
    imgsz    = IMG_SIZE,
    simplify = True,   # simplify ONNX graph
    opset    = 12,     # broad compatibility
    dynamic  = False,
)
print("✅ ONNX export done → best.onnx")

# ── 2. Export to NCNN (for Raspberry Pi) ─────────────────────────────────────
print("\n⚙  Exporting to NCNN (Raspberry Pi optimized)...")
try:
    model.export(
        format = "ncnn",
        imgsz  = IMG_SIZE,
    )
    print("✅ NCNN export done → best_ncnn_model/")
except Exception as e:
    print(f"⚠  NCNN export failed: {e}")
    print("   Install ncnn tools:  pip install ncnn")
    print("   Or run the export directly on Raspberry Pi")

print("\n📦 Exported files:")
export_dir = BEST_PT.parent
for f in export_dir.parent.rglob("best.*"):
    print(f"   {f}")

print("\n⚡ Next step → copy best.pt / best.onnx to Raspberry Pi")
print("   Then run:  python inference.py")
