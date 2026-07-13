"""Branding logic — most of it is making an uploaded logo safe.

A logo is customer-supplied bytes that we then serve to other people, so it is treated
as hostile until proven otherwise: we open it with Pillow (rejecting anything that is
not a real raster image), cap its size, resize it down, and RE-ENCODE it to a clean PNG.
Re-encoding is the important part — whatever was hidden in the original file (an SVG
script, a polyglot, EXIF) does not survive being decoded to pixels and written back out.
"""

import base64
import io

from PIL import Image, UnidentifiedImageError

# A brand logo does not need to be big. These bound both the upload we accept and the
# image we store, so a data URI on the captive portal stays small.
MAX_UPLOAD_BYTES = 3 * 1024 * 1024  # generous for the source file
MAX_DIMENSION = 512  # px — the longest side after resize
HEX = ("0123456789abcdefABCDEF")


class BrandingError(Exception):
    """Safe to show the user."""


def process_logo(raw: bytes) -> str:
    """Validate + normalise an uploaded logo, returning a `data:image/png;base64,...`
    URI. Raises BrandingError on anything that is not a sane image."""
    if not raw:
        raise BrandingError("No image was uploaded.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise BrandingError("That image is too large. Keep it under 3 MB.")

    try:
        img = Image.open(io.BytesIO(raw))
        img.verify()  # cheap structural check; must reopen after verify()
        img = Image.open(io.BytesIO(raw))
    except (UnidentifiedImageError, OSError) as exc:
        raise BrandingError("That file is not an image we can read.") from exc

    # Flatten transparency onto nothing special — keep alpha for logos, but convert
    # exotic modes (CMYK, P) to RGBA so the re-encode is predictable.
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")

    img.thumbnail((MAX_DIMENSION, MAX_DIMENSION))  # in place, preserves aspect

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)  # re-encode: drops anything non-pixel
    encoded = base64.b64encode(out.getvalue()).decode()
    return f"data:image/png;base64,{encoded}"


def clean_hex_color(value: str, *, field: str) -> str:
    """Accept #rgb or #rrggbb, normalise to #rrggbb lowercase. This value gets
    interpolated into CSS on the portal, so it must be exactly a colour and nothing
    that could break out of the style attribute."""
    v = (value or "").strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    if len(v) != 6 or any(c not in HEX for c in v):
        raise BrandingError(f"{field} must be a hex colour like #228B22.")
    return f"#{v.lower()}"
