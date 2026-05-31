"""Portfolio (works gallery) API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.schemas import PortfolioItem, PortfolioListResponse
from app.services.portfolio import resolve_poster, scan_portfolio

router = APIRouter()


@router.get("", response_model=PortfolioListResponse)
def list_portfolio() -> PortfolioListResponse:
    raw = scan_portfolio()
    return PortfolioListResponse(
        items=[PortfolioItem.model_validate(x) for x in raw],
        total=len(raw),
    )


@router.get("/{project_id:path}/poster")
def get_poster(project_id: str) -> FileResponse:
    path = resolve_poster(project_id)
    if not path:
        raise HTTPException(status_code=404, detail="poster not found")
    return FileResponse(path, media_type="image/png")
