# pyright: reportAny=false, reportAttributeAccessIssue=false, reportMissingImports=false, reportMissingParameterType=false, reportUnannotatedClassAttribute=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false, reportUnknownMemberType=false, reportUnknownParameterType=false, reportUnknownVariableType=false

import json
import sys
import tempfile
import types
from pathlib import Path

try:
    from PIL import Image
except ModuleNotFoundError:
    class _FakeImageObject:
        def __init__(self, size: tuple[int, int], fmt: str | None = None):
            self.size = size
            self.format = fmt

        def save(self, fp, format: str):
            payload = {"size": [self.size[0], self.size[1]], "format": format}
            fp.write(json.dumps(payload).encode("utf-8"))

    image_module = types.ModuleType("PIL.Image")
    image_module.new = lambda _mode, size, color=None: _FakeImageObject(size=size)
    image_module.open = lambda path: _FakeImageObject(
        size=tuple(json.loads(Path(path).read_text(encoding="utf-8"))["size"]),
        fmt=json.loads(Path(path).read_text(encoding="utf-8"))["format"],
    )

    pil_module = types.ModuleType("PIL")
    pil_module.Image = image_module
    sys.modules["PIL"] = pil_module
    sys.modules["PIL.Image"] = image_module
    from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "drive-worker" / "src"))

from tasks.image_metadata import extract_image_metadata, parse_filename


def _make_temp_image(size: tuple[int, int], suffix: str, fmt: str) -> Path:
    img = Image.new("RGB", size, color="red")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        img.save(f, format=fmt)
        return Path(f.name)


def test_extract_image_metadata_landscape():
    path = _make_temp_image((1920, 1080), ".jpg", "JPEG")
    try:
        meta = extract_image_metadata(path)
        assert meta.width == 1920
        assert meta.height == 1080
        assert meta.orientation == "landscape"
        assert meta.format == "JPEG"
    finally:
        path.unlink(missing_ok=True)


def test_extract_image_metadata_portrait():
    path = _make_temp_image((1080, 1920), ".png", "PNG")
    try:
        meta = extract_image_metadata(path)
        assert meta.width == 1080
        assert meta.height == 1920
        assert meta.orientation == "portrait"
        assert meta.format == "PNG"
    finally:
        path.unlink(missing_ok=True)


def test_extract_image_metadata_square():
    path = _make_temp_image((512, 512), ".jpg", "JPEG")
    try:
        meta = extract_image_metadata(path)
        assert meta.width == 512
        assert meta.height == 512
        assert meta.orientation == "square"
        assert meta.format == "JPEG"
    finally:
        path.unlink(missing_ok=True)


def test_parse_filename_korean():
    parsed = parse_filename("2024SS_나이키_에어맥스_화이트.jpg")
    assert parsed.tokens == ["2024SS", "나이키", "에어맥스", "화이트"]
    assert parsed.raw_stem == "2024SS_나이키_에어맥스_화이트"


def test_parse_filename_spaces():
    parsed = parse_filename("product photo (front).png")
    assert "product" in parsed.tokens
    assert "photo" in parsed.tokens
    assert "front" in parsed.tokens


def test_parse_filename_dots():
    parsed = parse_filename("img.2024.01.15.jpg")
    assert parsed.tokens == ["img", "2024", "01", "15"]


def test_parse_filename_no_extension():
    parsed = parse_filename("README")
    assert parsed.tokens == ["README"]
