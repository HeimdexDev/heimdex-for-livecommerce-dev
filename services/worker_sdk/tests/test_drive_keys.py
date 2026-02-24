"""Tests for heimdex_worker_sdk.drive_keys — parity with app.modules.drive.keys."""

import hashlib

import pytest

from heimdex_worker_sdk.drive_keys import (
    audio_s3_key,
    drive_video_id,
    enrichment_keyframe_s3_key,
    enrichment_keyframe_s3_prefix,
    proxy_s3_key,
    scene_manifest_s3_key,
    thumbnail_s3_key,
    thumbnail_s3_prefix,
)


class TestDriveVideoId:
    def test_deterministic(self):
        a = drive_video_id("org1", "file1")
        b = drive_video_id("org1", "file1")
        assert a == b

    def test_format(self):
        vid = drive_video_id("org1", "file1")
        assert vid.startswith("gd_")
        assert len(vid) == 3 + 16  # "gd_" + 16 hex chars

    def test_different_inputs(self):
        a = drive_video_id("org1", "file1")
        b = drive_video_id("org1", "file2")
        c = drive_video_id("org2", "file1")
        assert a != b
        assert a != c

    def test_matches_manual_computation(self):
        digest = hashlib.sha256("org1:file1".encode()).hexdigest()[:16]
        expected = f"gd_{digest}"
        assert drive_video_id("org1", "file1") == expected


class TestS3KeyHelpers:
    def test_proxy_s3_key(self):
        key = proxy_s3_key("org1", "drive1", "gfile1")
        assert key == "org1/drive/drive1/gfile1/proxy.mp4"

    def test_thumbnail_s3_key(self):
        key = thumbnail_s3_key("org1", "vid1", "scene1")
        assert key == "org1/drive/thumbs/vid1/scene1.jpg"

    def test_thumbnail_s3_prefix(self):
        prefix = thumbnail_s3_prefix("org1", "vid1")
        assert prefix == "org1/drive/thumbs/vid1/"

    def test_audio_s3_key(self):
        key = audio_s3_key("org1", "vid1")
        assert key == "org1/drive/audio/vid1/audio.wav"

    def test_enrichment_keyframe_s3_prefix(self):
        prefix = enrichment_keyframe_s3_prefix("org1", "vid1")
        assert prefix == "org1/drive/keyframes/vid1/"

    def test_enrichment_keyframe_s3_key(self):
        key = enrichment_keyframe_s3_key("org1", "vid1", "scene1")
        assert key == "org1/drive/keyframes/vid1/scene1.jpg"

    def test_scene_manifest_s3_key(self):
        key = scene_manifest_s3_key("org1", "vid1")
        assert key == "org1/drive/manifests/vid1/scenes.json"


class TestKeyConsistency:
    """Verify that enrichment key prefix is a proper prefix of enrichment key."""

    def test_keyframe_prefix_matches_key(self):
        prefix = enrichment_keyframe_s3_prefix("org1", "vid1")
        key = enrichment_keyframe_s3_key("org1", "vid1", "scene1")
        assert key.startswith(prefix)

    def test_thumbnail_prefix_matches_key(self):
        prefix = thumbnail_s3_prefix("org1", "vid1")
        key = thumbnail_s3_key("org1", "vid1", "scene1")
        assert key.startswith(prefix)
