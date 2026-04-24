"""GET /api/dates — list dates with articles."""
from __future__ import annotations

from fastapi import APIRouter

from ..schemas import DateEntry
from ..services import catalog

router = APIRouter()


@router.get("/dates", response_model=list[DateEntry])
def list_dates() -> list[dict]:
    return catalog.available_dates()
