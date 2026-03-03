from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    from src.templates_config import templates
    return templates.TemplateResponse(request, "landing.html", {})
