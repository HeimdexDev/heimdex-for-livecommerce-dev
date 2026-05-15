"""Auto-shorts product mode v2.

Replaces the heuristic + LLM scorer for ``ScoringMode.PRODUCT`` with a
two-stage lazy pipeline:

1. **Enumeration** (on tab open) — gpt-4o-mini vision over keyframes +
   SigLIP2 clustering produces a per-video ``ProductCatalogEntry`` set.
2. **Tracking + assembly** (on product pick) — SigLIP2 retrieval +
   SAM2 mask propagation produces ``AppearanceWindow`` rows; an LLM
   subset picker selects the best windows fitting the user's
   30/60/90s preset; the resulting ``StitchingPlan`` flows into the
   existing ``ShortsRenderService`` as a ``CompositionSpec``.

Plan: ``.claude/plans/shorts-auto-product-v2.md``.

Boundaries:
* API never imports ``heimdex_media_pipelines``. Worker outputs reach
  the API via Postgres + S3 + ``/internal/products/*`` callbacks only.
* This module never cross-imports from other ``app.modules.*`` —
  shared logic goes to ``app.lib.*``.
* Frontend hits ``/api/shorts/auto/products/*``; types live in
  ``services/web/src/lib/types/shorts-auto-product.ts``.
"""
