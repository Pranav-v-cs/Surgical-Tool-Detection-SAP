"""
main.py — FastAPI application entry point.
Handles: startup, WebSocket broadcasting, camera → inference → WS pipeline.
"""
import asyncio
import threading
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Set

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .database import engine, SessionLocal
from . import models, state
from .auth import hash_password
from .inference import detections_to_payload, encode_frame_with_detections, get_engine
from .camera import init_camera
from .routers import auth_router, surgery_router, tools_router
from .routers import detect_router

# ── Bootstrap DB ──────────────────────────────────────────────────────────────
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Surgical Tools Detection",
    description="Hospital-grade real-time surgical instrument detection system",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth_router.router, prefix="/auth", tags=["Authentication"])
app.include_router(surgery_router.router, prefix="/surgery", tags=["Surgery"])
app.include_router(tools_router.router, prefix="/tools", tags=["Tools"])
app.include_router(tools_router.router, prefix="/api/tools", tags=["Tool Reconciliation"])
app.include_router(detect_router.router, prefix="/detect", tags=["Detection"])

# ── Static files & pages ──────────────────────────────────────────────────────
FRONTEND = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND / "static")), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(
        str(FRONTEND / "index.html"),
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    return FileResponse(
        str(FRONTEND / "dashboard.html"),
        headers={"Cache-Control": "no-store, max-age=0"},
    )


# ── WebSocket Manager ─────────────────────────────────────────────────────────
class WSManager:
    def __init__(self):
        self._clients: Set[WebSocket] = set()
        self._last_payload: dict = {}

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._clients.add(ws)
        # Send last known detection immediately so screen isn't blank
        if self._last_payload:
            try:
                await ws.send_json(self._last_payload)
            except Exception:
                pass

    def disconnect(self, ws: WebSocket):
        self._clients.discard(ws)

    async def broadcast(self, payload: dict):
        self._last_payload = payload
        dead: Set[WebSocket] = set()
        for ws in list(self._clients):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.add(ws)
        self._clients -= dead


_manager = WSManager()
state.ws_manager = _manager
_last_persist_at = 0.0
_last_detection_signature = None
DETECTION_PERSIST_INTERVAL_SECONDS = 2.0
INFERENCE_INTERVAL_SECONDS = 5.0


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await _manager.connect(ws)
    try:
        while True:
            await ws.receive_text()   # keep-alive ping
    except WebSocketDisconnect:
        _manager.disconnect(ws)


# ── Detection pipeline (runs in background thread) ────────────────────────────
def _on_frame(frame: np.ndarray):
    """Called by the camera thread for every captured frame."""
    # Respect the camera pause toggle
    if state.camera_paused:
        return

    state.set_latest_frame(frame)
    detections, detection_timestamp = state.get_latest_detections()
    frame_b64 = encode_frame_with_detections(frame, detections)

    payload = {
        "type": "detection",
        "session_id": state.active_session_id,
        "detections": detections,
        "detection_timestamp": detection_timestamp.isoformat() if detection_timestamp else None,
        "frame": frame_b64,
        "tool_count": len(detections),
    }

    # Thread-safe broadcast to asyncio loop
    loop = state.event_loop
    if loop and loop.is_running():
        asyncio.run_coroutine_threadsafe(_manager.broadcast(payload), loop)


def _persist_detection_sample(detections: list[dict]):
    if not state.active_session_id or not detections:
        return

    global _last_persist_at, _last_detection_signature
    now = time.monotonic()
    signature = tuple((d.get("tool_id"), round(float(d.get("confidence") or 0), 1)) for d in detections)
    should_persist = (
        signature != _last_detection_signature
        or now - _last_persist_at >= DETECTION_PERSIST_INTERVAL_SECONDS
    )
    if not should_persist:
        return

    db = SessionLocal()
    try:
        db.add(models.DetectionEvent(
            session_id=state.active_session_id,
            tools_detected=[{"name": d["name"], "confidence": d["confidence"]} for d in detections],
            tool_count=len(detections),
        ))
        db.commit()
        _last_persist_at = now
        _last_detection_signature = signature
    finally:
        db.close()


def run_inference_on_latest_frame() -> list[dict]:
    frame = state.get_latest_frame()
    if frame is None:
        return []

    detections = get_engine().detect(frame)
    payload = detections_to_payload(detections)
    state.set_latest_detections(payload, datetime.utcnow())
    _persist_detection_sample(payload)
    return payload


def _inference_loop():
    while True:
        if not state.camera_paused:
            try:
                run_inference_on_latest_frame()
            except Exception as exc:
                print(f"[WARN] Inference worker error: {exc}")
        time.sleep(INFERENCE_INTERVAL_SECONDS)


# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def on_startup():
    state.event_loop = asyncio.get_event_loop()

    # Seed default users (only on first run)
    db = SessionLocal()
    try:
        if not db.query(models.User).first():
            default_users = [
                ("nurse1",   "nurse123",   "nurse"),
                ("surgeon1", "surgeon123", "surgeon"),
                ("admin",    "admin123",   "admin"),
            ]
            for username, password, role in default_users:
                db.add(models.User(
                    username=username,
                    hashed_password=hash_password(password),
                    role=role,
                ))
            db.commit()
            print("[INFO] Seeded default users: nurse1 / surgeon1 / admin")
    finally:
        db.close()

    # Load model in background so startup is fast
    threading.Thread(target=get_engine, daemon=True, name="model-loader").start()

    # Start camera -> inference pipeline
    threading.Thread(
        target=lambda: init_camera(_on_frame),
        daemon=True,
        name="camera-init",
    ).start()
    threading.Thread(
        target=_inference_loop,
        daemon=True,
        name="inference-worker",
    ).start()

    print("[INFO] Surgical Tools Detection server ready at http://localhost:8000")
