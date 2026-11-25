"""Application failures; the HTTP composition root chooses their representation."""

from typing import Any


class ApplicationError(Exception):
    def __init__(
        self, status_code: int, detail: Any, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail
        self.headers = headers
