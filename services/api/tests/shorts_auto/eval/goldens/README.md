# Auto-Shorts LLM goldens

Hand-curated "ideal" scene picks per fixture video, used by
`services/api/scripts/eval_shorts_auto_llm.py` to gate prompt changes.

## File shape

```json
{
  "video_id": "gd_abc123",
  "scene_corpus": [ /* array of SceneDocument dicts, typically from OS export */ ],
  "mode": "both",
  "ideal_scene_ids": ["gd_abc123_scene_003", "gd_abc123_scene_007"],
  "prompt_version": "2026-04-24-v1"
}
```

## How to produce a golden

1. Pick a staging video with rich captions + transcripts (≥ 5 min, multiple product segments).
2. Export its scene corpus from OpenSearch:
   ```bash
   curl "$OS/heimdex_scenes/_search?size=1000&q=video_id:gd_..." | jq '.hits.hits[]._source' > corpus.json
   ```
3. Watch the video + choose 4-6 scene_ids that should appear in a ~60s short. Focus on clear
   product demonstrations, punchy hooks, and unique visuals — avoid dead air / intros.
4. Save as `tests/shorts_auto/eval/goldens/<video_id>.json` with the schema above.
5. Commit (small JSON; no video files).

## Running

```bash
cd services/api && source .venv/bin/activate
OPENAI_API_KEY=sk-... python -m scripts.eval_shorts_auto_llm \
    --fixtures tests/shorts_auto/eval/goldens \
    --min-jaccard 0.5
```

Prints per-fixture Jaccard overlap. Exits 1 if any fixture falls below
`--min-jaccard`. Run manually on prompt bumps; the CI suite does NOT
invoke this (needs a real key + costs money).

## When to bump goldens

- After an accepted prompt change, if product review signs off that the
  new picks are objectively better than the old ideals, update
  `ideal_scene_ids` and bump `prompt_version` in the fixture.
- Do NOT rubber-stamp goldens to a worse pass rate. If mean Jaccard is
  dropping, that's a regression worth reviewing.
