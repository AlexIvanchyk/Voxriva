"""SDK exceptions deliberately omit request bodies, tokens and raw transport responses."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationIssue:
    path: tuple[str | int, ...]
    code: str
    message: str


class VoxrivaError(Exception):
    """Base SDK error."""


class InputError(VoxrivaError, ValueError):
    """Invalid local client configuration or request."""


class ProtocolError(VoxrivaError):
    """The server returned an unexpected response shape."""
    def __init__(self, message: str, *, idempotency_key: str | None = None) -> None:
        self.idempotency_key = idempotency_key
        super().__init__(message)


class TransportError(VoxrivaError):
    def __init__(self, *, attempts: int, idempotency_key: str | None) -> None:
        self.attempts, self.idempotency_key = attempts, idempotency_key
        super().__init__("Could not confirm the API response. Reuse the same idempotency key when retrying a send.")


class ApiError(VoxrivaError):
    def __init__(self, status_code: int, *, attempts: int = 1, idempotency_key: str | None = None,
                 retry_after: float | None = None, issues: tuple[ValidationIssue, ...] = ()) -> None:
        self.status_code, self.attempts = status_code, attempts
        self.idempotency_key, self.retry_after, self.issues = idempotency_key, retry_after, issues
        self.retryable = status_code in {408, 429, 500, 502, 503, 504}
        messages = {400: "Invalid API request.", 401: "Invalid or inactive environment API key.", 403: "This operation is forbidden.",
                    404: "The requested resource is unavailable in this environment.", 409: "The idempotency key conflicts with an existing request.",
                    422: "Notification validation failed.", 429: "The API rate or capacity limit was reached."}
        super().__init__(messages.get(status_code, "The API returned an unsuccessful response.")+f" (HTTP {status_code})")


class AuthenticationError(ApiError):
    pass


class PermissionDeniedError(ApiError):
    pass


class NotFoundError(ApiError):
    pass


class ConflictError(ApiError):
    pass


class ValidationError(ApiError):
    pass


class RateLimitError(ApiError):
    pass


class ServiceUnavailableError(ApiError):
    pass
