"""
camera.py — Webcam capture with simulated fallback.

Priority:
  1. Real webcam (OpenCV index 0)
  2. Simulated feed cycling through dataset_yolo/images/test/
"""
import cv2
import time
import threading
import glob
import numpy as np
from pathlib import Path
from typing import Callable, Optional

SIMULATED_IMAGE_GLOB = "dataset_yolo/images/test/*.jpg"
CAPTURE_FPS = 18.0
RECONNECT_DELAY_SECONDS = 1.0


class WebcamCamera:
    """Captures frames from a physical webcam."""

    def __init__(self, index: int = 0):
        self.index = index
        self._cap: Optional[cv2.VideoCapture] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callback: Optional[Callable] = None
        self._latest: Optional[np.ndarray] = None
        self._lock = threading.Lock()

    def start(self, callback: Callable[[np.ndarray], None]) -> None:
        self._callback = callback
        if not self._open_capture():
            raise RuntimeError(f"Cannot open webcam index={self.index}")
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print(f"✅ Webcam started (index={self.index})")

    def stop(self) -> None:
        self._running = False
        if self._cap:
            self._cap.release()

    def _loop(self) -> None:
        interval = 1.0 / CAPTURE_FPS
        while self._running:
            if self._cap is None or not self._cap.isOpened():
                self._open_capture()
                time.sleep(RECONNECT_DELAY_SECONDS)
                continue

            ret, frame = self._cap.read()
            if ret:
                with self._lock:
                    self._latest = frame
                if self._callback:
                    self._callback(frame)
            else:
                print("Webcam frame read failed; reconnecting.")
                self._cap.release()
                self._cap = None
                time.sleep(RECONNECT_DELAY_SECONDS)
                continue
            time.sleep(interval)

    def _open_capture(self) -> bool:
        self._cap = cv2.VideoCapture(self.index, cv2.CAP_DSHOW)
        if not self._cap.isOpened():
            return False
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self._cap.set(cv2.CAP_PROP_FPS, CAPTURE_FPS)
        return True

    def get_latest(self) -> Optional[np.ndarray]:
        with self._lock:
            return self._latest.copy() if self._latest is not None else None


class SimulatedCamera:
    """Cycles through test images at CAPTURE_FPS — no physical camera needed."""

    def __init__(self) -> None:
        self._images = sorted(glob.glob(SIMULATED_IMAGE_GLOB))
        if not self._images:
            # Fallback: 480×640 blank frame
            self._images = []
        self._idx = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callback: Optional[Callable] = None
        print(f"ℹ️  Simulated camera — {len(self._images)} test images")

    def start(self, callback: Callable[[np.ndarray], None]) -> None:
        self._callback = callback
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        interval = 1.0 / CAPTURE_FPS
        while self._running:
            if self._images:
                frame = cv2.imread(self._images[self._idx % len(self._images)])
                if frame is not None and self._callback:
                    self._callback(frame)
                self._idx += 1
            else:
                # Blank frame
                blank = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(blank, "No camera / test images found",
                            (60, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (80, 80, 80), 2)
                if self._callback:
                    self._callback(blank)
            time.sleep(interval)


# ── Global camera instance ─────────────────────────────────────────────────────
_camera = None


def init_camera(callback: Callable[[np.ndarray], None]):
    global _camera
    # Try real webcam first, fall back to simulation
    cam = WebcamCamera(index=0)
    try:
        cam.start(callback)
        _camera = cam
    except RuntimeError as exc:
        print(f"⚠️  Webcam unavailable ({exc}). Using simulated camera.")
        sim = SimulatedCamera()
        sim.start(callback)
        _camera = sim
    return _camera


def get_camera():
    return _camera
