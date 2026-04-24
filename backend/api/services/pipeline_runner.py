"""Subprocess-driven pipeline runner. Shared by scheduler and POST /api/runs."""
from __future__ import annotations

import logging
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from ..db import SessionLocal
from ..models import Run

log = logging.getLogger("pipeline")

ROOT = Path(__file__).resolve().parent.parent.parent.parent
LOG_DIR = ROOT / "data" / "logs"
SP_TZ = ZoneInfo("America/Sao_Paulo")

DEFAULT_STAGES = ["ingest", "extract", "dashboard", "report"]
ALLOWED_STAGES = set(DEFAULT_STAGES)

_run_lock = threading.Lock()
_current_run_id: Optional[str] = None


class RunInProgressError(RuntimeError):
    def __init__(self, run_id: str):
        super().__init__(f"run {run_id} already in progress")
        self.run_id = run_id


def _now() -> str:
    return datetime.now(SP_TZ).isoformat()


def _new_run_id() -> str:
    return datetime.now(SP_TZ).strftime("%Y%m%dT%H%M%S")


def _persist(run_id: str, **fields) -> None:
    with SessionLocal() as s:
        row = s.get(Run, run_id)
        if row is None:
            return
        for k, v in fields.items():
            setattr(row, k, v)
        s.commit()


def _execute(run_id: str, stages: list[str], target_date: str, log_path: Path) -> None:
    """Body of the background thread — runs stages sequentially."""
    global _current_run_id
    stage_state = [
        {"name": s, "status": "pending", "exit_code": None,
         "started_at": None, "finished_at": None}
        for s in stages
    ]
    _persist(run_id, status="running", stages=list(stage_state))

    overall_ok = True
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log_file:
        log_file.write(f"[{_now()}] run {run_id} start ({','.join(stages)})\n")
        log_file.flush()
        for idx, stage in enumerate(stages):
            stage_state[idx]["status"] = "running"
            stage_state[idx]["started_at"] = _now()
            _persist(run_id, stages=list(stage_state))

            cmd = [sys.executable, "-m", f"backend.pipeline.{stage}",
                   "--date", target_date]
            log_file.write(f"\n[{_now()}] $ {' '.join(cmd)}\n")
            log_file.flush()

            try:
                proc = subprocess.Popen(
                    cmd, stdout=log_file, stderr=subprocess.STDOUT, cwd=ROOT,
                )
                exit_code = proc.wait()
            except Exception as e:  # noqa: BLE001
                log_file.write(f"[{_now()}] stage {stage} crashed: {e}\n")
                exit_code = -1

            stage_state[idx]["exit_code"] = exit_code
            stage_state[idx]["finished_at"] = _now()
            stage_state[idx]["status"] = "success" if exit_code == 0 else "failed"
            _persist(run_id, stages=list(stage_state))

            if exit_code != 0:
                overall_ok = False
                # Mark remaining stages skipped and bail out.
                for later in stage_state[idx + 1 :]:
                    later["status"] = "skipped"
                _persist(run_id, stages=list(stage_state))
                break

        log_file.write(f"\n[{_now()}] run {run_id} {'ok' if overall_ok else 'failed'}\n")

    _persist(
        run_id,
        status="success" if overall_ok else "failed",
        finished_at=_now(),
        stages=list(stage_state),
    )

    with _run_lock:
        _current_run_id = None


def start(
    stages: Optional[list[str]] = None,
    target_date: Optional[str] = None,
    trigger: str = "manual",
) -> str:
    """Kick off a pipeline run in a background thread. Returns run_id.

    Raises RunInProgressError if a run is already active.
    """
    global _current_run_id
    stages = stages or DEFAULT_STAGES
    for s in stages:
        if s not in ALLOWED_STAGES:
            raise ValueError(f"unknown stage: {s}")

    if target_date is None:
        target_date = datetime.now(SP_TZ).date().isoformat()

    with _run_lock:
        if _current_run_id is not None:
            raise RunInProgressError(_current_run_id)
        run_id = _new_run_id()
        _current_run_id = run_id

    log_path = LOG_DIR / f"run_{run_id}.log"
    with SessionLocal() as s:
        s.add(Run(
            run_id=run_id,
            trigger=trigger,
            target_date=target_date,
            status="pending",
            started_at=_now(),
            finished_at=None,
            stages=[
                {"name": st, "status": "pending", "exit_code": None,
                 "started_at": None, "finished_at": None}
                for st in stages
            ],
            log_path=str(log_path.relative_to(ROOT)),
        ))
        s.commit()

    t = threading.Thread(
        target=_execute,
        args=(run_id, stages, target_date, log_path),
        name=f"pipeline-{run_id}",
        daemon=True,
    )
    t.start()
    return run_id


def current_run_id() -> Optional[str]:
    with _run_lock:
        return _current_run_id
