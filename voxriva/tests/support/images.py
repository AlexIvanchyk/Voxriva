"""Small fictional raster bytes generated independently for image contracts."""
import base64
import io

from PIL import Image


def image_value(color="red", size=(3, 2), format="PNG"):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format=format)
    return {
        "media_type": {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[format],
        "content_base64": base64.b64encode(buffer.getvalue()).decode(),
    }
