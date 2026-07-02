"""
inference.py — YOLOv8 detection engine (singleton, GPU-accelerated).
"""
import cv2
import base64
import threading
import numpy as np
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple
from ultralytics import YOLO  # type: ignore

# Search these paths for best.pt (in priority order)
MODEL_SEARCH_PATHS = [
    # Path("runs/detect/runs/surgical/yolov8s_instruments/weights/best.pt"),
    # Path("models/best.pt"),
    # Path("runs/surgical/yolov8s_instruments/weights/best.pt"),
    # Path("runs/detect/runs/surgical/yolov8s_instruments-7/weights/best.pt"),
    Path("runs/detect/test/runs_detect_train_weights_best.pt")
]

NUM_CLASSES = 26
# Minimum confidence to report a detection.
# Raise this if you see false positives; lower it if real tools are being missed.
CONF_THRESHOLD = 0.40


@dataclass
class Detection:
    tool_id: int            # 1-based
    name: str               # "Tool 1", "Tool 2", …
    confidence: float
    bbox: List[float]       # [x1, y1, x2, y2] normalised 0-1


class InferenceEngine:
    """Loads YOLOv8 once and exposes a thread-safe detect() method."""

    def __init__(self):
        self.model: Optional[YOLO] = None
        self._lock = threading.Lock()
        self._load_model()

    def _load_model(self) -> None:
        for path in MODEL_SEARCH_PATHS:
            if path.exists():
                print(f"✅ Model loaded: {path.resolve()}")
                self.model = YOLO(str(path))
                return
        print("⚠️  No best.pt found — inference disabled. Check MODEL_SEARCH_PATHS.")

    def detect(self, frame: np.ndarray) -> List[Detection]:
        if self.model is None:
            return []
        with self._lock:
            results = self.model(frame, verbose=False, conf=CONF_THRESHOLD)[0]

        h, w = frame.shape[:2]

        raw_count = len(results.boxes)
        print(f"  [RAW] {raw_count} raw detections")
        for box in results.boxes:
            cls_id = int(box.cls[0])
            conf  = float(box.conf[0])
            print(f"    class={cls_id} tool={cls_id + 1} conf={conf:.4f}")

        # Deduplicate: for each tool class keep only the highest-confidence box.
        best: dict[int, Detection] = {}
        for box in results.boxes:
            cls_id = int(box.cls[0])
            conf  = float(box.conf[0])
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            tool_id = cls_id + 1
            if tool_id not in best or conf > best[tool_id].confidence:
                best[tool_id] = Detection(
                    tool_id=tool_id,
                    name=f"Tool {tool_id}",
                    confidence=round(conf, 4),
                    bbox=[round(x1 / w, 4), round(y1 / h, 4),
                          round(x2 / w, 4), round(y2 / h, 4)],
                )

        deduped = sorted(best.values(), key=lambda d: d.confidence, reverse=True)
        print(f"  [DEDUP] {len(deduped)} unique tools")
        for d in deduped:
            print(f"    {d.name}: conf={d.confidence:.4f}  bbox={[round(v, 3) for v in d.bbox]}")

        return deduped

    def detect_with_viz(self, frame: np.ndarray) -> Tuple[List[Detection], str]:
        """Returns (detections, annotated JPEG as base64 string)."""
        detections = self.detect(frame)
        return detections, encode_frame_with_detections(frame, detections)


def detection_to_payload(detection: Detection) -> dict:
    return {
        "tool_id": detection.tool_id,
        "name": detection.name,
        "confidence": detection.confidence,
        "bbox": detection.bbox,
    }


def detections_to_payload(detections: List[Detection]) -> list[dict]:
    return [detection_to_payload(detection) for detection in detections]


def encode_frame_with_detections(frame: np.ndarray, detections) -> str:
    viz = frame.copy()
    h, w = viz.shape[:2]

    for detection in detections or []:
        bbox = detection.bbox if hasattr(detection, "bbox") else detection.get("bbox")
        if not bbox:
            continue
        name = detection.name if hasattr(detection, "name") else detection.get("name", "Tool")
        confidence = detection.confidence if hasattr(detection, "confidence") else float(detection.get("confidence") or 0)
        x1 = int(bbox[0] * w); y1 = int(bbox[1] * h)
        x2 = int(bbox[2] * w); y2 = int(bbox[3] * h)
        cv2.rectangle(viz, (x1, y1), (x2, y2), (0, 255, 140), 2)
        label = f"{name}  {confidence:.0%}"
        (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        label_y = max(y1, lh + 8)
        cv2.rectangle(viz, (x1, label_y - lh - 8), (x1 + lw + 4, label_y), (0, 255, 140), -1)
        cv2.putText(viz, label, (x1 + 2, label_y - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

    max_width = 480
    if viz.shape[1] > max_width:
        scale = max_width / viz.shape[1]
        viz = cv2.resize(viz, (max_width, int(viz.shape[0] * scale)))

    _, buf = cv2.imencode(".jpg", viz, [cv2.IMWRITE_JPEG_QUALITY, 58])
    return base64.b64encode(buf).decode("utf-8")


# ── Singleton ─────────────────────────────────────────────────────────────────
_engine: Optional[InferenceEngine] = None
_engine_lock = threading.Lock()


def get_engine() -> InferenceEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = InferenceEngine()
    return _engine
