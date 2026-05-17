from dataclasses import dataclass
from pathlib import Path
@dataclass(frozen=True)
class ImageMetadata:
    width: int
    height: int
    orientation: str
    format: str


@dataclass(frozen=True)
class ParsedFilename:
    tokens: list[str]
    raw_stem: str


def extract_image_metadata(path: Path) -> ImageMetadata:
    from PIL import Image

    img = Image.open(path)
    w, h = img.size
    fmt = (img.format or "UNKNOWN").upper()
    if w > h:
        orientation = "landscape"
    elif h > w:
        orientation = "portrait"
    else:
        orientation = "square"
    return ImageMetadata(width=w, height=h, orientation=orientation, format=fmt)


def parse_filename(filename: str) -> ParsedFilename:
    import re

    stem = Path(filename).stem
    tokens = [t for t in re.split(r"[_\-\s.\(\)]+", stem) if t]
    return ParsedFilename(tokens=tokens, raw_stem=stem)
