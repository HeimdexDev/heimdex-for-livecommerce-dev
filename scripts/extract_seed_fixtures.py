"""One-off tool: extract keyframes + color data from real videos/images for seed fixtures.

Uses production pipeline (split_scenes + extract_all_keyframes) + color_extraction
to generate deterministic seed fixtures from a folder of real assets.

Designed to run inside the api container (has ffmpeg + pipelines + PIL):

    docker compose run --rm --no-deps \\
      -v "/host/seed:/seed:ro" \\
      --entrypoint python \\
      api /app/../scripts/extract_seed_fixtures.py \\
      --input /seed \\
      --output /app/app/db/seed/fixtures \\
      --per-video 9 \\
      --image-size 640

Inputs:
  --input: folder containing N *.mp4 videos and M *.png/*.jpg images
  --output: fixtures folder (will be created)

Outputs:
  {output}/keyframes/{scene_id}.jpg  — video keyframes
  {output}/images/{scene_id}.jpg     — standalone image scenes (VMD)
  {output}/scenes.json               — metadata + color info
  {output}/color_distribution.json   — per-family count report
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image  # noqa: E402

from heimdex_media_pipelines.scenes.keyframe import extract_all_keyframes  # noqa: E402
from heimdex_media_pipelines.scenes.splitter import split_scenes  # noqa: E402
from heimdex_media_pipelines.transcoding.probe import probe_video  # noqa: E402
from heimdex_media_pipelines.transcoding.proxy import (  # noqa: E402
    make_transcode_decision,
    transcode_to_proxy,
)


# Load color_extraction by file path to avoid triggering app.modules.search.__init__
# (which imports fastapi and other api-only deps not present in worker image).
def _load_color_extraction():
    import importlib.util
    candidates = [
        "/api_src/app/modules/search/color_extraction.py",
        "/app/app/modules/search/color_extraction.py",
    ]
    for path in candidates:
        if os.path.isfile(path):
            spec = importlib.util.spec_from_file_location("color_extraction", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise RuntimeError(f"color_extraction.py not found. Tried: {candidates}")


_color_mod = _load_color_extraction()
COLOR_FAMILIES = _color_mod.COLOR_FAMILIES
colors_to_hex = _color_mod.colors_to_hex
extract_dominant_colors = _color_mod.extract_dominant_colors
family_to_color_histogram = _color_mod.family_to_color_histogram
rgb_to_hsl_histogram = _color_mod.rgb_to_hsl_histogram

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("extract_seed_fixtures")


VIDEO_EXTS = {".mp4", ".mov", ".mkv"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass
class SceneFixture:
    scene_id: str
    video_id: str
    video_title: str
    content_type: str  # "video" or "image"
    keyframe_path: str  # relative to fixtures dir
    start_ms: int
    end_ms: int
    keyframe_timestamp_ms: int
    dominant_colors: list[str] = field(default_factory=list)
    color_embedding: list[float] = field(default_factory=list)
    color_family: str = ""  # dominant family
    image_width: int = 0
    image_height: int = 0


def slugify(name: str) -> str:
    """Make a stable short id from a filename stem (ASCII + hash)."""
    stem = Path(name).stem
    h = hashlib.md5(stem.encode("utf-8")).hexdigest()[:8]
    safe = "".join(ch if ch.isalnum() else "_" for ch in stem)[:32].strip("_")
    return f"{safe}_{h}" if safe else f"asset_{h}"


def resize_for_fixture(src: Path, dst: Path, max_width: int) -> tuple[int, int]:
    """Resize image to max_width (preserve aspect), save as JPEG. Returns (w, h)."""
    with Image.open(src) as img:
        img = img.convert("RGB")
        w, h = img.size
        if w > max_width:
            new_h = int(h * max_width / w)
            img = img.resize((max_width, new_h), Image.LANCZOS)
            w, h = max_width, new_h
        dst.parent.mkdir(parents=True, exist_ok=True)
        img.save(dst, format="JPEG", quality=85, optimize=True)
    return w, h


def sample_evenly(items: list[Any], target: int) -> list[Any]:
    """Pick target evenly-spaced items from a list (keeps endpoints when possible)."""
    n = len(items)
    if n <= target:
        return list(items)
    if target <= 1:
        return [items[n // 2]]
    step = (n - 1) / (target - 1)
    return [items[round(i * step)] for i in range(target)]


def extract_color_data(image_path: Path) -> tuple[list[str], list[float]]:
    """Run production k-means + HSL histogram on an image file."""
    with Image.open(image_path) as img:
        colors, weights = extract_dominant_colors(img, k=5)
    hex_colors = colors_to_hex(colors)
    histogram = rgb_to_hsl_histogram(colors, weights)
    return hex_colors, histogram


def classify_family(color_embedding: list[float]) -> str:
    """Assign the scene to its closest color family by cosine similarity."""
    best_family = "gray"
    best_score = -1.0
    for family in COLOR_FAMILIES:
        family_vec = family_to_color_histogram(family)
        # Both are L2-normalized, so dot product == cosine similarity.
        score = sum(a * b for a, b in zip(color_embedding, family_vec))
        if score > best_score:
            best_score = score
            best_family = family
    return best_family


def ensure_proxy(video_path: Path, proxy_dir: Path) -> Path:
    """Transcode large/high-bitrate videos to a 720p proxy for analysis.

    Mirrors the production drive-transcode-worker flow. If the source is
    already within the proxy envelope (H.264, <=720p, <=2500kbps),
    returns the original path.
    """
    probe = probe_video(video_path)
    decision = make_transcode_decision(probe)
    logger.info("probe video=%s %dx%d codec=%s bitrate_kbps=%d transcode=%s",
                video_path.name, probe.width, probe.height, probe.codec_name,
                probe.bitrate_kbps, decision.should_transcode)

    if not decision.should_transcode:
        return video_path

    proxy_path = proxy_dir / f"{video_path.stem}.proxy.mp4"
    if proxy_path.is_file() and proxy_path.stat().st_size > 0:
        logger.info("proxy_reused path=%s", proxy_path)
        return proxy_path

    logger.info("proxy_start src=%s target=720p", video_path.name)
    transcode_to_proxy(
        input_path=video_path,
        output_path=proxy_path,
        probe=probe,
        decision=decision,
        preset="ultrafast",  # analysis-only proxy; quality trumps speed here
        crf=28,
    )
    logger.info("proxy_done src=%s -> %s (%dMB)",
                video_path.name, proxy_path.name,
                proxy_path.stat().st_size // (1024 * 1024))
    return proxy_path


def process_videos(
    videos: list[Path],
    output_dir: Path,
    per_video: int,
    proxy_dir: Path,
) -> list[SceneFixture]:
    fixtures: list[SceneFixture] = []
    keyframes_dir = output_dir / "keyframes"
    keyframes_dir.mkdir(parents=True, exist_ok=True)
    proxy_dir.mkdir(parents=True, exist_ok=True)

    for idx, video_path in enumerate(sorted(videos), start=1):
        video_id = f"seed_video_{idx:02d}_{slugify(video_path.name)}"
        video_title = video_path.stem

        logger.info("video_start idx=%d name=%s id=%s size=%dMB",
                    idx, video_path.name, video_id,
                    video_path.stat().st_size // (1024 * 1024))

        # Mirror production: transcode to 720p H.264 proxy first, then analyze.
        analysis_path = ensure_proxy(video_path, proxy_dir)

        logger.info("split_start video=%s", video_path.name)
        scenes = split_scenes(
            video_path=str(analysis_path),
            video_id=video_id,
            preset="default",
        )
        logger.info("split_done video=%s total_scenes=%d", video_path.name, len(scenes))

        sampled = sample_evenly(scenes, per_video)
        logger.info("sampled video=%s picked=%d", video_path.name, len(sampled))

        for new_idx, scene in enumerate(sampled):
            scene.index = new_idx
            scene.scene_id = f"{video_id}_scene_{new_idx:03d}"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            extract_all_keyframes(
                video_path=str(analysis_path),
                scenes=sampled,
                out_dir=str(tmp_path),
            )
            for scene in sampled:
                tmp_jpg = tmp_path / f"{scene.scene_id}.jpg"
                if not tmp_jpg.is_file():
                    logger.warning("keyframe_missing scene=%s", scene.scene_id)
                    continue
                final_jpg = keyframes_dir / f"{scene.scene_id}.jpg"
                w, h = resize_for_fixture(tmp_jpg, final_jpg, max_width=640)

                hex_colors, histogram = extract_color_data(final_jpg)
                family = classify_family(histogram)

                fixtures.append(SceneFixture(
                    scene_id=scene.scene_id,
                    video_id=video_id,
                    video_title=video_title,
                    content_type="video",
                    keyframe_path=str(final_jpg.relative_to(output_dir)),
                    start_ms=scene.start_ms,
                    end_ms=scene.end_ms,
                    keyframe_timestamp_ms=scene.keyframe_timestamp_ms,
                    dominant_colors=hex_colors,
                    color_embedding=histogram,
                    color_family=family,
                    image_width=w,
                    image_height=h,
                ))
    return fixtures


def process_images(
    images: list[Path],
    output_dir: Path,
    image_size: int,
) -> list[SceneFixture]:
    fixtures: list[SceneFixture] = []
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    for idx, img_path in enumerate(sorted(images), start=1):
        slug = slugify(img_path.name)
        video_id = f"seed_image_{idx:02d}_{slug}"
        scene_id = f"{video_id}_scene_000"
        final_jpg = images_dir / f"{scene_id}.jpg"

        logger.info("image_process src=%s id=%s", img_path.name, scene_id)
        w, h = resize_for_fixture(img_path, final_jpg, max_width=image_size)

        hex_colors, histogram = extract_color_data(final_jpg)
        family = classify_family(histogram)

        fixtures.append(SceneFixture(
            scene_id=scene_id,
            video_id=video_id,
            video_title=img_path.stem,
            content_type="image",
            keyframe_path=str(final_jpg.relative_to(output_dir)),
            start_ms=0,
            end_ms=0,
            keyframe_timestamp_ms=0,
            dominant_colors=hex_colors,
            color_embedding=histogram,
            color_family=family,
            image_width=w,
            image_height=h,
        ))
    return fixtures


def write_metadata(
    fixtures: list[SceneFixture],
    output_dir: Path,
) -> None:
    # scenes.json: flat list, one entry per scene.
    scenes_payload = {
        "schema_version": "1.0",
        "generator": "scripts/extract_seed_fixtures.py",
        "total_scenes": len(fixtures),
        "video_scenes": sum(1 for f in fixtures if f.content_type == "video"),
        "image_scenes": sum(1 for f in fixtures if f.content_type == "image"),
        "scenes": [
            {
                "scene_id": f.scene_id,
                "video_id": f.video_id,
                "video_title": f.video_title,
                "content_type": f.content_type,
                "keyframe_path": f.keyframe_path,
                "start_ms": f.start_ms,
                "end_ms": f.end_ms,
                "keyframe_timestamp_ms": f.keyframe_timestamp_ms,
                "image_width": f.image_width,
                "image_height": f.image_height,
                "dominant_colors": f.dominant_colors,
                "color_family": f.color_family,
                "color_embedding": f.color_embedding,
            }
            for f in fixtures
        ],
    }
    (output_dir / "scenes.json").write_text(
        json.dumps(scenes_payload, ensure_ascii=False, indent=2)
    )
    logger.info("wrote scenes.json total=%d", len(fixtures))

    # color_distribution.json: per-family count.
    family_counts: dict[str, int] = {f: 0 for f in COLOR_FAMILIES}
    family_by_type: dict[str, dict[str, int]] = {
        "video": {f: 0 for f in COLOR_FAMILIES},
        "image": {f: 0 for f in COLOR_FAMILIES},
    }
    for fx in fixtures:
        family_counts[fx.color_family] += 1
        family_by_type[fx.content_type][fx.color_family] += 1

    distribution = {
        "total": len(fixtures),
        "per_family": family_counts,
        "per_type": family_by_type,
    }
    (output_dir / "color_distribution.json").write_text(
        json.dumps(distribution, ensure_ascii=False, indent=2)
    )
    logger.info("wrote color_distribution.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Input folder with videos + images")
    parser.add_argument("--output", required=True, help="Output fixtures folder")
    parser.add_argument("--per-video", type=int, default=9, help="Keyframes per video")
    parser.add_argument("--image-size", type=int, default=640, help="Max width for fixture images")
    parser.add_argument("--proxy-dir", default="/tmp/seed_proxies",
                        help="Scratch dir for 720p proxies (kept across runs to skip re-transcode)")
    args = parser.parse_args()

    input_dir = Path(args.input)
    output_dir = Path(args.output)

    if not input_dir.is_dir():
        logger.error("input dir missing: %s", input_dir)
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)

    videos = [p for p in input_dir.iterdir() if p.suffix.lower() in VIDEO_EXTS]
    images = [p for p in input_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS]

    logger.info("discovered videos=%d images=%d", len(videos), len(images))
    if not videos and not images:
        logger.error("no assets found in %s", input_dir)
        return 1

    fixtures: list[SceneFixture] = []
    fixtures += process_videos(
        videos, output_dir, per_video=args.per_video, proxy_dir=Path(args.proxy_dir),
    )
    fixtures += process_images(images, output_dir, image_size=args.image_size)

    write_metadata(fixtures, output_dir)

    # Print distribution summary to stdout for quick review.
    video_scenes = [f for f in fixtures if f.content_type == "video"]
    image_scenes = [f for f in fixtures if f.content_type == "image"]

    print("\n=== COLOR FAMILY DISTRIBUTION ===")
    print(f"Total scenes: {len(fixtures)}  (videos: {len(video_scenes)}, images: {len(image_scenes)})")
    print(f"{'family':<10} {'total':>6} {'video':>6} {'image':>6}")
    print("-" * 32)
    counts: dict[str, list[int]] = {f: [0, 0, 0] for f in COLOR_FAMILIES}
    for fx in fixtures:
        counts[fx.color_family][0] += 1
        if fx.content_type == "video":
            counts[fx.color_family][1] += 1
        else:
            counts[fx.color_family][2] += 1
    for family, (tot, vid, img) in sorted(counts.items(), key=lambda x: -x[1][0]):
        print(f"{family:<10} {tot:>6} {vid:>6} {img:>6}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
