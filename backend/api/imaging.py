"""Image operations built on top of the alpha mattes returned by the vision service."""

import base64
import io

import numpy as np
from PIL import Image, ImageColor, ImageFilter, ImageOps


def decode_masks(masks_b64: list[str]) -> list[np.ndarray]:
    return [
        np.asarray(Image.open(io.BytesIO(base64.b64decode(m))).convert("L"), dtype=np.float32) / 255.0
        for m in masks_b64
    ]


def combined_alpha(masks: list[np.ndarray]) -> Image.Image:
    """Union of all instance mattes as a single 8-bit alpha map."""
    alpha = np.maximum.reduce(masks)
    return Image.fromarray((alpha * 255).round().astype(np.uint8), mode="L")


def threshold(alpha: Image.Image, cutoff: int = 128) -> Image.Image:
    return alpha.point(lambda v: 255 if v >= cutoff else 0)


def background_mask(alpha: Image.Image) -> Image.Image:
    return ImageOps.invert(alpha)


def cutout(image: Image.Image, alpha: Image.Image) -> Image.Image:
    out = image.convert("RGBA")
    out.putalpha(alpha)
    return out


def replace_background(image: Image.Image, alpha: Image.Image, color: str | None = None,
                       background: Image.Image | None = None) -> Image.Image:
    rgb = image.convert("RGB")
    if background is not None:
        bg = ImageOps.fit(background.convert("RGB"), rgb.size)
    else:
        bg = Image.new("RGB", rgb.size, ImageColor.getrgb(color or "#ffffff"))
    return Image.composite(rgb, bg, alpha)


def blur_background(image: Image.Image, alpha: Image.Image, radius: float = 12) -> Image.Image:
    rgb = image.convert("RGB")
    return Image.composite(rgb, rgb.filter(ImageFilter.GaussianBlur(radius)), alpha)


def grayscale_background(image: Image.Image, alpha: Image.Image) -> Image.Image:
    rgb = image.convert("RGB")
    return Image.composite(rgb, ImageOps.grayscale(rgb).convert("RGB"), alpha)


def to_png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()
