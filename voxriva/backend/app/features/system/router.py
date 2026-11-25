from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import PlainTextResponse

from backend.app.features.identity.dependencies import platform_admin, session_principal
from backend.app.features.system.monitoring import read_monitoring
from backend.app.features.system.schemas import Liveness, SystemInfo, SystemStatus
from backend.app.infrastructure.resources import Dependencies, Readiness
from backend.app.infrastructure.settings import Settings


def system_router(config: Settings) -> APIRouter:
    router = APIRouter()
    system = APIRouter(prefix="/api/v1/system", tags=["System"])
    info = SystemInfo(version=config.version)

    async def readiness(request: Request) -> Readiness:
        probes: Dependencies = request.app.state.dependencies
        return await probes.readiness()

    @router.get("/health/live", tags=["Health"])
    async def live() -> Liveness:
        return Liveness()

    @router.get(
        "/health/ready",
        tags=["Health"],
        responses={
            503: {"model": Readiness, "description": "A dependency is unavailable"}
        },
    )
    async def ready(request: Request, response: Response) -> Readiness:
        report = await readiness(request)
        response.headers["Cache-Control"] = "no-store"
        if report.status != "ready":
            response.status_code = 503
        return report

    @router.get("/metrics", response_class=PlainTextResponse, tags=["Health"])
    async def metrics(request: Request) -> str:
        report = await readiness(request)
        samples = [
            "# HELP voxriva_dependency_ready Whether the dependency is ready.",
            "# TYPE voxriva_dependency_ready gauge",
        ]
        samples.extend(
            (
                f'''voxriva_dependency_ready{{dependency="{name}"}} {int(state == "ready")}'''
                for name, state in report.checks.items()
            )
        )
        return "\n".join(samples) + "\n"

    @system.get("/info")
    async def system_info(response: Response) -> SystemInfo:
        response.headers["Cache-Control"] = "no-store"
        return info

    @system.get("/readiness", dependencies=[Depends(session_principal)])
    async def system_readiness(request: Request) -> Readiness:
        return await readiness(request)

    @system.get("/status", dependencies=[Depends(platform_admin)])
    async def system_status(request: Request, response: Response) -> SystemStatus:
        response.headers["Cache-Control"] = "no-store"
        return SystemStatus(
            info=info,
            readiness=await readiness(request),
            monitoring=read_monitoring(config),
            snapshot_max_age_seconds=config.snapshot_max_age,
        )

    router.include_router(system)
    return router
