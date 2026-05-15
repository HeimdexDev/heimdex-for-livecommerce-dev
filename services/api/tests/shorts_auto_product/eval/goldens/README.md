# shorts-auto product v2 — golden eval set

Hand-curated ground truth for the product-anchored shorts pipeline.
The eval harness at `services/api/scripts/eval_shorts_auto_product.py`
(landed in a later phase) consumes these to gate prompt and
threshold changes.

> Goldens are **devorg-curated on staging**, not synthetic. Curating
> against real Korean live-commerce content is the whole point —
> synthetic goldens would not catch the failure modes the hard-gates
> in `.claude/plans/shorts-auto-product-v2.md` §14 are designed to
> surface.

## When to run the eval

The eval is **not** in CI — it spends real OpenAI + Aircloud GPU
budget. It runs on demand, gated by:

1. Any bump of `EnumerationPrompt.VERSION` in `heimdex-media-contracts`
   (per plan §9 rule 5; whoever bumps owns the run).
2. Any change to `enumeration_version` or `tracker_version` constants
   in `heimdex_media_pipelines.product_enum` /
   `heimdex_media_pipelines.product_track`.
3. The Phase 2 → Phase 3 calibration gate before the prod rollout
   flag `auto_shorts_product_v2_enabled` is allowed to flip on prod
   (plan §11 phase table; §14 risks: SigLIP2 used off-label).

## Calibration thresholds (gate prod rollout)

Per the plan's hard-gate decisions:

| Metric                    | Floor      | Failure action                          |
|---------------------------|------------|-----------------------------------------|
| Enumeration recall        | ≥ 0.85     | Swap SigLIP2 → DINOv2 before prod       |
| Enumeration precision     | ≥ 0.80     | Fall back to gpt-4o (from gpt-4o-mini)  |
| Mean window IoU per prod  | ≥ 0.60     | Swap SigLIP2 → DINOv2 before prod       |

Failing any of these does **not** mean delaying — it means flipping
to the documented fallback configuration before flipping the flag.

## Coverage targets (v1)

Three livecommerce categories — the platform's biggest by volume.
Aim for 3-5 goldens per category at v1; expand reactively when
soak surfaces category-specific complaints.

| Category    | Folder         | v1 target |
|-------------|----------------|-----------|
| Cosmetics   | `cosmetics/`   | 5 videos  |
| Fashion     | `fashion/`     | 3 videos  |
| Food        | `food/`        | 3 videos  |

## Golden file schema

One JSON file per video. Filename: `{org_slug}_{video_id}.json`.

```jsonc
{
  "$schema_version": "1",
  "video_id": "gd_1ABcDef...",
  "org_slug": "devorg",
  "category": "cosmetics",
  "authored_at": "2026-05-15T10:00:00Z",
  "authored_by": "user@heimdex.dev",

  // Versions this golden was authored against. The eval harness must
  // refuse to run if the live versions disagree without an explicit
  // --allow-version-drift flag.
  "enumeration_prompt_version": "v1.0",
  "enumeration_version": "v1.0",
  "tracker_version": "v1.0",

  // Ground truth — list every product the host actively presents.
  // Indirect mentions, sponsor banners, and host accessories MUST
  // NOT appear here (they're the negative examples the enumerator
  // is being graded on excluding).
  "expected_products": [
    {
      "label_kr": "핑크 세럼 병",
      "label_en_hint": "pink rectangular serum bottle",
      "first_appearance_ms": 14200,
      "expected_appearance_count_min": 4,
      "expected_total_seconds_min": 28,
      "category_hint": "skincare"
    }
  ],

  // For each expected product, the ideal final-clip windows the
  // pipeline should select within a 60s preset. Window IoU is
  // computed against this set per duration_preset.
  "expected_clip_for_product": [
    {
      "label_kr": "핑크 세럼 병",
      "duration_preset_sec": 60,
      "ideal_window_set": [
        { "scene_id": "gd_1A_scene_007", "start_ms":  18400, "end_ms":  29200 },
        { "scene_id": "gd_1A_scene_012", "start_ms":  74100, "end_ms":  91500 },
        { "scene_id": "gd_1A_scene_018", "start_ms": 138600, "end_ms": 156800 }
      ]
    }
  ],

  // Optional: explicit negative examples to score precision. Items
  // here SHOULD NOT appear in the catalog. Helps catch host-accessory
  // and background-prop pollution.
  "expected_negatives": [
    "host's gold watch",
    "sponsor mug on desk",
    "studio ring light"
  ]
}
```

## Authoring workflow (devorg, on staging)

1. Pick a representative video on `devorg.app.heimdexdemo.dev` covering
   the target category. Prefer 30-60 minute videos with 3-8 distinct
   products and at least one obvious host-accessory negative example.
2. Watch the video and fill `expected_products` + `expected_negatives`
   with the source-of-truth list. Do **not** look at any pipeline
   output yet — bias the LLM by inspecting its output and you've
   ruined the golden.
3. For each expected product, scrub the timeline and capture the
   ideal `ideal_window_set` for the 60s preset. Optional: add 30s
   and 90s presets if the video supports it.
4. Commit the JSON file under the appropriate category folder.
5. Run the eval harness against the new golden + the existing set
   to confirm metrics still pass before merging.

## Eval metrics computed

- **Enumeration recall**: proportion of `expected_products` surfaced
  in the catalog (label match via cosine sim of LLM-label embeddings,
  threshold 0.65 — matches the spec authoring-vs-runtime label drift).
- **Enumeration precision**: 1 − (count of catalog entries matching
  any `expected_negatives` label / total catalog entries).
- **Window IoU** per (product × duration_preset): IoU of the
  pipeline's selected windows vs `ideal_window_set`. Mean across all
  products per video, then across videos.

A run is a **pass** if all three metrics meet the floors in the
calibration table above. Any failure flags the run output for review
and prevents the tracker_version / prompt_version bump from shipping.

## Storage rules

- Goldens are checked into the repo (this directory).
- The video files themselves are **not** checked in — they live in
  the org's S3 bucket. The eval harness pulls them via the same
  `drive_files` lookup the API uses.
- Never check in screenshots or crops from the source video.
  Goldens describe expectations; they don't carry pixel data.
