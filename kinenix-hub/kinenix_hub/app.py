import logging
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import __version__
from . import query as hub_query
from .config import DATABASE_URL, HOST, PORT, STATIC_DIR, VIEWS_DIR
from .database import get_db, get_write_db, init_db
from .models import Worker, Execution
from .security import require_worker_api_key, require_dashboard_auth, log_auth_mode
from .services.telemetry_service import record_heartbeat, ingest_execution_log, step_summaries
from .services.ai_summarizer import analyze_failure

from contextlib import asynccontextmanager

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kinenix.hub")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Database initialized successfully.")
    log_auth_mode()
    yield


# Ensure tables exist immediately on import
init_db()

app = FastAPI(
    title="Kinenix Hub & AI Dashboard",
    version=__version__,
    description="Central control hub, telemetry receiver, and AI-powered failure summarizer for Kinenix Edge Workers.",
    lifespan=lifespan
)

# No CORS middleware: the dashboard is served from this same origin and workers are not browsers.
# Adding a permissive CORS policy would let any website read dashboard data through a logged-in browser.


# ---------------------------------------------------------
# Request Models
# ---------------------------------------------------------

class HeartbeatRequest(BaseModel):
    worker_id: str
    name: str = "Worker"
    ip_address: str = "127.0.0.1"
    os_info: str = "Linux"
    cpu_percent: float = 0.0
    ram_usage: str = "0.0 GB"
    current_task: Optional[str] = None


class TelemetryRequest(BaseModel):
    worker_id: str = "local-worker"
    payload: Dict[str, Any]


class QueryRequest(BaseModel):
    """A view or table name with filters, or one SQL SELECT (see query.py and docs/hub.md)."""
    source: str
    since: Optional[str] = None
    flow: Optional[str] = None
    worker: Optional[str] = None
    status: Optional[str] = None
    filters: Dict[str, str] = Field(default_factory=dict)
    limit: Optional[int] = None


# ---------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------

@app.get("/api/v1/healthz")
def health_check():
    return {"status": "healthy", "service": "Kinenix Hub"}


@app.get("/api/v1/auth/worker", dependencies=[Depends(require_worker_api_key)])
def check_worker_key():
    """Lets `kinenix connect` check the key before saving it, without recording a heartbeat or a run."""
    return {"status": "ok"}


@app.post("/api/v1/heartbeat", dependencies=[Depends(require_worker_api_key)])
def heartbeat(req: HeartbeatRequest, db: Session = Depends(get_write_db)):
    worker = record_heartbeat(
        db=db,
        worker_id=req.worker_id,
        name=req.name,
        ip_address=req.ip_address,
        os_info=req.os_info,
        cpu_percent=req.cpu_percent,
        ram_usage=req.ram_usage,
        current_task=req.current_task
    )
    return {"status": "ok", "worker": worker.to_dict()}


@app.get("/api/v1/workers", dependencies=[Depends(require_dashboard_auth)])
def list_workers(db: Session = Depends(get_db)):
    workers = db.query(Worker).all()
    return {"workers": [w.to_dict() for w in workers]}


@app.post("/api/v1/telemetry", dependencies=[Depends(require_worker_api_key)])
def receive_telemetry(req: TelemetryRequest, db: Session = Depends(get_write_db)):
    execution = ingest_execution_log(
        db=db,
        payload=req.payload,
        worker_id=req.worker_id
    )
    return {
        "status": "recorded",
        "execution_id": execution.id,
        "flow_name": execution.flow_name,
        "has_error": execution.has_error,
        "ai_summary": execution.ai_summary
    }


@app.get("/api/v1/executions", dependencies=[Depends(require_dashboard_auth)])
def list_executions(
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Execution).order_by(Execution.created_at.desc())
    if status:
        query = query.filter(Execution.status == status)
    items = query.limit(limit).all()
    return {"executions": [e.to_dict() for e in items]}


@app.get("/api/v1/executions/{execution_id}", dependencies=[Depends(require_dashboard_auth)])
def get_execution(execution_id: str, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution.to_dict()


@app.get("/api/v1/executions/{execution_id}/steps", dependencies=[Depends(require_dashboard_auth)])
def get_execution_steps(execution_id: str, db: Session = Depends(get_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    return {"execution": execution.to_dict(), "steps": step_summaries(execution.raw_log)}


@app.post("/api/v1/executions/{execution_id}/reanalyze", dependencies=[Depends(require_worker_api_key)])
def reanalyze_execution(execution_id: str, db: Session = Depends(get_write_db)):
    execution = db.query(Execution).filter(Execution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    facts = dict(
        flow_name=execution.flow_name,
        failed_step_name=execution.failed_step_name,
        error_message=execution.error_message,
        exception_class=execution.exception_class,
        error_type=execution.error_type
    )
    # The central LLM may take seconds; do not hold the database's write lock while it answers (#201)
    db.rollback()
    ai_res = analyze_failure(**facts)
    execution.ai_category = ai_res.get("category")
    execution.ai_confidence = ai_res.get("confidence")
    execution.ai_summary = ai_res.get("summary")
    execution.ai_root_cause = ai_res.get("root_cause")
    execution.ai_suggestion = ai_res.get("suggestion")

    db.commit()
    db.refresh(execution)
    return {"status": "reanalyzed", "execution": execution.to_dict()}


# ---------------------------------------------------------
# Read-only queries (`kinenix hub query --url`); executions.raw_log reads as empty here
# ---------------------------------------------------------

def _query_connection():
    try:
        return hub_query.connect(hub_query.database_path(DATABASE_URL), hide_raw_log=True)
    except hub_query.QueryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/query/catalog", dependencies=[Depends(require_dashboard_auth)])
def query_catalog():
    conn = _query_connection()
    try:
        return {"objects": hub_query.catalog(conn, VIEWS_DIR)}
    finally:
        conn.close()


@app.get("/api/v1/query/describe/{name}", dependencies=[Depends(require_dashboard_auth)])
def query_describe(name: str):
    conn = _query_connection()
    try:
        return hub_query.describe(conn, name, VIEWS_DIR)
    except hub_query.QueryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@app.get("/api/v1/query/runs", dependencies=[Depends(require_dashboard_auth)])
def query_runs(flow: Optional[str] = None, run: Optional[str] = None, limit: int = 1):
    """Newest runs with their reports, of one flow or by ID (`kinenix hub report`, `kinenix hub logs --flow`)."""
    conn = _query_connection()
    try:
        return {"runs": hub_query.latest_runs(conn, flow=flow, run=run, limit=limit)}
    except hub_query.QueryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@app.post("/api/v1/query", dependencies=[Depends(require_dashboard_auth)])
def run_query(req: QueryRequest):
    conn = _query_connection()
    try:
        result = hub_query.run(conn, req.source, since=req.since, flow=req.flow, worker=req.worker,
                               status=req.status, filters=req.filters, limit=req.limit)
        return result.to_dict()
    except hub_query.QueryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


# ---------------------------------------------------------
# Web Dashboard Frontend
# ---------------------------------------------------------

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", dependencies=[Depends(require_dashboard_auth)])
def serve_dashboard():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "Kinenix Hub Running. Dashboard UI file not found in static/."}


def start_server():
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    start_server()
