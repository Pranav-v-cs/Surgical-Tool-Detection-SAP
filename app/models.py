"""
models.py — SQLAlchemy ORM table definitions.
"""
from sqlalchemy import Column, Integer, String, DateTime, Float, JSON, ForeignKey, Boolean, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    hashed_password = Column(String(256), nullable=False)
    role = Column(String(16), nullable=False)          # nurse | surgeon | admin
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    sessions = relationship("SurgerySession", back_populates="user")
    audit_logs = relationship("AuditLog", back_populates="user")


class SurgerySession(Base):
    __tablename__ = "surgery_sessions"

    id = Column(Integer, primary_key=True, index=True)
    or_name = Column(String(128), nullable=False)
    surgeon_name = Column(String(128), nullable=False)
    started_by = Column(Integer, ForeignKey("users.id"))
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)

    user = relationship("User", back_populates="sessions")
    detections = relationship("DetectionEvent", back_populates="session")


class DetectionEvent(Base):
    __tablename__ = "detection_events"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("surgery_sessions.id"))
    timestamp = Column(DateTime, default=datetime.utcnow)
    tools_detected = Column(JSON)       # [{"name": "Tool 1", "confidence": 0.92}]
    tool_count = Column(Integer, default=0)

    session = relationship("SurgerySession", back_populates="detections")


class SavedToolInventory(Base):
    __tablename__ = "saved_tool_inventory"
    __table_args__ = (
        UniqueConstraint("session_id", "tool_name", name="uq_saved_tool_inventory_session_tool"),
    )

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("surgery_sessions.id"), nullable=False, index=True)
    tool_name = Column(String(128), nullable=False)
    confidence_score = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    or_name = Column(String(128), nullable=False)
    surgeon_name = Column(String(128), nullable=False)


class ReconciliationResult(Base):
    __tablename__ = "reconciliation_results"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("surgery_sessions.id"), nullable=False, index=True)
    status = Column(String(16), nullable=False)
    saved_tools_count = Column(Integer, default=0, nullable=False)
    current_tools_count = Column(Integer, default=0, nullable=False)
    missing_tools = Column(JSON, default=list, nullable=False)
    present_tools = Column(JSON, default=list, nullable=False)
    current_tools = Column(JSON, default=list, nullable=False)
    checked_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    alert_logged = Column(Boolean, default=False, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    action = Column(String(64), nullable=False)
    detail = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    ip_address = Column(String(64), nullable=True)

    user = relationship("User", back_populates="audit_logs")
