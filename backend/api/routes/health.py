"""GET /api/health."""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from ..db import engine
from ..scheduler import next_run_iso, scheduler
from ..schemas import HealthOut

router = APIRouter()


@router.get("/health", response_model=HealthOut)
def health() -> dict:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:  # noqa: BLE001
        db_status = "error"
    return {
        "status": "ok",
        "scheduler": "running" if scheduler.running else "stopped",
        "next_run": next_run_iso(),
        "db": db_status,
    }
