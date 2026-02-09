import typer
import json
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.domain.faces.schemas import (
    FacePresenceResponse,
    IdentityPresence,
)
from src.domain.faces.pipeline import run_pipeline
from src.domain.faces.embed import run_embeddings

def _parse_boundaries(raw: str):
    if not raw:
        return None
    values = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        values.append(float(item))
    return values or None

def run(
    video: str = typer.Option(..., help="Path to video file"),
    identity: str = typer.Option(..., help="Path to identity folder"),
    out: str = typer.Option(..., help="Output json path"),
    fps: float = typer.Option(1.0, help="Frame sampling fps"),
    min_size: int = typer.Option(40, help="Minimum face bbox size"),
    scene_boundaries: str = typer.Option(
        "", help="Comma-separated scene boundary timestamps in seconds (e.g. 12.5,48.0)"
    ),
    detector: str = typer.Option("scrfd", help="Detector: scrfd or haar"),
    scrfd_det_size: int = typer.Option(640, help="SCRFD det_size (pixels)"),
    scrfd_ctx_id: int = typer.Option(-1, help="SCRFD ctx_id (-1=CPU, 0=GPU)"),
    embed: bool = typer.Option(True, help="Whether to compute face embeddings"),
    q_min: Optional[float] = typer.Option(
        None, help="Drop faces with quality below this threshold (optional)"
    ),
    align: bool = typer.Option(False, help="Align faces before embedding when possible"),
):
    video_id = os.path.splitext(os.path.basename(video))[0]

    artifacts_root = os.path.join(os.getcwd(), "artifacts", video_id)
    os.makedirs(artifacts_root, exist_ok=True)

    if os.path.isabs(out):
        out_path = out
    else:
        out_path = os.path.join(artifacts_root, out)

    detections_path = run_pipeline(
        video,
        identity,
        fps=fps,
        min_size=min_size,
        scene_boundaries_s=_parse_boundaries(scene_boundaries),
        detector=detector,
        scrfd_det_size=scrfd_det_size,
        scrfd_ctx_id=scrfd_ctx_id,
    )
    embeddings_path = None
    if embed:
        embeddings_paths = run_embeddings(
            video,
            detections_path,
            q_min=q_min,
            align=align,
            det_size=scrfd_det_size,
            ctx_id=scrfd_ctx_id,
        )
        embeddings_path = embeddings_paths.get("jsonl")

    response = FacePresenceResponse(
        video_id=video_id,
        identities=[
            IdentityPresence(
                identity_id="dummy_host",
                intervals=[],
                scene_summary=[]
            )
        ],
        meta={
            "detector": detector,
            "embedder": "arcface",
            "similarity": "cosine",
            "thresholds": {
                "high": 0.35,
                "low": 0.25
            },
            "confidence_semantics": "recall-oriented (safe exclusion)",
            "created_at": datetime.utcnow().isoformat(),
            "detections_path": detections_path,
            "embeddings_path": embeddings_path,
            "fps": fps,
            "min_size": min_size,
            "scene_boundaries": scene_boundaries,
            "scrfd_det_size": scrfd_det_size,
            "scrfd_ctx_id": scrfd_ctx_id,
        }
    )

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(response.model_dump(), f, indent=2)

    print(f"[OK] Face presence json written to {out_path}")
    print(f"[OK] Face detections jsonl written to {detections_path}")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        sys.argv.pop(1)
    typer.run(run)
