"""
state.py — Shared mutable state.
Centralised here to avoid circular imports between main.py and routers.
"""
from datetime import datetime
import threading
from typing import Optional, Any

# ID of the currently-active surgery session (None = no session running)
active_session_id: Optional[int] = None

# asyncio event loop — set by main.py on startup
event_loop: Optional[Any] = None

# WebSocket connection manager — set by main.py on startup
ws_manager: Optional[Any] = None

# Camera pause flag — toggled by /detect/camera/toggle
camera_paused: bool = False

# True when running on simulated (blank) camera — set by camera init in main.py
is_simulated_camera: bool = True

# Latest detection payload from the live pipeline or upload flow.
latest_detections: list[dict[str, Any]] = []
latest_detection_timestamp: Optional[datetime] = None
latest_frame: Optional[Any] = None
_state_lock = threading.RLock()


def set_latest_frame(frame: Any) -> None:
    global latest_frame
    with _state_lock:
        latest_frame = frame.copy() if frame is not None else None


def get_latest_frame() -> Optional[Any]:
    with _state_lock:
        return latest_frame.copy() if latest_frame is not None else None


def set_latest_detections(detections: list[dict[str, Any]], timestamp: Optional[datetime] = None) -> None:
    global latest_detections, latest_detection_timestamp
    with _state_lock:
        latest_detections = [dict(item) for item in detections]
        latest_detection_timestamp = timestamp or datetime.utcnow()


def get_latest_detections() -> tuple[list[dict[str, Any]], Optional[datetime]]:
    with _state_lock:
        return [dict(item) for item in latest_detections], latest_detection_timestamp

