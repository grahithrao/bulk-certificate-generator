import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as api_v1_router
from app.config import settings
from app.database import init_db
from app.models import utc_now
from app.schemas import HealthResponse
from app.services.certificates import init_fonts

logger = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup initialization
    settings.ensure_directories()
    init_db()
    try:
        init_fonts()
    except Exception as e:
        logger.warning(f"Font initialization warning: {e}")
    yield
    # Shutdown cleanup if needed


app = FastAPI(
    title="Grahith Rao | Bulk Certificate Generator",
    description=(
        "Production-quality backend system for bulk certificate generation. "
        "Accepts bulk recipient batches, validates data, queues generation asynchronously, "
        "isolates recipient failures, tracks granular progress, and securely serves rendered PDF certificates."
    ),
    version="1.0.0",
    contact={
        "name": "Grahith Rao",
    },
    lifespan=lifespan,
)


# Global Exception Handler to avoid leaking internal stack traces
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "An unexpected internal server error occurred. Please contact the administrator.",
        },
    )


# Versioned API routes
app.include_router(api_v1_router, prefix="/api/v1")


@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Service Health Check",
    description="Returns service status and operational metadata.",
    tags=["System"],
)
def health_check():
    return HealthResponse(
        status="ok",
        service="Bulk Certificate Generator",
        owner=settings.project_owner,
        timestamp=utc_now(),
        version="1.0.0",
    )


# Serve demo static files if directory exists
static_path = Path("static")
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

    @app.get("/", include_in_schema=False)
    def demo_page():
        index_file = static_path / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return {"message": "Bulk Certificate Generator API", "docs": "/docs"}
