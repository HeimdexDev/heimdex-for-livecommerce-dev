"""Recover real start_ms/end_ms for video scenes in scenes.json.

Runs split_scenes() directly on the ORIGINAL .mp4 files (no proxy transcode),
mimics the sample_evenly(9) selection used in extract_seed_fixtures.py, and
patches start_ms / end_ms / keyframe_timestamp_ms back into scenes.json.

Usage (inside api container):
    docker compose run --rm --no-deps \\
      -v "/host/seed:/seed:ro" \\
      -v "$(pwd)/scripts:/scripts:ro" \\
      --entrypoint python \\
      api /scripts/recover_timestamps.py \\
      --videos /seed \\
      --scenes /app/app/db/seed/fixtures/scenes.json
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import defaultdict
from pathlib import Path

from heimdex_media_pipelines.scenes.splitter import split_scenes

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("recover_timestamps")


def sample_evenly_indices(n: int, target: int) -> list[int]:
    """Mirror extract_seed_fixtures.py::sample_evenly for index mapping."""
    if n <= target:
        return list(range(n))
    if target <= 1:
        return [n // 2]
    step = (n - 1) / (target - 1)
    return [round(i * step) for i in range(target)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--videos", required=True, help="Folder with original .mp4")
    parser.add_argument("--scenes", required=True, help="scenes.json path (in-place)")
    parser.add_argument("--preset", default="default")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Compute the new timestamps but do NOT write scenes.json. "
            "Prints a summary of how many scenes would change. Safer "
            "default when pointing --videos at a new asset folder."
        ),
    )
    args = parser.parse_args()

    videos_dir = Path(args.videos)
    scenes_path = Path(args.scenes)

    with scenes_path.open() as f:
        payload = json.load(f)

    # Map slugged_stem ("260311_베노프_영상") -> real proxy path
    # Accepts both ".proxy.mp4" and ".mp4" suffixes. Strips ".proxy" from stem.
    video_files: dict[str, Path] = {}
    for vf in videos_dir.iterdir():
        if vf.suffix.lower() != ".mp4":
            continue
        stem = vf.stem
        if stem.endswith(".proxy"):
            stem = stem[: -len(".proxy")]
        key = stem.replace(" ", "_")
        video_files[key] = vf
    logger.info("found %d source videos", len(video_files))

    # Group scenes.json video scenes by video_title
    by_title: dict[str, list[dict]] = defaultdict(list)
    for sc in payload["scenes"]:
        if sc["content_type"] == "video":
            by_title[sc["video_title"]].append(sc)

    updated = 0
    missing_videos: list[str] = []

    for title, scene_docs in sorted(by_title.items()):
        vf = video_files.get(title)
        if vf is None:
            missing_videos.append(title)
            logger.warning("no source video for title=%s", title)
            continue

        logger.info("split_start video=%s", vf.name)
        full_scenes = split_scenes(
            video_path=str(vf),
            video_id="recover",
            preset=args.preset,
        )
        total = len(full_scenes)
        picked = sample_evenly_indices(total, target=9)
        logger.info("split_done video=%s total=%d picked_indices=%s",
                    vf.name, total, picked)

        # new_idx (0..8) -> original scene in full_scenes
        for sc in scene_docs:
            new_idx = int(sc["scene_id"].rsplit("_", 1)[-1])
            if new_idx >= len(picked):
                logger.warning("scene_id idx out of range: %s (new_idx=%d)",
                               sc["scene_id"], new_idx)
                continue
            orig = full_scenes[picked[new_idx]]
            sc["start_ms"] = int(orig.start_ms)
            sc["end_ms"] = int(orig.end_ms)
            sc["keyframe_timestamp_ms"] = int(orig.keyframe_timestamp_ms)
            updated += 1

    if args.dry_run:
        logger.info(
            "dry_run_complete would_update=%d scenes_path=%s (no write)",
            updated, scenes_path,
        )
    else:
        scenes_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2)
        )
        logger.info("wrote %s updated_scenes=%d", scenes_path, updated)

    if missing_videos:
        logger.warning("missing videos: %s", missing_videos)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
