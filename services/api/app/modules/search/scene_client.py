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
    INDEX_VERSION: str = "v3"
