"""Version-one raster values. No URLs, filesystem paths or HTML are accepted."""

import base64
import binascii
import hashlib
import io
import warnings
from typing import Any, Literal

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_IMAGE_BYTES = 262144
MAX_IMAGE_TOTAL = 1048576
MAX_IMAGE_PIXELS = 4000000
MIMES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


class ImageContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    content_base64: str = Field(max_length=349528, repr=False)

    @model_validator(mode="after")
    def raster(self) -> "ImageContent":
        try:
            data = base64.b64decode(self.content_base64, validate=True)
            if not data or len(data) > MAX_IMAGE_BYTES:
                raise ValueError("Image must be 1–262144 bytes")
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    if MIMES.get(image.format or "") != self.media_type:
                        raise ValueError(
                            "Image MIME does not match decoded PNG, JPEG or WebP"
                        )
                    if (
                        image.width > 4096
                        or image.height > 4096
                        or image.width * image.height > MAX_IMAGE_PIXELS
                    ):
                        raise ValueError(
                            "Image exceeds 4096 dimensions or 4 million pixels"
                        )
                    if getattr(image, "n_frames", 1) != 1:
                        raise ValueError("Use a single-frame raster image")
                    image.verify()
                with Image.open(io.BytesIO(data)) as image:
                    image.load()
        except (
            binascii.Error,
            OSError,
            UnidentifiedImageError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ):
            raise ValueError("Invalid raster image") from None
        if base64.b64encode(data).decode() != self.content_base64:
            raise ValueError("Use canonical padded base64")
        return self

    @property
    def cid(self) -> str:
        return (
            hashlib.sha256(base64.b64decode(self.content_base64)).hexdigest()
            + "@images.voxriva"
        )


def image_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "x-voxriva-image": 1,
        "properties": {
            "media_type": {"type": "string", "enum": list(MIMES.values())},
            "content_base64": {"type": "string", "maxLength": 349528},
        },
        "required": ["media_type", "content_base64"],
        "additionalProperties": False,
    }


def bounded_images(value: Any) -> int:
    """Bound all embedded binary values, including test scenarios, before persistence."""
    total = 0

    def visit(node: Any, depth: int = 0) -> None:
        nonlocal total
        if depth > 30:
            raise ValueError("Image data nesting exceeds 30 levels")
        if isinstance(node, dict):
            if node.get("media_type") in MIMES.values() and isinstance(
                node.get("content_base64"), str
            ):
                image = ImageContent.model_validate(node)
                total += len(base64.b64decode(image.content_base64))
                if total > MAX_IMAGE_TOTAL:
                    raise ValueError("Combined image content exceeds 1 MiB")
            else:
                for child in node.values():
                    visit(child, depth + 1)
        elif isinstance(node, list):
            for child in node:
                visit(child, depth + 1)

    visit(value)
    return total


def without_image_bytes(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ""
            if key == "content_base64"
            and value.get("media_type") in MIMES.values()
            and isinstance(child, str)
            else without_image_bytes(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [without_image_bytes(child) for child in value]
    return value


def resolve_images(value: Any, schema: Any, images: dict[str, ImageContent]) -> Any:
    if not isinstance(schema, dict):
        return value
    if schema.get("x-voxriva-image") is not None:
        if schema.get("x-voxriva-image") != 1 or schema.get("type") != "object":
            raise ValueError("Use x-voxriva-image: 1 with an object schema")
        image = ImageContent.model_validate(value)
        images[image.cid] = image
        return "cid:" + image.cid
    if isinstance(value, dict):
        return {
            key: resolve_images(
                child, schema.get("properties", {}).get(key, {}), images
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [
            resolve_images(child, schema.get("items", {}), images) for child in value
        ]
    return value


def synthetic_image() -> ImageContent:
    """Explicit fictional fixture only; never a runtime default."""
    output = io.BytesIO()
    Image.new("RGB", (16, 16), "#5475a5").save(output, format="PNG")
    return ImageContent(
        media_type="image/png",
        content_base64=base64.b64encode(output.getvalue()).decode(),
    )
