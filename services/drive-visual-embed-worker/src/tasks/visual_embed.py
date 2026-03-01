"""Visual embedding task: encode keyframes with SigLIP2 vision encoder.

Downloads keyframe images from S3, runs them through the SigLIP2 vision
encoder to produce 768-dim embeddings, and posts results back to the API
via the ``/internal/ingest/enrich`` endpoint.

The vision encoder produces embeddings in the same vector space as the
SigLIP2 text encoder running in the API container — enabling cross-modal
search (text query → visual embedding space → keyframe matches).
"""
import importlib
import json
import logging
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Lazy-loaded globals (initialized once per worker lifetime)
_vision_model = None
_processor = None
_device = None


def _load_vision_model(use_gpu: bool = False) -> None:
    """Lazy-load SigLIP2 vision encoder and processor.

    Called once on first job.  Model stays in memory for the worker's lifetime.
    """
    global _vision_model, _processor, _device

    if _vision_model is not None:
        return

    import torch
    from transformers import AutoProcessor, Siglip2VisionModel

    _device = torch.device("cuda" if use_gpu and torch.cuda.is_available() else "cpu")
    dtype = torch.float16 if _device.type == "cuda" else torch.bfloat16

    logger.info(
        "loading_siglip2_vision_model",
        extra={
            "model": "google/siglip2-base-patch16-256",
            "device": str(_device),
            "dtype": str(dtype),
        },
    )

    _processor = AutoProcessor.from_pretrained("google/siglip2-base-patch16-256")
    _vision_model = Siglip2VisionModel.from_pretrained(
        "google/siglip2-base-patch16-256",
        torch_dtype=dtype,
        low_cpu_mem_usage=True,
    ).to(_device)
    _vision_model.eval()

    param_count = sum(p.numel() for p in _vision_model.parameters())
    logger.info(
        "siglip2_vision_model_loaded",
        extra={"params_m": round(param_count / 1e6, 1), "device": str(_device)},
    )


def _embed_keyframe(image_path: Path) -> list[float]:
    """Encode a single keyframe image → 768-dim L2-normalized vector."""
    import torch
    import torch.nn.functional as F
    from PIL import Image

    assert _vision_model is not None
    assert _processor is not None

    image = Image.open(image_path).convert("RGB")
    inputs = _processor(images=image, return_tensors="pt")

    # Move to model device and dtype
    for key in inputs:
        inputs[key] = inputs[key].to(_device)
        if inputs[key].dtype == torch.float32 and _vision_model.dtype != torch.float32:
            inputs[key] = inputs[key].to(_vision_model.dtype)

    with torch.no_grad():
        outputs = _vision_model(**inputs)

    # pooler_output: MAP-pooled → [1, 768]
    pooled = outputs.pooler_output.float()
    normalized = F.normalize(pooled, p=2, dim=-1)

    return normalized.squeeze(0).cpu().tolist()


def _embed_keyframes_batch(image_paths: list[Path], batch_size: int = 16) -> list[list[float]]:
    """Batch-encode multiple keyframes for throughput.

    Processes in mini-batches to fit GPU memory.
    Returns list of 768-dim vectors in same order as input.
    """
    import torch
    import torch.nn.functional as F
    from PIL import Image

    assert _vision_model is not None
    assert _processor is not None

    all_embeddings: list[list[float]] = []

    for batch_start in range(0, len(image_paths), batch_size):
        batch_paths = image_paths[batch_start : batch_start + batch_size]
        images = [Image.open(p).convert("RGB") for p in batch_paths]

        inputs = _processor(images=images, return_tensors="pt")
        for key in inputs:
            inputs[key] = inputs[key].to(_device)
            if inputs[key].dtype == torch.float32 and _vision_model.dtype != torch.float32:
                inputs[key] = inputs[key].to(_vision_model.dtype)

        with torch.no_grad():
            outputs = _vision_model(**inputs)

        pooled = outputs.pooler_output.float()
        normalized = F.normalize(pooled, p=2, dim=-1)

        for i in range(normalized.shape[0]):
            all_embeddings.append(normalized[i].cpu().tolist())

    return all_embeddings


def _process_single_visual_embed(
    api_client: Any,
    settings: Any,
    claimed_file: Any,
) -> None:
    """Process a single video's keyframes → visual embeddings → enrich API."""
    drive_keys = importlib.import_module("heimdex_worker_sdk.drive_keys")
    scene_manifest_s3_key = drive_keys.scene_manifest_s3_key
    enrichment_keyframe_s3_key = drive_keys.enrichment_keyframe_s3_key
    S3Client = importlib.import_module("heimdex_worker_sdk.s3").S3Client

    org_id = claimed_file.org_id
    org_id_str = str(org_id)
    file_id = claimed_file.id
    lease_token = claimed_file.lease_token
    video_id = claimed_file.video_id
    temp_dir = Path(tempfile.mkdtemp(prefix=f"visual_embed_{video_id}_"))

    try:
        # 1. Load model on first call
        _load_vision_model(use_gpu=getattr(settings, "use_gpu", False))

        # 2. Download scene manifest
        s3 = S3Client(bucket=settings.drive_s3_bucket)
        manifest_key = scene_manifest_s3_key(org_id_str, video_id)
        manifest_path = temp_dir / "scenes.json"

        try:
            s3.download_file(manifest_key, manifest_path)
        except Exception as e:
            error_msg = f"manifest_download_failed: {type(e).__name__}: {e}"
            api_client.update_job_status(
                file_id, job_type="visual_embed", status="failed",
                error=error_msg, lease_token=lease_token,
            )
            return

        manifest = json.loads(manifest_path.read_text())
        scenes = manifest.get("scenes", [])
        scene_count = len(scenes)

        if scene_count == 0:
            api_client.update_job_status(
                file_id, job_type="visual_embed", status="done", lease_token=lease_token,
            )
            return

        # 3. Download keyframes from S3 (parallel)
        keyframes_dir = temp_dir / "keyframes"
        keyframes_dir.mkdir(parents=True, exist_ok=True)

        download_tasks: list[tuple[int, str, str, Path]] = []
        for scene_idx, scene in enumerate(scenes):
            scene_id = scene.get("scene_id")
            if not scene_id:
                continue
            s3_key = enrichment_keyframe_s3_key(org_id_str, video_id, scene_id)
            local_path = keyframes_dir / f"{scene_id}.jpg"
            download_tasks.append((scene_idx, scene_id, s3_key, local_path))

        downloaded_keyframes: dict[int, tuple[str, Path]] = {}
        download_failures = 0
        n_workers = min(8, max(1, len(download_tasks)))

        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            future_to_task = {
                pool.submit(s3.download_file, s3_key, local_path): (scene_idx, scene_id, local_path)
                for scene_idx, scene_id, s3_key, local_path in download_tasks
            }
            for future in as_completed(future_to_task):
                scene_idx, scene_id, local_path = future_to_task[future]
                try:
                    future.result()
                    downloaded_keyframes[scene_idx] = (scene_id, local_path)
                except Exception:
                    download_failures += 1
                    logger.warning(
                        "visual_embed_keyframe_download_failed",
                        extra={"org_id": org_id_str, "video_id": video_id, "scene_id": scene_id},
                    )

        if not downloaded_keyframes:
            api_client.update_job_status(
                file_id, job_type="visual_embed", status="failed",
                error="no_keyframes_downloaded", lease_token=lease_token,
            )
            return

        # 4. Batch encode keyframes → 768-dim vectors
        embed_started = time.monotonic()

        # Sort by scene_idx to maintain order
        sorted_indices = sorted(downloaded_keyframes.keys())
        ordered_paths = [downloaded_keyframes[idx][1] for idx in sorted_indices]
        ordered_scene_ids = [downloaded_keyframes[idx][0] for idx in sorted_indices]

        batch_size = 32 if getattr(settings, "use_gpu", False) else 4
        embeddings = _embed_keyframes_batch(ordered_paths, batch_size=batch_size)

        embed_duration_ms = int((time.monotonic() - embed_started) * 1000)

        # 5. Post visual embeddings to enrich API
        enrich_scenes: list[dict[str, Any]] = []
        for scene_id, embedding in zip(ordered_scene_ids, embeddings):
            enrich_scenes.append({
                "scene_id": scene_id,
                "visual_embedding": embedding,
            })

        if not enrich_scenes:
            api_client.update_job_status(
                file_id, job_type="visual_embed", status="done", lease_token=lease_token,
            )
            return

        try:
            ingest_result = _post_enrich_to_api(
                settings=settings,
                org_id=org_id,
                video_id=video_id,
                scenes=enrich_scenes,
            )
        except Exception as e:
            error_msg = f"visual_embed_enrich_failed: {type(e).__name__}: {e}"
            api_client.update_job_status(
                file_id, job_type="visual_embed", status="failed",
                error=error_msg, lease_token=lease_token,
            )
            return

        api_client.update_job_status(
            file_id, job_type="visual_embed", status="done", lease_token=lease_token,
        )

        logger.info(
            "visual_embed_processing_complete",
            extra={
                "org_id": org_id_str,
                "video_id": video_id,
                "scene_count": scene_count,
                "frames_processed": len(downloaded_keyframes),
                "frames_embedded": len(enrich_scenes),
                "download_failures": download_failures,
                "embed_duration_ms": embed_duration_ms,
                "updated_count": ingest_result.get("updated_count", 0),
            },
        )

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        api_client.update_job_status(
            file_id, job_type="visual_embed", status="failed",
            error=error_msg, lease_token=lease_token,
        )
        logger.exception(
            "visual_embed_processing_failed",
            extra={"org_id": org_id_str, "video_id": video_id},
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _post_enrich_to_api(
    settings: Any,
    org_id: Any,
    video_id: str,
    scenes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Post visual embeddings to the internal enrich API."""
    requests = importlib.import_module("requests")

    payload = {
        "video_id": video_id,
        "scenes": scenes,
    }

    api_base = settings.drive_api_base_url.rstrip("/")
    url = f"{api_base}/internal/ingest/enrich"

    resp = requests.post(
        url,
        json=payload,
        headers={
            "Authorization": f"Bearer {settings.drive_internal_api_key}",
            "X-Heimdex-Org-Id": str(org_id),
            "Content-Type": "application/json",
        },
        timeout=300,
    )

    if resp.status_code != 200:
        raise RuntimeError(
            f"Internal enrich API returned {resp.status_code}: {resp.text[:500]}"
        )

    return resp.json()
