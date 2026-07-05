"""
tools_router.py — Tool detection statistics.
"""
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from collections import defaultdict

from ..database import get_db
from ..auth import get_current_user
from ..inference import detections_to_payload, get_engine
from .. import models, state

router = APIRouter()
CONFIDENCE_THRESHOLD = 0.45


def _unique_tools(detections):
    tools = {}
    for detection in detections or []:
        name = detection.get("name")
        confidence = float(detection.get("confidence") or 0)
        if not name or confidence < CONFIDENCE_THRESHOLD:
            continue
        current = tools.get(name)
        if current is None or confidence > current["confidence_score"]:
            tools[name] = {
                "tool_name": name,
                "confidence_score": confidence,
            }
    return tools


def _active_session(db: Session):
    session = db.query(models.SurgerySession).filter(models.SurgerySession.is_active == True).first()
    if not session:
        raise HTTPException(status_code=404, detail="No active surgery session")
    return session


def _audit(db: Session, request: Request, user: models.User, action: str, detail: dict):
    db.add(models.AuditLog(
        user_id=user.id,
        action=action,
        detail=json.dumps(detail),
        ip_address=request.client.host if request.client else "unknown",
    ))


def _force_latest_inference() -> tuple[list[dict], datetime]:
    # Use the stored detections if available — they come from the last upload
    # or the last real camera frame.  Re-running inference on state.latest_frame
    # is unreliable because the simulated camera overwrites it with a blank
    # frame at 18 FPS, which always yields 0 detections.
    stored, timestamp = state.get_latest_detections()
    if stored:
        return stored, timestamp or datetime.utcnow()

    # No stored detections yet — try to infer from whatever frame we have.
    frame = state.get_latest_frame()
    if frame is None:
        raise HTTPException(status_code=400, detail="No camera frame available")
    timestamp = datetime.utcnow()
    detections = detections_to_payload(get_engine().detect(frame))
    state.set_latest_detections(detections, timestamp)
    return detections, timestamp



@router.get("/stats")
async def get_tool_stats(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Aggregate detection counts per tool across all sessions."""
    events = db.query(models.DetectionEvent).all()
    counts: dict = defaultdict(int)
    for event in events:
        for tool in (event.tools_detected or []):
            name = tool.get("name", "Unknown")
            counts[name] += 1

    return sorted(
        [{"name": k, "count": v} for k, v in counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )


@router.get("/audit")
async def get_audit_log(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Admin-only: full audit trail."""
    if user.role != "admin":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Admin only")

    logs = (
        db.query(models.AuditLog)
        .order_by(models.AuditLog.timestamp.desc())
        .limit(200)
        .all()
    )
    return [
        {
            "id": l.id,
            "user_id": l.user_id,
            "username": l.user.username if l.user else "—",
            "action": l.action,
            "detail": l.detail,
            "timestamp": l.timestamp,
            "ip_address": l.ip_address,
        }
        for l in logs
    ]


@router.post("/save")
async def save_tool_inventory(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Save current unique live detections as the baseline inventory."""
    session = _active_session(db)
    existing = (
        db.query(models.SavedToolInventory)
        .filter(models.SavedToolInventory.session_id == session.id)
        .count()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Tools have already been saved for this session",
        )

    latest_detections, detection_timestamp = state.get_latest_detections()
    tools = _unique_tools(latest_detections)
    if not tools:
        raise HTTPException(
            status_code=400,
            detail="No tools detected at or above 45% confidence",
        )

    saved_at = detection_timestamp or datetime.utcnow()
    for tool in tools.values():
        db.add(models.SavedToolInventory(
            session_id=session.id,
            tool_name=tool["tool_name"],
            confidence_score=tool["confidence_score"],
            timestamp=saved_at,
            or_name=session.or_name,
            surgeon_name=session.surgeon_name,
        ))

    _audit(db, request, user, "SAVE_TOOLS", {
        "session_id": session.id,
        "tool_count": len(tools),
        "tools": sorted(tools.keys()),
    })
    db.commit()

    return {
        "session_id": session.id,
        "saved_tools_count": len(tools),
        "saved_tools": sorted(tools.values(), key=lambda item: item["tool_name"]),
        "timestamp": saved_at,
        "message": "Tools saved for reconciliation",
    }


@router.post("/check")
async def check_tool_inventory(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Compare current unique live detections with the saved baseline inventory."""
    session = _active_session(db)
    saved_rows = (
        db.query(models.SavedToolInventory)
        .filter(models.SavedToolInventory.session_id == session.id)
        .order_by(models.SavedToolInventory.tool_name.asc())
        .all()
    )
    if not saved_rows:
        raise HTTPException(
            status_code=404,
            detail="No saved tool inventory found for this session",
        )

    forced_detections, _ = _force_latest_inference()
    current_tools = _unique_tools(forced_detections)
    saved_names = {row.tool_name for row in saved_rows}
    current_names = set(current_tools.keys())
    missing_names = sorted(saved_names - current_names)
    present_names = sorted(saved_names & current_names)
    status = "PASS" if not missing_names else "FAIL"
    checked_at = datetime.utcnow()

    result = models.ReconciliationResult(
        session_id=session.id,
        status=status,
        saved_tools_count=len(saved_names),
        current_tools_count=len(current_names),
        missing_tools=missing_names,
        present_tools=present_names,
        current_tools=sorted(current_tools.values(), key=lambda item: item["tool_name"]),
        checked_at=checked_at,
        alert_logged=bool(missing_names),
    )
    db.add(result)

    _audit(db, request, user, "CHECK_TOOLS", {
        "session_id": session.id,
        "status": status,
        "saved_tools_count": len(saved_names),
        "current_tools_count": len(current_names),
        "missing_tools": missing_names,
    })
    if missing_names:
        _audit(db, request, user, "MISSING_TOOL_ALERT", {
            "session_id": session.id,
            "missing_count": len(missing_names),
            "missing_tools": missing_names,
        })

    db.commit()
    db.refresh(result)
    return _result_payload(result)


@router.get("/results/{session_id}")
async def get_reconciliation_result(
    session_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Return the latest reconciliation result for a session."""
    result = (
        db.query(models.ReconciliationResult)
        .filter(models.ReconciliationResult.session_id == session_id)
        .order_by(models.ReconciliationResult.checked_at.desc())
        .first()
    )
    if not result:
        raise HTTPException(status_code=404, detail="No reconciliation result found")
    return _result_payload(result)


def _result_payload(result: models.ReconciliationResult):
    missing_tools = result.missing_tools or []
    return {
        "id": result.id,
        "session_id": result.session_id,
        "status": result.status,
        "safe": result.status == "PASS",
        "saved_tools_count": result.saved_tools_count,
        "current_tools_count": result.current_tools_count,
        "missing_tools_count": len(missing_tools),
        "missing_tools": missing_tools,
        "present_tools": result.present_tools or [],
        "current_tools": result.current_tools or [],
        "checked_at": result.checked_at,
        "message": (
            "All Surgical Tools Accounted For"
            if result.status == "PASS"
            else f"{len(missing_tools)} surgical tool(s) missing"
        ),
    }
