"""POST /api/runs, GET /api/runs, GET /api/runs/{id}."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ..db import SessionLocal
from ..models import Run
from ..schemas import RunCreate, RunOut
from ..services import pipeline_runner
from ._common import validate_date

router = APIRouter()


def _to_out(row: Run) -> dict:
    return {
        "run_id": row.run_id,
        "trigger": row.trigger,
        "target_date": row.target_date,
        "status": row.status,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "stages": row.stages or [],
        "log_path": row.log_path,
    }


@router.post("/runs", response_model=RunOut, status_code=202)
def create_run(body: RunCreate) -> dict:
    if body.date:
        validate_date(body.date)
    try:
        run_id = pipeline_runner.start(
            stages=body.stages, target_date=body.date, trigger="manual",
        )
    except pipeline_runner.RunInProgressError as e:
        raise HTTPException(
            status_code=409,
            detail={"error": "run_in_progress", "run_id": e.run_id},
        ) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    with SessionLocal() as s:
        row = s.get(Run, run_id)
        if row is None:
            raise HTTPException(status_code=500, detail="run row missing after start")
        return _to_out(row)


@router.get("/runs", response_model=list[RunOut])
def list_runs(limit: int = 50) -> list[dict]:
    limit = max(1, min(limit, 200))
    with SessionLocal() as s:
        rows = (
            s.execute(select(Run).order_by(Run.started_at.desc()).limit(limit))
            .scalars()
            .all()
        )
        return [_to_out(r) for r in rows]


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: str) -> dict:
    with SessionLocal() as s:
        row = s.get(Run, run_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"run {run_id} not found")
        return _to_out(row)
