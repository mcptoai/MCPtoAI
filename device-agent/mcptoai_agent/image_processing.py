"""Bounded, local-only image transforms. No external image services."""
from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SOURCE_BYTES = 25 * 1024 * 1024
MAX_PIXELS = 24_000_000
MAX_OUTPUT_BYTES = 25 * 1024 * 1024
MAX_SIDE = 10000
FORMATS = {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp'}


def _inside(path: str, roots: list[Path]) -> Path:
    p = Path(path).expanduser().resolve(strict=False)
    if not any(p == root.resolve() or p.is_relative_to(root.resolve()) for root in roots):
        raise PermissionError('Path outside allowed roots')
    return p


def _transform(source: str, roots: list[Path], operation: str, *, width: int = 0,
               height: int = 0, left: int = 0, top: int = 0, right: int = 0,
               bottom: int = 0, output_format: str = 'PNG', background: str = '#ffffff') -> tuple[bytes, dict]:
    if Path(source).expanduser().is_symlink():
        raise ValueError('Source symlinks are not permitted')
    src = _inside(source, roots)
    if not src.is_file() or src.is_symlink() or src.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError('Invalid or oversized source image')
    output_format = output_format.upper()
    if output_format not in FORMATS:
        raise ValueError('Unsupported output format')
    if operation not in ('resize', 'crop', 'convert'):
        raise ValueError('Unsupported operation')
    with Image.open(src) as opened:
        if opened.format not in FORMATS or getattr(opened, 'n_frames', 1) != 1:
            raise ValueError('Unsupported or animated source image')
        if opened.width * opened.height > MAX_PIXELS:
            raise ValueError('Source pixel quota exceeded')
        opened.load()
        image = ImageOps.exif_transpose(opened)
    original_size = image.size
    if operation == 'resize':
        if not (1 <= width <= MAX_SIDE and 1 <= height <= MAX_SIDE and width * height <= MAX_PIXELS):
            raise ValueError('Invalid resize dimensions')
        image.thumbnail((width, height), Image.Resampling.LANCZOS)
    elif operation == 'crop':
        if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
            raise ValueError('Crop must be inside the source image')
        image = image.crop((left, top, right, bottom))
    if image.width * image.height > MAX_PIXELS or max(image.size) > MAX_SIDE:
        raise ValueError('Output dimensions exceed quota')
    if output_format == 'JPEG':
        if image.mode in ('RGBA', 'LA') or 'transparency' in image.info:
            from PIL import ImageColor
            rgb = Image.new('RGB', image.size, ImageColor.getrgb(background))
            rgba = image.convert('RGBA')
            rgb.paste(rgba, mask=rgba.getchannel('A'))
            image = rgb
        else:
            image = image.convert('RGB')
    elif image.mode not in ('RGB', 'RGBA', 'L', 'LA'):
        image = image.convert('RGBA')
    out = io.BytesIO()
    # Do not forward EXIF, GPS, ICC or other untrusted source metadata.
    image.save(out, format=output_format)
    payload = out.getvalue()
    if len(payload) > MAX_OUTPUT_BYTES:
        raise ValueError('Output byte quota exceeded')
    return payload, {'source_dimensions': list(original_size), 'dimensions': list(image.size),
                     'format': output_format, 'bytes': len(payload), 'metadata': 'stripped'}


def preview(source: str, roots: list[Path], operation: str, **kwargs) -> dict:
    import base64
    data, details = _transform(source, roots, operation, **kwargs)
    with Image.open(io.BytesIO(data)) as img:
        img.thumbnail((640, 640), Image.Resampling.LANCZOS)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=65)
    details['preview_data_url'] = 'data:image/jpeg;base64,' + base64.b64encode(output.getvalue()).decode('ascii')
    return details


def save(source: str, destination: str, roots: list[Path], operation: str,
         overwrite: bool = False, **kwargs) -> dict:
    dest = _inside(destination, roots)
    if dest.is_symlink() or not dest.parent.is_dir() or dest.parent.is_symlink():
        raise ValueError('Destination parent must exist and must not be a symlink')
    if dest.exists() and not overwrite:
        raise FileExistsError('Destination exists; explicit overwrite approval required')
    data, details = _transform(source, roots, operation, **kwargs)
    if dest.suffix.lower() not in ({'.jpg', '.jpeg'} if details['format'] == 'JPEG' else {FORMATS[details['format']]}):
        raise ValueError('Destination extension does not match output format')
    fd, temporary = tempfile.mkstemp(prefix='.mcptoai-image-', dir=dest.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, dest)
        else:
            os.link(temporary, dest)  # atomic no-clobber, even if a file appeared meanwhile
        details['saved_to'] = str(dest)
        return details
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
