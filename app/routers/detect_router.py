"""
detect_router.py — Image upload detection + camera toggle.
"""
import cv2
import numpy as np
from fastapi import APIRouter, UploadFile, File, HTTPException

from ..inference import detections_to_payload, get_engine
from .. import state

router = APIRouter()


@router.post("/upload")
async def detect_upload(file: UploadFile = File(...)):
    """
    Upload a JPEG/PNG image, run YOLOv8 inference, return detections + annotated frame.
    Works without a camera — great for testing.
    """
    # Validate file type
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image (JPEG/PNG)")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Empty file")

    # Decode image
    np_arr = np.frombuffer(contents, np.uint8)
    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=400, detail="Could not decode image")
    state.set_latest_frame(frame)

    # Run inference
    engine = get_engine()
    detections, frame_b64 = engine.detect_with_viz(frame)

    detections_payload = detections_to_payload(detections)
    state.set_latest_detections(detections_payload)

    return {
        "type": "detection",
        "source": "upload",
        "session_id": state.active_session_id,
        "detections": detections_payload,
        "frame": frame_b64,
        "tool_count": len(detections),
    }


@router.post("/camera/toggle")
async def toggle_camera():
    """Pause or resume the webcam capture pipeline."""
    state.camera_paused = not state.camera_paused
    return {
        "camera_paused": state.camera_paused,
        "status": "paused" if state.camera_paused else "active",
    }


@router.get("/camera/status")
async def camera_status():
    return {
        "camera_paused": state.camera_paused,
        "status": "paused" if state.camera_paused else "active",
    }
