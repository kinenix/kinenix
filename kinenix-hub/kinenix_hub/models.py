import datetime
import json
import uuid
from sqlalchemy import Column, String, Float, Boolean, DateTime, Text, Integer, ForeignKey, Index
from . import config
from .database import Base
from .timeutils import isoformat_utc, utc_now


class Worker(Base):
    __tablename__ = "workers"

    id = Column(String(64), primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    ip_address = Column(String(64), default="127.0.0.1")
    os_info = Column(String(128), default="Linux")
    status = Column(String(32), default="online")  # online, offline, busy
    current_task = Column(String(128), nullable=True)
    cpu_percent = Column(Float, default=0.0)
    ram_usage = Column(String(32), default="0.0 GB")
    last_heartbeat = Column(DateTime, default=utc_now)

    def effective_status(self) -> str:
        """Stored status, or "offline" when the last heartbeat is older than WORKER_OFFLINE_SECONDS."""
        if self.last_heartbeat is None:
            return "offline"
        age = utc_now() - self.last_heartbeat
        if age > datetime.timedelta(seconds=config.WORKER_OFFLINE_SECONDS):
            return "offline"
        return self.status

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "ip_address": self.ip_address,
            "os_info": self.os_info,
            "status": self.effective_status(),
            "current_task": self.current_task,
            "cpu_percent": self.cpu_percent,
            "ram_usage": self.ram_usage,
            "last_heartbeat": isoformat_utc(self.last_heartbeat),
        }


class Execution(Base):
    __tablename__ = "executions"
    # A run sent twice is stored once (#165). Rows without a run id, from older workers, are not compared
    __table_args__ = (Index("uq_executions_worker_run", "worker_id", "run_id", unique=True),)

    id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    worker_id = Column(String(64), default="local-worker", index=True)
    run_id = Column(String(64), nullable=True)
    flow_name = Column(String(128), nullable=False, index=True)
    status = Column(String(32), default="success", index=True)  # success, partial, failed, interrupted, running
    start_time = Column(DateTime, default=utc_now)
    end_time = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, default=0.0)
    has_error = Column(Boolean, default=False)
    
    # Error details
    failed_step_id = Column(String(64), nullable=True)
    failed_step_name = Column(String(128), nullable=True)
    error_type = Column(String(64), nullable=True)
    exception_class = Column(String(128), nullable=True)
    error_message = Column(Text, nullable=True)
    screenshot_path = Column(String(256), nullable=True)
    raw_log = Column(Text, nullable=True)
    # Run facts as JSON: run id, Kinenix version, work items, report (services/run_records.py, docs/hub_data.md)
    details = Column(Text, nullable=True)

    # Central AI Triage & Summary
    ai_category = Column(String(128), nullable=True)
    ai_confidence = Column(Float, nullable=True)
    ai_summary = Column(Text, nullable=True)
    ai_root_cause = Column(Text, nullable=True)
    ai_suggestion = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utc_now)

    def to_dict(self):
        return {
            "id": self.id,
            "worker_id": self.worker_id,
            "flow_name": self.flow_name,
            "status": self.status,
            "start_time": isoformat_utc(self.start_time),
            "end_time": isoformat_utc(self.end_time),
            "duration_seconds": self.duration_seconds,
            "has_error": self.has_error,
            "failed_step_id": self.failed_step_id,
            "failed_step_name": self.failed_step_name,
            "error_type": self.error_type,
            "exception_class": self.exception_class,
            "error_message": self.error_message,
            "screenshot_path": self.screenshot_path,
            "ai_category": self.ai_category,
            "ai_confidence": self.ai_confidence,
            "ai_summary": self.ai_summary,
            "ai_root_cause": self.ai_root_cause,
            "ai_suggestion": self.ai_suggestion,
            "created_at": isoformat_utc(self.created_at),
            "details": _json_or_none(self.details),
        }


def _json_or_none(text):
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


class StepResult(Base):
    """One executed step of a run, also inside loops, subflows, On Error, and Finally (docs/hub_data.md)."""
    __tablename__ = "step_results"
    __table_args__ = (Index("ix_step_results_execution_seq", "execution_id", "seq"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    execution_id = Column(String(64), ForeignKey("executions.id"), nullable=False)
    seq = Column(Integer, nullable=False)
    section = Column(String(16), nullable=False, default="steps")
    step_id = Column(String(128), nullable=True)
    step_name = Column(Text, nullable=True)
    action = Column(String(64), nullable=True)
    status = Column(String(16), nullable=True)
    started_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    details = Column(Text, nullable=True)


class Failure(Base):
    """One failure of a run, also one the flow continued after (docs/hub_data.md)."""
    __tablename__ = "failures"
    __table_args__ = (
        Index("ix_failures_failed_at", "failed_at"),
        Index("ix_failures_flow_failed_at", "flow_name", "failed_at"),
        Index("ix_failures_execution", "execution_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    execution_id = Column(String(64), ForeignKey("executions.id"), nullable=False)
    step_result_id = Column(Integer, ForeignKey("step_results.id"), nullable=True)
    failed_at = Column(DateTime, nullable=True)
    flow_name = Column(String(128), nullable=True)
    worker_id = Column(String(64), nullable=True)
    step_name = Column(Text, nullable=True)
    action = Column(String(64), nullable=True)
    error_type = Column(String(32), nullable=True)
    handled = Column(String(16), nullable=True)
    message = Column(Text, nullable=True)
    details = Column(Text, nullable=True)

