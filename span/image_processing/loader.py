"""Open the source image, once, correctly.

EXIF orientation is applied here and nowhere else. After this function returns there is
exactly one image object in the process: the GUI renders it and the exporter cuts from
it. A rectangle placed over the preview therefore lands on the same pixels at export
time, with no chance of a rotation appearing between the two.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .. import diaglog

EXIF_ORIENTATION = 274


class ImageLoadError(RuntimeError):
    """Raised when the source image cannot be opened or decoded."""


def load_image(path: Path) -> Image.Image:
    """Load ``path`` as RGB with EXIF orientation applied."""
    path = Path(path)
    try:
        img = Image.open(path)
        img.load()   # force decoding inside the try, so a truncated file fails here
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageLoadError(f"cannot open image {path}: {exc}") from exc

    original = img.size
    orientation = img.getexif().get(EXIF_ORIENTATION)
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")

    diaglog.log(
        "image.load", path=str(path),
        original=f"{original[0]}x{original[1]}",
        exif_orientation=orientation,
        loaded=f"{img.width}x{img.height}", mode=img.mode,
    )
    return img
