# pyright: reportMissingTypeStubs=false

from heimdex_worker_sdk.content_type import (
    classify_mime,
    is_image,
    is_supported_mime,
    is_video,
)


def test_classify_mime_video_types() -> None:
    assert classify_mime("video/mp4") == "video"
    assert classify_mime("video/quicktime") == "video"
    assert classify_mime("video/x-msvideo") == "video"
    assert classify_mime("video/webm") == "video"


def test_classify_mime_image_types() -> None:
    assert classify_mime("image/jpeg") == "image"
    assert classify_mime("image/png") == "image"
    assert classify_mime("image/webp") == "image"


def test_classify_mime_unknown() -> None:
    assert classify_mime("application/pdf") == "unknown"
    assert classify_mime("text/plain") == "unknown"
    assert classify_mime("") == "unknown"


def test_is_supported_mime() -> None:
    assert is_supported_mime("video/mp4") is True
    assert is_supported_mime("image/jpeg") is True
    assert is_supported_mime("application/pdf") is False


def test_is_image() -> None:
    assert is_image("image/jpeg") is True
    assert is_image("image/png") is True
    assert is_image("image/webp") is True
    assert is_image("video/mp4") is False


def test_is_video() -> None:
    assert is_video("video/mp4") is True
    assert is_video("video/quicktime") is True
    assert is_video("image/jpeg") is False


def test_api_reexport() -> None:
    from app.modules.content_type import classify_mime as api_classify_mime

    assert api_classify_mime("video/mp4") == classify_mime("video/mp4")
    assert api_classify_mime("image/jpeg") == classify_mime("image/jpeg")
    assert api_classify_mime("application/pdf") == classify_mime("application/pdf")
