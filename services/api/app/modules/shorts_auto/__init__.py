"""Auto-shorts: AI-driven mode-aware clip selection over the existing
shorts render pipeline.

Loose-coupling rules (see ``.claude/plans/auto-shorts-v1.md`` §3):
  - Scoring + concat live in ``heimdex_media_contracts.shorts``.
  - This module **only** delegates to ``shorts_render`` via its public
    ``ShortsRenderService.create_render_job(...)`` interface. Never
    import ``shorts_render.models``, ``shorts_render.repository``, or
    other internals.
  - Face data is read through the OpenSearch scene index, never via
    ``app.modules.face`` repositories.
"""
