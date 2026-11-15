import hashlib
import io
import re
from pathlib import Path

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

from mealie.core.config import get_app_dirs


def media_path(owner: str, name: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{64}\.webp", name):
        raise HTTPException(404, "Photo not found")
    return get_app_dirs().DATA_DIR / "hearth-media" / owner / name


def save_image(owner: str, raw: bytes) -> str:
    if len(raw) > 10_000_000:
        raise HTTPException(413, "Image is too large")
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.width * source.height > 24_000_000:
                raise HTTPException(422, "Image dimensions are too large")
            source.thumbnail((1600, 1600))
            output = io.BytesIO()
            source.convert("RGB").save(output, format="WEBP", quality=85)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise HTTPException(422, "Upload a supported recipe photo") from error
    content = output.getvalue()
    name = hashlib.sha256(content).hexdigest() + ".webp"
    path = media_path(owner, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as file:
            file.write(content)
    except FileExistsError:
        pass
    return "/kitchen/media/" + name
