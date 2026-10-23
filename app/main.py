"""FastAPI application factory."""
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import protected, router
from app.core.config import Settings, get_settings
from app.core.services import Services, build_services
from app.services.docker_service import ContainerNotFound, DockerUnavailable

STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Optional[Settings] = None, services: Optional[Services] = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="DevOpsPilot AI", version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.services = services or build_services(settings)
    app.dependency_overrides[get_settings] = lambda: settings

    app.add_middleware(CORSMiddleware, allow_origins=settings.origins, allow_methods=["GET", "POST", "PATCH"],
                       allow_headers=["Authorization", "Content-Type"])

    @app.middleware("http")
    async def limit_request_size(request: Request, call_next):
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > settings.max_request_bytes:
            return JSONResponse({"error": "request_too_large", "message": "Request body is too large."}, status_code=413)
        return await call_next(request)

    @app.exception_handler(DockerUnavailable)
    async def docker_down(_: Request, exc: DockerUnavailable):
        return JSONResponse({"error": "docker_unavailable", "message": str(exc)}, status_code=503)

    @app.exception_handler(ContainerNotFound)
    async def not_found(_: Request, exc: ContainerNotFound):
        return JSONResponse({"error": "container_not_found", "message": str(exc)}, status_code=404)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception):
        # Do not leak internals or secrets in error bodies.
        return JSONResponse({"error": "internal_error", "message": "Unexpected server error. Check the server log."}, status_code=500)

    app.include_router(router)
    app.include_router(protected)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app


def app_factory() -> FastAPI:
    return create_app()
