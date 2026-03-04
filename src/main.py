import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
from src.config import settings as _settings
if _settings.langfuse_public_key and _settings.langfuse_secret_key:
    import os
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", _settings.langfuse_public_key)
    os.environ.setdefault("LANGFUSE_SECRET_KEY", _settings.langfuse_secret_key)
    os.environ.setdefault("LANGFUSE_HOST", _settings.langfuse_host)
    logging.getLogger(__name__).info("Langfuse tracing enabled → %s", _settings.langfuse_host)
from fastapi.responses import HTMLResponse
from pymongo.errors import PyMongoError
from src.db import init_db
from src.services.scheduler import scheduler, start_scheduler
from src.routes import landing, dashboard
from src.routes import signals as signals_router
from src.routes import config as config_router
from src.routes import alerts as alerts_router
from src.routes import auth as auth_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    start_scheduler()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Signals", lifespan=lifespan)

app.include_router(auth_router.router)
app.include_router(landing.router)
app.include_router(dashboard.router)
app.include_router(signals_router.router)
app.include_router(config_router.router)
app.include_router(alerts_router.router)


@app.exception_handler(PyMongoError)
async def mongo_error_handler(request: Request, exc: PyMongoError):
    from src.templates_config import templates
    return templates.TemplateResponse(
        request,
        "error.html",
        {"detail": "Database is unavailable. Please try again later."},
        status_code=503,
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
