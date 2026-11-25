"""HTTP adapters for the application's explicit runtime resources."""

from fastapi import Request

from backend.app.infrastructure.context import ApplicationContext


def application_context(request: Request) -> ApplicationContext:
    state = request.app.state
    return ApplicationContext(
        password_slots=state.password_slots,
        settings=state.settings,
        provider_registry=state.provider_registry,
        preview_slots=state.preview_slots,
        preview_limits=state.preview_limits,
        provider_slots=state.provider_slots,
        provider_limits=state.provider_limits,
    )
