import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.middleware.base import RequestResponseEndpoint
from starlette.types import Scope

from backend.app.features.deployments.inventory_router import router as deployments
from backend.app.features.deployments.router import router as lifecycle
from backend.app.features.identity.router import auth
from backend.app.features.management.router import router as management_credentials
from backend.app.features.notifications.operations_router import router as operations
from backend.app.features.notifications.router import router as notifications
from backend.app.features.projects.members_router import router as members
from backend.app.features.projects.router import delivery
from backend.app.features.projects.router import router as catalog
from backend.app.features.providers.adapters.registry import discover
from backend.app.features.providers.events_router import router as provider_events
from backend.app.features.providers.router import router as providers
from backend.app.features.system.router import system_router
from backend.app.features.templates.router import router as templates
from backend.app.features.templates.versions_router import router as template_versions
from backend.app.infrastructure.errors import ApplicationError
from backend.app.infrastructure.resources import Dependencies
from backend.app.infrastructure.settings import Settings


class FingerprintedAssets(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def create_app(
    settings: Settings | None = None, dependencies: Dependencies | None = None
) -> FastAPI:
    config = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        resources = (
            dependencies
            if dependencies is not None
            else Dependencies.from_settings(config)
        )
        application.state.dependencies = resources
        application.state.settings = config
        application.state.auth_limits = {}
        application.state.password_slots = asyncio.Semaphore(2)
        application.state.preview_slots = asyncio.Semaphore(2)
        application.state.preview_limits = {}
        application.state.provider_registry = discover()
        application.state.provider_slots = asyncio.Semaphore(2)
        application.state.provider_limits = {}
        application.state.session_factory = (
            async_sessionmaker(resources.database, expire_on_commit=False)
            if resources.database is not None
            else None
        )
        try:
            yield
        finally:
            await resources.close()

    app = FastAPI(title="Voxriva API", version=config.version, lifespan=lifespan)

    @app.middleware("http")
    async def api_cache_policy(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ApplicationError)
    async def application_error(
        request: Request, error: ApplicationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={"detail": error.detail},
            headers=error.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        detail = [
            {key: entry[key] for key in ("loc", "msg", "type")}
            for entry in error.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": detail})

    app.include_router(system_router(config))
    app.include_router(auth)
    app.include_router(management_credentials)
    app.include_router(catalog)
    app.include_router(delivery)
    app.include_router(templates)
    app.include_router(template_versions)
    app.include_router(lifecycle)
    app.include_router(deployments)
    app.include_router(providers)
    app.include_router(provider_events)
    app.include_router(members)
    app.include_router(notifications)
    app.include_router(operations)
    downloads = config.static_dir / "downloads"
    if downloads.is_dir():
        app.mount("/downloads", StaticFiles(directory=downloads), name="downloads")
    assets = config.static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", FingerprintedAssets(directory=assets), name="assets")

    @app.get("/", include_in_schema=False)
    @app.get("/system/health", include_in_schema=False)
    @app.get("/account/security", include_in_schema=False)
    @app.get("/sign-in", include_in_schema=False)
    @app.get("/api-keys", include_in_schema=False)
    @app.get("/notifications", include_in_schema=False)
    @app.get("/notifications/{path:path}", include_in_schema=False)
    @app.get("/operations", include_in_schema=False)
    @app.get("/providers", include_in_schema=False)
    @app.get("/deployments", include_in_schema=False)
    @app.get("/templates", include_in_schema=False)
    @app.get("/templates/{path:path}", include_in_schema=False)
    @app.get("/projects", include_in_schema=False)
    @app.get("/projects/{path:path}", include_in_schema=False)
    @app.get("/environments", include_in_schema=False)
    @app.get("/members", include_in_schema=False)
    async def dashboard() -> FileResponse:
        entry = config.static_dir / "index.html"
        if not entry.is_file():
            raise HTTPException(404, "Dashboard build unavailable")
        return FileResponse(entry, headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
