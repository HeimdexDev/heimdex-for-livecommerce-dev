"""Wizard child runner — Phase 4 PR #4.

This sub-package is a closed boundary inside ``app.modules.shorts_auto_product``.
The child runner is the in-API-process consumer of ``mode='render_child'``
rows produced by the parent fan-out hook (``internal_router.complete``).

Loose-coupling rules (plan §15):
* The runner does NOT cross-import other ``app.modules.*`` packages.
* The runner CAN import ``heimdex_media_pipelines.product_track``
  (picker + stitch_plan) and ``app.dependencies.get_shorts_render_service``
  — both are explicitly allowed exceptions per the plan, since the
  runner is the API's reuse seam for the same logic that the worker
  uses on the GPU side.
* The runner uses its own module's repos + models for DB ops.

Phase 4 PR #4 (this PR) ships the infrastructure with a STUB processing
step. PR #5 replaces the stub with the real picker + render-enqueue
integration once contracts v0.14.0 is published and the worker refactor
exists to actually populate the parent's appearances. Until PR #5
lands, children claimed by this runner /complete with
``render_job_id=None`` — the wizard frontend (PR #6) is the first
caller that observes this state, so the stubbed semantics never reach
production users.
"""

from app.modules.shorts_auto_product.children.runner import (
    ChildRunner,
    create_child_runner,
)

__all__ = ["ChildRunner", "create_child_runner"]
