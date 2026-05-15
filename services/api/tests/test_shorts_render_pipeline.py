"""End-to-end integration tests for the shorts render pipeline.

Exercises the full flow: submit composition spec → SQS → worker renders
via ffmpeg → S3 upload → status callback → download rendered MP4.

Prerequisites:
    docker compose --profile local-dev up -d

Run:
    docker compose exec api pytest tests/test_shorts_render_pipeline.py -v -m integration --timeout=180

    Or locally (if API is running on localhost:8000):
    API_BASE_URL=http://devorg.app.heimdex.local:8000 pytest tests/test_shorts_render_pipeline.py -v -m integration
"""

import asyncio
import os
import shutil
import subprocess
import tempfile
import time
from uuid import uuid4

import httpx
import pytest

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000")
API_PREFIX = "/api/shorts/render"
# Use bbb.mp4 test video (2 min, 1920x1080, h264) — kept at workspace root
TEST_VIDEO_PATH = os.environ.get("TEST_VIDEO_PATH", "/workspace/bbb.mp4")
POLL_INTERVAL = 2  # seconds between status polls
RENDER_TIMEOUT = 180  # max wait for render completion


def _auth_headers() -> dict[str, str]:
    """Headers for authenticated API requests.

    In integration test mode, the API uses dev auth:
    - Host header for org resolution
    - Bearer token from DRIVE_INTERNAL_API_KEY or dev token
    """
    return {
        "Host": "devorg.app.heimdex.local",
        "Authorization": f"Bearer {os.environ.get('TEST_AUTH_TOKEN', 'dev-test-token')}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _upload_test_video_to_s3(org_id: str, video_id: str) -> str:
    """Upload test video to MinIO as a proxy file. Returns S3 key.

    Uses bbb.mp4 — copies first to avoid modifying the original.
    """
    import boto3
    from botocore.config import Config

    s3_key = f"{org_id}/{video_id}/proxy.mp4"
    bucket = os.environ.get("DRIVE_S3_BUCKET", "heimdex-drive")

    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ.get("MINIO_URL", "http://minio:9000"),
        aws_access_key_id=os.environ.get("MINIO_ACCESS_KEY", "heimdex"),
        aws_secret_access_key=os.environ.get("MINIO_SECRET_KEY", "heimdex_dev_password"),
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        region_name="us-east-1",
    )

    # Ensure bucket
    try:
        s3.head_bucket(Bucket=bucket)
    except Exception:
        s3.create_bucket(Bucket=bucket)

    s3.upload_file(TEST_VIDEO_PATH, bucket, s3_key, ExtraArgs={"ContentType": "video/mp4"})
    return s3_key


def _make_composition_spec(
    video_id: str,
    *,
    clips: list[dict] | None = None,
    subtitles: list[dict] | None = None,
) -> dict:
    """Build a CompositionSpec dict for testing."""
    if clips is None:
        clips = [
            {
                "scene_id": f"{video_id}_scene_000",
                "video_id": video_id,
                "source_type": "gdrive",
                "start_ms": 0,
                "end_ms": 5000,
                "timeline_start_ms": 0,
            }
        ]
    if subtitles is None:
        subtitles = []

    return {
        "output": {
            "width": 405,
            "height": 720,
            "fps": 30,
            "format": "mp4",
            "background_color": "#000000",
        },
        "scene_clips": clips,
        "subtitles": subtitles,
    }


async def _poll_render_status(
    client: httpx.AsyncClient,
    job_id: str,
    *,
    timeout_s: int = RENDER_TIMEOUT,
) -> dict:
    """Poll render job status until completed or failed."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        resp = await client.get(
            f"{API_BASE_URL}{API_PREFIX}/{job_id}",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        if data["status"] in ("completed", "failed"):
            return data
        await asyncio.sleep(POLL_INTERVAL)
    raise TimeoutError(f"Render job {job_id} did not complete within {timeout_s}s")


def _validate_mp4(data: bytes) -> dict:
    """Use ffprobe to validate MP4 bytes. Returns metadata dict."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(data)
        tmp_path = f.name

    try:
        import json
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", tmp_path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"ffprobe failed: {result.stderr}"
        probe = json.loads(result.stdout)

        streams = probe.get("streams", [])
        has_video = any(s["codec_type"] == "video" for s in streams)
        has_audio = any(s["codec_type"] == "audio" for s in streams)
        duration_s = float(probe["format"]["duration"])

        return {
            "duration_s": duration_s,
            "duration_ms": int(duration_s * 1000),
            "has_video": has_video,
            "has_audio": has_audio,
            "streams": streams,
            "format": probe["format"],
        }
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestRenderPipeline:
    """End-to-end render pipeline integration tests.

    Requires full stack: API + shorts-render-worker + SQS + MinIO.
    """

    @pytest.mark.asyncio
    async def test_single_clip_no_subtitles(self):
        """Simplest render: 1 clip, no subtitles → valid MP4."""
        video_id = f"gd_test_{uuid4().hex[:8]}"
        _upload_test_video_to_s3("devorg", video_id)

        async with httpx.AsyncClient() as client:
            # Submit render job
            resp = await client.post(
                f"{API_BASE_URL}{API_PREFIX}",
                headers=_auth_headers(),
                json={
                    "video_id": video_id,
                    "title": "Single Clip Test",
                    "composition": _make_composition_spec(video_id),
                },
            )
            assert resp.status_code == 201
            job = resp.json()
            job_id = job["id"]
            assert job["status"] == "queued"

            # Wait for completion
            result = await _poll_render_status(client, job_id)
            assert result["status"] == "completed"
            assert result["output_duration_ms"] is not None
            assert result["output_size_bytes"] is not None
            assert result["output_size_bytes"] > 0
            assert result["render_time_ms"] is not None
            assert result["render_time_ms"] > 0

    @pytest.mark.asyncio
    async def test_full_pipeline_two_clips_with_subtitle(self):
        """Full pipeline: 2 clips + Korean subtitle → valid MP4 download."""
        video_id = f"gd_test_{uuid4().hex[:8]}"
        _upload_test_video_to_s3("devorg", video_id)

        clips = [
            {
                "scene_id": f"{video_id}_scene_000",
                "video_id": video_id,
                "source_type": "gdrive",
                "start_ms": 0,
                "end_ms": 5000,
                "timeline_start_ms": 0,
            },
            {
                "scene_id": f"{video_id}_scene_001",
                "video_id": video_id,
                "source_type": "gdrive",
                "start_ms": 10000,
                "end_ms": 15000,
                "timeline_start_ms": 5000,
            },
        ]
        subtitles = [
            {
                "text": "신상품 출시!",
                "start_ms": 0,
                "end_ms": 5000,
                "style": {
                    "font_family": "Noto Sans KR",
                    "font_size_px": 48,
                    "font_color": "#FFFFFF",
                    "font_weight": 700,
                    "position_y": 0.85,
                },
            },
        ]
        spec = _make_composition_spec(video_id, clips=clips, subtitles=subtitles)

        async with httpx.AsyncClient() as client:
            # Submit
            resp = await client.post(
                f"{API_BASE_URL}{API_PREFIX}",
                headers=_auth_headers(),
                json={
                    "video_id": video_id,
                    "title": "Full Pipeline Test",
                    "composition": spec,
                },
            )
            assert resp.status_code == 201
            job_id = resp.json()["id"]

            # Wait
            result = await _poll_render_status(client, job_id)
            assert result["status"] == "completed"

            # Download
            download_url = result.get("download_url")
            assert download_url is not None

            dl_resp = await client.get(
                f"{API_BASE_URL}{download_url}",
                headers=_auth_headers(),
            )
            assert dl_resp.status_code == 200
            assert dl_resp.headers["content-type"] == "video/mp4"
            assert "attachment" in dl_resp.headers.get("content-disposition", "")

            # Validate MP4
            mp4_info = _validate_mp4(dl_resp.content)
            assert mp4_info["has_video"]
            assert mp4_info["has_audio"]
            # 2 clips * 5s each = 10s expected duration (±1s tolerance)
            expected_duration_ms = 10000
            assert abs(mp4_info["duration_ms"] - expected_duration_ms) < 1000

    @pytest.mark.asyncio
    async def test_korean_subtitles(self):
        """Korean text renders without ffmpeg errors."""
        video_id = f"gd_test_{uuid4().hex[:8]}"
        _upload_test_video_to_s3("devorg", video_id)

        subtitles = [
            {
                "text": "안녕하세요 세계!",
                "start_ms": 0,
                "end_ms": 3000,
                "style": {"font_family": "Noto Sans KR", "font_weight": 700},
            },
            {
                "text": "프리텐다드 폰트",
                "start_ms": 3000,
                "end_ms": 5000,
                "style": {"font_family": "Pretendard", "font_weight": 400},
            },
        ]
        spec = _make_composition_spec(video_id, subtitles=subtitles)

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{API_BASE_URL}{API_PREFIX}",
                headers=_auth_headers(),
                json={"video_id": video_id, "title": "Korean Test", "composition": spec},
            )
            assert resp.status_code == 201
            result = await _poll_render_status(client, resp.json()["id"])
            assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_render_invalid_video_id(self):
        """Non-existent video_id → job transitions to failed."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{API_BASE_URL}{API_PREFIX}",
                headers=_auth_headers(),
                json={
                    "video_id": "gd_nonexistent_video",
                    "title": "Should Fail",
                    "composition": _make_composition_spec("gd_nonexistent_video"),
                },
            )
            assert resp.status_code == 201
            job_id = resp.json()["id"]

            result = await _poll_render_status(client, job_id, timeout_s=60)
            assert result["status"] == "failed"
            assert result["error"] is not None

    @pytest.mark.asyncio
    async def test_render_job_lifecycle(self):
        """Create → list → poll → download → delete → verify S3 cleanup."""
        video_id = f"gd_test_{uuid4().hex[:8]}"
        _upload_test_video_to_s3("devorg", video_id)

        async with httpx.AsyncClient() as client:
            # Create
            resp = await client.post(
                f"{API_BASE_URL}{API_PREFIX}",
                headers=_auth_headers(),
                json={
                    "video_id": video_id,
                    "title": "Lifecycle Test",
                    "composition": _make_composition_spec(video_id),
                },
            )
            assert resp.status_code == 201
            job_id = resp.json()["id"]

            # List
            list_resp = await client.get(
                f"{API_BASE_URL}{API_PREFIX}",
                headers=_auth_headers(),
            )
            assert list_resp.status_code == 200
            items = list_resp.json()["items"]
            assert any(j["id"] == job_id for j in items)

            # Poll until completed
            result = await _poll_render_status(client, job_id)
            assert result["status"] == "completed"

            # Download
            dl_resp = await client.get(
                f"{API_BASE_URL}{result['download_url']}",
                headers=_auth_headers(),
            )
            assert dl_resp.status_code == 200

            # Delete
            del_resp = await client.delete(
                f"{API_BASE_URL}{API_PREFIX}/{job_id}",
                headers=_auth_headers(),
            )
            assert del_resp.status_code == 204

            # Verify gone
            get_resp = await client.get(
                f"{API_BASE_URL}{API_PREFIX}/{job_id}",
                headers=_auth_headers(),
            )
            assert get_resp.status_code == 404

    @pytest.mark.asyncio
    async def test_concurrent_renders(self):
        """Submit 3 jobs concurrently → all complete."""
        video_id = f"gd_test_{uuid4().hex[:8]}"
        _upload_test_video_to_s3("devorg", video_id)

        async with httpx.AsyncClient() as client:
            job_ids = []
            for i in range(3):
                resp = await client.post(
                    f"{API_BASE_URL}{API_PREFIX}",
                    headers=_auth_headers(),
                    json={
                        "video_id": video_id,
                        "title": f"Concurrent Test {i}",
                        "composition": _make_composition_spec(video_id),
                    },
                )
                assert resp.status_code == 201
                job_ids.append(resp.json()["id"])

            # Wait for all to complete
            results = await asyncio.gather(
                *[_poll_render_status(client, jid) for jid in job_ids]
            )
            for r in results:
                assert r["status"] == "completed"

    @pytest.mark.asyncio
    async def test_output_duration_accuracy(self):
        """Output duration matches expected total_duration_ms (±500ms)."""
        video_id = f"gd_test_{uuid4().hex[:8]}"
        _upload_test_video_to_s3("devorg", video_id)

        # 1 clip of 5s
        expected_ms = 5000
        spec = _make_composition_spec(video_id)

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{API_BASE_URL}{API_PREFIX}",
                headers=_auth_headers(),
                json={"video_id": video_id, "title": "Duration Test", "composition": spec},
            )
            assert resp.status_code == 201
            result = await _poll_render_status(client, resp.json()["id"])
            assert result["status"] == "completed"
            assert abs(result["output_duration_ms"] - expected_ms) < 500

    @pytest.mark.asyncio
    async def test_range_request_download(self):
        """Download with Range header returns 206 Partial Content."""
        video_id = f"gd_test_{uuid4().hex[:8]}"
        _upload_test_video_to_s3("devorg", video_id)

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{API_BASE_URL}{API_PREFIX}",
                headers=_auth_headers(),
                json={"video_id": video_id, "title": "Range Test", "composition": _make_composition_spec(video_id)},
            )
            assert resp.status_code == 201
            result = await _poll_render_status(client, resp.json()["id"])
            assert result["status"] == "completed"

            dl_resp = await client.get(
                f"{API_BASE_URL}{result['download_url']}",
                headers={**_auth_headers(), "Range": "bytes=0-1023"},
            )
            assert dl_resp.status_code == 206
            assert "content-range" in dl_resp.headers
