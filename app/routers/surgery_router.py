"""
surgery_router.py — Surgery session lifecycle endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

from ..database import get_db
from ..auth import get_current_user
from .. import models, state

router = APIRouter()


class StartSurgeryRequest(BaseModel):
    or_name: str
    surgeon_name: str


@router.post("/start")
async def start_surgery(
    req: StartSurgeryRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    # Close any currently-active session
    active = db.query(models.SurgerySession).filter(models.SurgerySession.is_active == True).first()
    if active:
        active.is_active = False
        active.ended_at = datetime.utcnow()
        db.commit()

    session = models.SurgerySession(
        or_name=req.or_name,
        surgeon_name=req.surgeon_name,
        started_by=user.id,
        is_active=True,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    state.active_session_id = session.id

    db.add(models.AuditLog(
        user_id=user.id,
        action="START_SURGERY",
        detail=f"OR: {req.or_name} | Surgeon: {req.surgeon_name}",
        ip_address=request.client.host if request.client else "unknown",
    ))
    db.commit()

    return {"session_id": session.id, "started_at": session.started_at}


@router.post("/end")
async def end_surgery(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    session = db.query(models.SurgerySession).filter(models.SurgerySession.is_active == True).first()
    if not session:
        raise HTTPException(status_code=404, detail="No active surgery session")

    session.is_active = False
    session.ended_at = datetime.utcnow()
    db.commit()

    state.active_session_id = None

    db.add(models.AuditLog(
        user_id=user.id,
        action="END_SURGERY",
        detail=f"Session #{session.id} ended",
        ip_address=request.client.host if request.client else "unknown",
    ))
    db.commit()

    duration = session.ended_at - session.started_at
    return {"session_id": session.id, "ended_at": session.ended_at, "duration_seconds": int(duration.total_seconds())}


@router.get("/active")
async def get_active_session(db: Session = Depends(get_db)):
    """Public endpoint — dashboard polls this on load."""
    session = db.query(models.SurgerySession).filter(models.SurgerySession.is_active == True).first()
    if not session:
        return None
    return {
        "id": session.id,
        "or_name": session.or_name,
        "surgeon_name": session.surgeon_name,
        "started_at": session.started_at,
    }


@router.get("/history")
async def get_history(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    sessions = (
        db.query(models.SurgerySession)
        .order_by(models.SurgerySession.started_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": s.id,
            "or_name": s.or_name,
            "surgeon_name": s.surgeon_name,
            "started_at": s.started_at,
            "ended_at": s.ended_at,
            "is_active": s.is_active,
            "detection_count": len(s.detections) if s.detections else 0,
            "duration_seconds": int((s.ended_at - s.started_at).total_seconds()) if s.ended_at else None,
        }
        for s in sessions
    ]
