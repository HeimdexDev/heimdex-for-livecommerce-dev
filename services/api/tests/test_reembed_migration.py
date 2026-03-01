"""
Unit tests for the re-embedding migration script logic (Phase 3).

Tests cover:
1. INDEX_VERSION is bumped to v2
2. Embedding version constant matches expected value
3. Scene client creates v2 index name correctly
4. build_embedding_text integration in migration context
5. Index naming after version bump

Run with: pytest tests/test_reembed_migration.py -v
"""
import pytest
from unittest.mock import patch, MagicMock

from app.modules.search.scene_client import SceneSearchClient
from app.modules.ingest.service import build_embedding_text
from scripts.reembed_scenes import EMBEDDING_VERSION


class TestReembedMigration:
    """Tests for Phase 3 migration configuration and logic."""

    def test_index_version_is_v3(self):
        """INDEX_VERSION should be v3 after adding visual_embedding field."""
        assert SceneSearchClient.INDEX_VERSION == "v3"

    def test_embedding_version_constant(self):
        """Migration stamps docs with v2_caption."""
        assert EMBEDDING_VERSION == "v2_caption"

    @patch("app.modules.search.scene_client.get_opensearch_client")
    @patch("app.modules.search.scene_client.get_settings")
    def test_scene_client_index_name_v3(self, mock_settings, mock_get_client):
        """SceneSearchClient should construct v3 index name."""
        settings = MagicMock()
        settings.opensearch_index_prefix = "heimdex"
        mock_settings.return_value = settings
        mock_get_client.return_value = MagicMock()

        client = SceneSearchClient()
        assert client.alias_name == "heimdex_scenes"
        assert client.index_name == "heimdex_scenes_v3"

    def test_build_embedding_text_for_migration(self):
        """build_embedding_text produces expected output for typical scene data."""
        # Typical Korean scene from staging
        result = build_embedding_text(
            transcript_norm="안녕하세요 여러분 오늘은 이 제품을 소개해 드리겠습니다",
            ocr_norm="30% 할인 특가",
            caption_norm="라이브 방송에서 화장품을 소개하는 여성",
        )
        # Caption first
        assert result.startswith("라이브 방송에서")
        # All three parts present
        assert "안녕하세요" in result
        assert "할인" in result

    def test_build_embedding_text_caption_only_scene(self):
        """Scenes with only caption (no transcript/ocr) should still get embedded."""
        result = build_embedding_text(
            transcript_norm="",
            ocr_norm="",
            caption_norm="상품 클로즈업 장면",
        )
        assert result == "상품 클로즈업 장면"

    def test_build_embedding_text_empty_scene(self):
        """Scenes with no text should return empty string (no embedding)."""
        result = build_embedding_text(
            transcript_norm="",
            ocr_norm="",
            caption_norm="",
        )
        assert result == ""

    def test_migration_doc_transform(self):
        """Verify the expected transformation of a scene doc during migration."""
        # Simulate what the migration script does for each doc
        source_doc = {
            "org_id": "test-org",
            "scene_id": "vid1_scene_0",
            "transcript_norm": "hello world",
            "ocr_text_norm": "SALE",
            "scene_caption": "a person speaking",
            "embedding_vector": [0.1] * 1024,  # old embedding
        }

        # Migration builds new embedding text
        text = build_embedding_text(
            transcript_norm=source_doc["transcript_norm"],
            ocr_norm=source_doc["ocr_text_norm"],
            caption_norm=source_doc["scene_caption"],
        )

        # Expected: caption first
        assert text == "a person speaking hello world SALE"

        # Migration stamps embedding_version
        new_doc = dict(source_doc)
        new_doc["embedding_version"] = EMBEDDING_VERSION
        assert new_doc["embedding_version"] == "v2_caption"

    def test_alias_name_unchanged(self):
        """Alias name should NOT change when INDEX_VERSION bumps."""
        # The alias is the stable reference that all reads use
        with patch("app.modules.search.scene_client.get_opensearch_client"):
            with patch("app.modules.search.scene_client.get_settings") as mock:
                settings = MagicMock()
                settings.opensearch_index_prefix = "heimdex"
                mock.return_value = settings

                client = SceneSearchClient()
                # Alias stays the same regardless of version
                assert client.alias_name == "heimdex_scenes"
                assert "v2" not in client.alias_name
