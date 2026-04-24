"""GET /api/files/{date}/{csv|dashboard|report} — serve on-disk artifacts."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ._common import validate_date

router = APIRouter()

ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA_DIR = ROOT / "data"


def _csv_path(date: str) -> Path:
    return DATA_DIR / f"news_{date}.csv"


def _image_path(date: str, name: str) -> Path:
    return DATA_DIR / "images" / date / f"{name}.png"


@router.get("/files/{date}/csv")
def get_csv(date: str) -> FileResponse:
    validate_date(date)
    path = _csv_path(date)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"csv for {date} not found")
    return FileResponse(path, media_type="text/csv", filename=path.name)


@router.get("/files/{date}/dashboard")
def get_dashboard(date: str) -> FileResponse:
    validate_date(date)
    path = _image_path(date, "dashboard")
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"dashboard for {date} not found")
    return FileResponse(path, media_type="image/png")


@router.get("/files/{date}/report")
def get_report(date: str) -> FileResponse:
    validate_date(date)
    path = _image_path(date, "report")
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"report for {date} not found")
    return FileResponse(path, media_type="image/png")
