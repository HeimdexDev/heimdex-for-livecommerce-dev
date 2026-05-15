"""Pure data-access layer for shorts-auto product mode v2.

Each repository is org-scoped — every public read/write that takes an
``org_id`` MUST filter on it. Worker callback paths use the
ID-only methods (no user scope, but org guard is preserved through
the job row's ``org_id``).
"""

from app.modules.shorts_auto_product.repositories.appearance import (
    ProductAppearanceRepository,
)
from app.modules.shorts_auto_product.repositories.catalog import (
    ProductCatalogRepository,
)
from app.modules.shorts_auto_product.repositories.cost import (
    ProductScanDailyCostRepository,
)
from app.modules.shorts_auto_product.repositories.job import (
    ProductScanJobRepository,
)

__all__ = [
    "ProductAppearanceRepository",
    "ProductCatalogRepository",
    "ProductScanDailyCostRepository",
    "ProductScanJobRepository",
]
