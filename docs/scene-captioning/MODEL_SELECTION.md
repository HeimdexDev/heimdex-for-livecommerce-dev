# Phase B — Model Selection

**Date:** 2026-02-20
**Status:** Complete
**Purpose:** Compare small VLMs for CPU-first scene captioning. Recommend primary + fallback model.

---

## Constraints

- CPU inference by default (GPU optional)
- RAM budget: under 3 GB per worker
- Docker-deployable
- Korean + English content (livecommerce domain)
- No paid AI APIs
- Short captions (1-2 sentences per scene)

---

## Candidates Evaluated

| | BLIP-base | Moondream2 | Florence-2-base | SmolVLM-500M | InternVL2-1B |
|---|---|---|---|---|---|
| **HF ID** | Salesforce/blip-image-captioning-base | vikhyatk/moondream2 | microsoft/Florence-2-base | HuggingFaceTB/SmolVLM-500M-Instruct | OpenGVLab/InternVL2-1B |
| **Parameters** | 224M | ~2B | **230M** | 500M | 900M |
| **Disk** | 990 MB | 3.85 GB | **463 MB** | ~1.2 GB | 1.88 GB |
| **CPU RAM (fp32)** | ~1.5 GB | ~4.2 GB | **~1.0 GB** | ~2-3 GB | ~2.5-3.5 GB |
| **Under 3 GB?** | Yes | No (fp16) | **Yes** | Yes | Tight (needs int8) |
| **CPU latency/image** | ~4-8s | >=7s | **~3-6s** | ~5-15s | ~10-20s |
| **License** | BSD-3 | Apache 2.0 | **MIT** | Apache 2.0 | MIT |
| **COCO CIDEr** | 133.3 (ft) | N/A | **133.0 (zero-shot)** | N/A | N/A |
| **Korean output** | No | No | No | No | **Yes (native)** |
| **Instruction prompts** | Prefix-only | .query() API | Task tokens only | Chat template | Chat template |
| **Docker complexity** | Simple | Medium | Medium | **Simplest** | Medium |
| **Active maintenance** | No (2022) | Yes | Stable | Yes | Yes |

---

## Detailed Analysis

### BLIP-base — Eliminated

- 2022 model, no active development
- English-only BERT tokenizer — Korean characters not in vocabulary
- No instruction following (prefix completion only)
- Outperformed by Florence-2-base at similar parameter count

### Moondream2 — Eliminated

- 3.85 GB disk + 4.2 GB RAM **exceeds 3 GB budget**
- English-only (confirmed by maintainers, multilingual is roadmap only)
- Int4 QAT variant (2.4 GB) requires native `moondream` package, not HF transformers
- Best prompt interface (.query() API) but memory disqualifies it

### Florence-2-base — Recommended Fallback

**Strengths:**
- Smallest footprint: 463 MB disk, ~1.0 GB RAM
- Fastest CPU inference: ~3-6s/image (greedy)
- COCO CIDEr 133.0 zero-shot — outperforms Flamingo-80B at 0.3% the parameters
- MIT license, Microsoft-maintained

**Limitations:**
- English-only output (Korean requires post-translation)
- Fixed task tokens only (`<CAPTION>`, `<DETAILED_CAPTION>`, `<MORE_DETAILED_CAPTION>`)
- Cannot follow free-text instructions like "focus on the product"
- Requires `trust_remote_code=True`

**Best for:** English-only pipeline, maximum throughput, smallest Docker image.

### SmolVLM-500M-Instruct — Strong Alternative

**Strengths:**
- Best instruction-following interface (full chat template)
- Apache 2.0 license, no `trust_remote_code` needed
- Cleanest Docker packaging of all candidates
- OpenVINO optimization available (12x speedup on Intel CPU → sub-second TTFT)

**Limitations:**
- English-only (model card explicitly states this)
- No COCO CIDEr benchmark published
- 500M params may produce generic captions for niche product categories
- Unoptimized CPU: 5-15s/image

**Best for:** English-only pipeline where instruction quality matters more than raw speed.

### InternVL2-1B — Primary Recommendation

**Strengths:**
- **Only model with native Korean output** — eliminates translation entirely
- CCBench score 75.7 (highest CJK cultural understanding)
- Full instruction-following via `.chat()` API — Korean and English prompts
- MIT license, actively maintained
- OCRBench 754 (highest — reads text in images well, relevant for livecommerce product labels)

**Limitations:**
- Largest footprint: 1.88 GB disk, ~2.5-3.5 GB RAM (bf16)
- Slowest default CPU: ~10-20s/image with dynamic tiling
- Requires `trust_remote_code=True`
- Dynamic tiling adds complexity

**Mitigation:**
- Set `max_num=1` (disable dynamic tiling) → reduces to ~5-8s/image
- Use int8 quantization → fits comfortably in 3 GB
- Single-tile mode is sufficient for keyframe captioning (frames are already cropped scenes)

---

## Recommendation

### Primary: InternVL2-1B (`OpenGVLab/InternVL2-1B`)

**Rationale:** Heimdex is a Korean-first platform. All video titles, transcripts, and OCR text are Korean. Generating English captions and translating adds latency, cost, and quality loss. InternVL2-1B generates Korean directly:

```python
# Korean prompt → Korean caption
question = '<image>\n이 라이브커머스 장면을 한 문장으로 설명해주세요.'
response = model.chat(tokenizer, pixel_values, question, generation_config)
# → "진행자가 카메라 앞에서 핑크색 립스틱을 시연하고 있습니다."
```

Korean captions are BM25-searchable via the existing `korean_analyzer` (Nori) — no tokenizer changes needed.

**CPU optimization config:**
```python
# Disable dynamic tiling for keyframes (single scene frame, not document)
pixel_values = load_image(frame_path, max_num=1)

# Greedy decoding, short output
generation_config = dict(
    max_new_tokens=64,
    num_beams=1,
    do_sample=False,
)
```

### Fallback: Florence-2-base (`microsoft/Florence-2-base`)

**When to use instead:**
- If InternVL2-1B Korean quality is poor on actual test frames (validate first)
- If memory budget is tighter than expected (Florence-2 uses 60% less RAM)
- If throughput is critical (Florence-2 is 2-3x faster per frame)

English captions from Florence-2 are still BM25-searchable via `standard` analyzer, and embedding text is already English-compatible (`intfloat/multilingual-e5-large`).

---

## Validation Plan (Before Implementation)

Before committing to InternVL2-1B, run this benchmark on 10 real Heimdex keyframes:

```python
# benchmark_caption_models.py
import time, torch
from transformers import AutoModelForCausalLM, AutoProcessor

models = {
    "internvl2-1b": "OpenGVLab/InternVL2-1B",
    "florence2-base": "microsoft/Florence-2-base",
}

test_frames = [
    "beauty_product_demo.jpg",
    "food_review.jpg",
    "fashion_showcase.jpg",
    "walking_tour.jpg",
    # ... 10 representative keyframes from staging
]

for name, model_id in models.items():
    model = load_model(model_id)
    for frame in test_frames:
        start = time.time()
        caption = generate_caption(model, frame)
        latency = time.time() - start
        print(f"{name} | {frame} | {latency:.1f}s | {caption}")
```

**Success criteria:**
- InternVL2-1B generates coherent Korean captions for 8/10 frames
- CPU latency < 15s/frame with `max_num=1`
- RAM stays under 3 GB during inference
- Caption mentions visible product/activity (not generic "a person talking")

---

## Sources

| Source | URL |
|--------|-----|
| BLIP paper | https://arxiv.org/abs/2201.12086 |
| Moondream2 model card | https://huggingface.co/vikhyatk/moondream2 |
| Moondream 4-bit QAT blog | https://moondream.ai/blog/smaller-faster-moondream-with-qat |
| Florence-2 paper | https://arxiv.org/abs/2311.06242 |
| Florence-2-base model card | https://huggingface.co/microsoft/Florence-2-base |
| SmolVLM paper | https://arxiv.org/abs/2504.05299 |
| SmolVLM-500M model card | https://huggingface.co/HuggingFaceTB/SmolVLM-500M-Instruct |
| InternVL2-1B model card | https://huggingface.co/OpenGVLab/InternVL2-1B |
| InternVL2.5 paper | https://arxiv.org/abs/2412.05271 |
