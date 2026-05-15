import pytest

from app.modules.drive.keys import (
    audio_s3_key,
    drive_video_id,
    enrichment_keyframe_s3_key,
    enrichment_keyframe_s3_prefix,
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


class TestAudioS3Key:
    def test_format(self):
        key = audio_s3_key("org-123", "gd_abc123def456ab")
        assert key == "org-123/drive/audio/gd_abc123def456ab/audio.wav"

    def test_ends_with_wav(self):
        key = audio_s3_key("org-123", "gd_abc")
        assert key.endswith(".wav")

    def test_uuid_style_org_id(self):
        key = audio_s3_key("4d20264c-c440-4d69-8613-7d7558ea386b", "gd_abc123")
        assert key.startswith("4d20264c-c440-4d69-8613-7d7558ea386b/drive/audio/")

    def test_contains_video_id(self):
        key = audio_s3_key("org-1", "gd_myvid")
        assert "gd_myvid" in key


class TestEnrichmentKeyframeS3:
    def test_prefix_format(self):
        prefix = enrichment_keyframe_s3_prefix("org-123", "gd_abc123def456ab")
        assert prefix == "org-123/drive/keyframes/gd_abc123def456ab/"

    def test_prefix_ends_with_slash(self):
        prefix = enrichment_keyframe_s3_prefix("org-123", "gd_abc")
        assert prefix.endswith("/")

    def test_key_format(self):
        key = enrichment_keyframe_s3_key("org-123", "gd_abc123", "gd_abc123_scene_001")
        assert key == "org-123/drive/keyframes/gd_abc123/gd_abc123_scene_001.jpg"

    def test_key_ends_with_jpg(self):
        key = enrichment_keyframe_s3_key("org-123", "gd_abc", "gd_abc_scene_000")
        assert key.endswith(".jpg")

    def test_key_lives_under_prefix(self):
        org = "org-123"
        vid = "gd_abc123"
        scene = f"{vid}_scene_002"
        prefix = enrichment_keyframe_s3_prefix(org, vid)
        key = enrichment_keyframe_s3_key(org, vid, scene)
        assert key.startswith(prefix)

    def test_different_scenes_different_keys(self):
        k1 = enrichment_keyframe_s3_key("org-1", "vid-1", "vid-1_scene_000")
        k2 = enrichment_keyframe_s3_key("org-1", "vid-1", "vid-1_scene_001")
        assert k1 != k2

    def test_no_overlap_with_thumbnails(self):
        prefix_kf = enrichment_keyframe_s3_prefix("org-1", "gd_abc")
        prefix_th = thumbnail_s3_prefix("org-1", "gd_abc")
        assert "keyframes" in prefix_kf
        assert "thumbs" in prefix_th
        assert prefix_kf != prefix_th
