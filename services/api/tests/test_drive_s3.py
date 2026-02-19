import pytest

from app.modules.drive.keys import (
    drive_video_id,
    proxy_s3_key,
    thumbnail_s3_key,
    thumbnail_s3_prefix,
)


class TestDriveVideoId:
    def test_deterministic(self):
        vid1 = drive_video_id("org-123", "file-abc")
        vid2 = drive_video_id("org-123", "file-abc")
        assert vid1 == vid2

    def test_gd_prefix(self):
        vid = drive_video_id("org-123", "file-abc")
        assert vid.startswith("gd_")

    def test_16_char_hex_after_prefix(self):
        vid = drive_video_id("org-123", "file-abc")
        hex_part = vid[3:]
        assert len(hex_part) == 16
        int(hex_part, 16)

    def test_different_orgs_different_ids(self):
        vid1 = drive_video_id("org-1", "file-abc")
        vid2 = drive_video_id("org-2", "file-abc")
        assert vid1 != vid2

    def test_different_files_different_ids(self):
        vid1 = drive_video_id("org-1", "file-1")
        vid2 = drive_video_id("org-1", "file-2")
        assert vid1 != vid2


class TestS3KeyGeneration:
    def test_proxy_key_format(self):
        key = proxy_s3_key("org-123", "drive-456", "file-789")
        assert key == "org-123/drive/drive-456/file-789/proxy.mp4"

    def test_thumbnail_key_format(self):
        key = thumbnail_s3_key("org-123", "gd_abc123def456ab", "gd_abc123def456ab_scene_001")
        assert key == "org-123/drive/thumbs/gd_abc123def456ab/gd_abc123def456ab_scene_001.jpg"

    def test_thumbnail_prefix_format(self):
        prefix = thumbnail_s3_prefix("org-123", "gd_abc123def456ab")
        assert prefix == "org-123/drive/thumbs/gd_abc123def456ab/"

    def test_thumbnail_key_matches_router_read_pattern(self):
        org_id = "4d20264c-c440-4d69-8613-7d7558ea386b"
        video_id = drive_video_id(org_id, "1a2b3cGoogleFileId")
        scene_id = f"{video_id}_scene_0"
        key = thumbnail_s3_key(org_id, video_id, scene_id)
        assert key == f"{org_id}/drive/thumbs/{video_id}/{scene_id}.jpg"

    def test_key_contains_all_components(self):
        key = proxy_s3_key("my-org", "my-drive", "my-file")
        assert "my-org" in key
        assert "my-drive" in key
        assert "my-file" in key
        assert key.endswith(".mp4")

    def test_uuid_style_org_id(self):
        key = proxy_s3_key("4d20264c-c440-4d69-8613-7d7558ea386b", "0AMX5qpoGaJvLUk9PVA", "1a2b3c")
        assert key.startswith("4d20264c-c440-4d69-8613-7d7558ea386b/drive/")
