from app.config import get_settings  # noqa: F401 — re-exported for test patching
from app.modules.search.client import get_opensearch_client  # noqa: F401 — re-exported for test patching
from app.modules.search.scene_facets import SceneFacetsMixin
from app.modules.search.scene_index import SceneIndexMixin
from app.modules.search.scene_ingest import SceneIngestMixin
from app.modules.search.scene_query import SceneQueryMixin


class SceneSearchClient(
    SceneIndexMixin,
    SceneIngestMixin,
    SceneQueryMixin,
    SceneFacetsMixin,
):
    EMBEDDING_DIMENSION: int = 1024
    VISUAL_EMBEDDING_DIMENSION: int = 768
    COLOR_EMBEDDING_DIMENSION: int = 27
    INDEX_VERSION: str = "v5"

    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = get_opensearch_client()
        self.alias_name = f"{self.settings.opensearch_index_prefix}_scenes"
        self.index_name = f"{self.alias_name}_{self.INDEX_VERSION}"

    async def close(self) -> None:
        await self.client.close()
