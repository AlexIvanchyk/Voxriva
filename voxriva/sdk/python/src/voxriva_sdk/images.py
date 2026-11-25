"""Encode bounded raster bytes for Image variables; the server decodes and validates them."""
import base64

from .errors import InputError
from .models import JsonValue


def image_from_bytes(content: bytes, media_type: str) -> dict[str, JsonValue]:
    """Build an Image v1 context value. No file paths or remote fetches are performed."""
    if media_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise InputError("Use image/png, image/jpeg or image/webp.")
    if not isinstance(content, bytes) or not 1 <= len(content) <= 262144:
        raise InputError("Image must contain 1–262144 bytes.")
    return {"media_type": media_type, "content_base64": base64.b64encode(content).decode("ascii")}
