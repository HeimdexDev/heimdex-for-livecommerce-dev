import importlib
import logging
import shutil
import tempfile
import time
from pathlib import Path
import uuid
from typing import Any

import requests

from heimdex_worker_sdk import emit_event

logger = logging.getLogger(__name__)
_SERVICE_NAME = "drive-face-worker"
cv2 = importlib.import_module("cv2")
np = importlib.import_module("numpy")

# Expand face bounding box by this ratio on each side for thumbnails.
# 0.4 = 40% of face width/height added to each edge (tight face → head + shoulders).
THUMBNAIL_PADDING = 0.4


def compute_quality(blur_score: float, area_ratio: float, det_conf: float) -> float:
    blur_norm = blur_score / (blur_score + 100.0)
    area_norm = min(max(area_ratio, 0.0), 1.0)
    conf_norm = min(max(det_conf, 0.0), 1.0)
    return blur_norm * 0.4 + area_norm * 0.3 + conf_norm * 0.3


async def process_face_pending_files(api_client: Any, settings: Any, face_analyzer: Any = None) -> None:
    files = api_client.claim_jobs("face", limit=1)
    for claimed_file in files:
        _process_single_face_detect(
            api_client=api_client,
            settings=settings,
            claimed_file=claimed_file,
            face_analyzer=face_analyzer,
        )


def _process_single_face_detect(
    api_client: Any,
    settings: Any,
    claimed_file: Any,
    face_analyzer: Any = None,
) -> None:
    S3Client = importlib.import_module("heimdex_worker_sdk.s3").S3Client
    FaceAnalysis = importlib.import_module("insightface.app").FaceAnalysis
    detect_onnx_providers = importlib.import_module(
        "heimdex_media_pipelines.device"
    ).detect_onnx_providers

    org_id = str(claimed_file.org_id)
    file_id = claimed_file.id
    lease_token = claimed_file.lease_token
    video_id = claimed_file.video_id
    keyframe_s3_prefix = claimed_file.keyframe_s3_prefix
    temp_dir = Path(tempfile.mkdtemp(prefix=f"face_{video_id}_"))

    t_start = time.monotonic()

    try:
        if not keyframe_s3_prefix:
            api_client.update_job_status(
                file_id,
                job_type="face",
                status="failed",
                error="missing_keyframe_s3_prefix",
                lease_token=lease_token,
            )
            emit_event(
                service=_SERVICE_NAME,
                event_name="face_skipped",
                category="job_failure",
                level="WARNING",
                org_id=claimed_file.org_id,
                job_id=file_id,
                duration_ms=int((time.monotonic() - t_start) * 1000),
                message="missing_keyframe_s3_prefix",
                metadata={
                    "video_id": video_id,
                    "reason": "missing_keyframe_s3_prefix",
                    "error_class": "MissingPrecondition",
                },
            )
            return

        s3 = S3Client(bucket=settings.drive_s3_bucket)
        keyframes_dir = temp_dir / "keyframes"
        keyframes_dir.mkdir(parents=True, exist_ok=True)

        downloaded = _download_keyframes_from_prefix(
            s3=s3,
            prefix=keyframe_s3_prefix,
            out_dir=keyframes_dir,
        )
        if not downloaded:
            api_client.update_job_status(
                file_id,
                job_type="face",
                status="failed",
                error="no_keyframes_downloaded",
                lease_token=lease_token,
            )
            emit_event(
                service=_SERVICE_NAME,
                event_name="face_failed",
                category="job_failure",
                level="ERROR",
                org_id=claimed_file.org_id,
                job_id=file_id,
                duration_ms=int((time.monotonic() - t_start) * 1000),
                message="no_keyframes_downloaded",
                metadata={
                    "video_id": video_id,
                    "stage": "keyframe_download",
                    "error_class": "NoKeyframesDownloaded",
                    "keyframe_s3_prefix": keyframe_s3_prefix,
                },
            )
            return

        if face_analyzer is None:
            providers = detect_onnx_providers()
            face_analyzer = FaceAnalysis(name="buffalo_l", providers=providers)
            face_analyzer.prepare(
                ctx_id=0 if settings.use_gpu else -1,
                det_size=(640, 640),
                det_thresh=0.5,
            )

        detections = _detect_faces(downloaded, face_analyzer, video_id)
        if not detections:
            api_client.update_job_status(
                file_id,
                job_type="face",
                status="done",
                lease_token=lease_token,
            )
            emit_event(
                service=_SERVICE_NAME,
                event_name="face_skipped",
                category="job_failure",
                level="WARNING",
                org_id=claimed_file.org_id,
                job_id=file_id,
                duration_ms=int((time.monotonic() - t_start) * 1000),
                message="no_faces_detected",
                metadata={
                    "video_id": video_id,
                    "reason": "no_faces_detected",
                    "error_class": "NoFacesDetected",
                    "keyframe_count": len(downloaded),
                },
            )
            return

        clusters = _cluster_detections(detections, similarity_threshold=0.6)
        representative_embeddings = [c["representative"]["embedding"].tolist() for c in clusters]

        matches = _match_faces(
            settings=settings,
            org_id=org_id,
            embeddings=representative_embeddings,
            threshold=0.55,
        )

        identity_rows, cluster_id_by_index = _build_identity_rows(
            clusters=clusters,
            matches=matches,
            org_id=org_id,
            video_id=video_id,
        )

        upsert_result = _upsert_identities(settings=settings, org_id=org_id, identities=identity_rows)

        scene_cluster_map = _build_scene_people_map(detections, cluster_id_by_index)
        _post_enrich_to_api(
            api_client=api_client,
            org_id=org_id,
            video_id=video_id,
            scene_cluster_map=scene_cluster_map,
        )

        try:
            _upload_thumbnails(
                settings=settings,
                org_id=org_id,
                cluster_id_by_index=cluster_id_by_index,
                clusters=clusters,
            )
        except Exception as thumb_err:
            logger.warning(
                "face_thumbnail_upload_failed_non_fatal",
                extra={"org_id": org_id, "video_id": video_id, "error": str(thumb_err)},
            )

        try:
            _upload_exemplar_crops(
                settings=settings,
                org_id=org_id,
                upsert_result=upsert_result,
                clusters=clusters,
                cluster_id_by_index=cluster_id_by_index,
            )
        except Exception as crop_err:
            logger.warning(
                "face_exemplar_crop_upload_failed_non_fatal",
                extra={"org_id": org_id, "video_id": video_id, "error": str(crop_err)},
            )

        api_client.update_job_status(
            file_id,
            job_type="face",
            status="done",
            lease_token=lease_token,
        )
        logger.info(
            "face_processing_complete",
            extra={
                "org_id": org_id,
                "video_id": video_id,
                "keyframe_count": len(downloaded),
                "face_count": len(detections),
                "cluster_count": len(clusters),
                "scene_count": len(scene_cluster_map),
            },
        )
        emit_event(
            service=_SERVICE_NAME,
            event_name="face_completed",
            category="job_success",
            level="INFO",
            org_id=claimed_file.org_id,
            job_id=file_id,
            duration_ms=int((time.monotonic() - t_start) * 1000),
            metadata={
                "video_id": video_id,
                "keyframe_count": len(downloaded),
                "face_count": len(detections),
                "cluster_count": len(clusters),
                "scene_count": len(scene_cluster_map),
            },
        )
    except Exception as e:
        api_client.update_job_status(
            file_id,
            job_type="face",
            status="failed",
            error=f"{type(e).__name__}: {e}",
            lease_token=lease_token,
        )
        logger.exception(
            "face_processing_failed",
            extra={"org_id": org_id, "video_id": video_id},
        )
        emit_event(
            service=_SERVICE_NAME,
            event_name="face_failed",
            category="job_failure",
            level="ERROR",
            org_id=claimed_file.org_id,
            job_id=file_id,
            duration_ms=int((time.monotonic() - t_start) * 1000),
            message=f"{type(e).__name__}: {e}"[:1000],
            metadata={
                "video_id": video_id,
                "error_class": type(e).__name__,
                "error_msg": str(e)[:500],
            },
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _download_keyframes_from_prefix(s3: Any, prefix: str, out_dir: Path) -> list[Path]:
    paginator = s3._client.get_paginator("list_objects_v2")
    downloaded: list[Path] = []
    for page in paginator.paginate(Bucket=s3.bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.lower().endswith(".jpg"):
                continue
            local_path = out_dir / Path(key).name
            s3.download_file(key, local_path)
            downloaded.append(local_path)
    return sorted(downloaded)


def _parse_scene_id(video_id: str, keyframe_path: Path) -> str | None:
    stem = keyframe_path.stem
    expected_prefix = f"{video_id}_scene_"
    if not stem.startswith(expected_prefix):
        return None
    scene_num = stem[len(expected_prefix) :]
    if not scene_num.isdigit():
        return None
    return stem


def _detect_faces(image_paths: list[Path], face_analyzer: Any, video_id: str) -> list[dict[str, Any]]:
    detections: list[dict[str, Any]] = []
    for image_path in image_paths:
        scene_id = _parse_scene_id(video_id, image_path)
        if not scene_id:
            continue
        image = cv2.imread(str(image_path))
        if image is None:
            continue

        height, width = image.shape[:2]
        image_area = float(max(width * height, 1))

        faces = face_analyzer.get(image)
        for face in faces:
            x1, y1, x2, y2 = [int(v) for v in face.bbox]
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(width, x2)
            y2 = min(height, y2)
            if x2 <= x1 or y2 <= y1:
                continue

            face_w = x2 - x1
            face_h = y2 - y1
            if min(face_w, face_h) < 40:
                continue

            crop = image[y1:y2, x1:x2]
            if crop.size == 0:
                continue

            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            area_ratio = float((face_w * face_h) / image_area)
            det_conf = float(face.det_score)
            quality = compute_quality(blur_score, area_ratio, det_conf)

            embedding = np.asarray(face.embedding, dtype=np.float32)
            norm = float(np.linalg.norm(embedding))
            if norm <= 0:
                continue
            embedding = embedding / norm

            pad_x = int(face_w * THUMBNAIL_PADDING)
            pad_y = int(face_h * THUMBNAIL_PADDING)
            tx1 = max(0, x1 - pad_x)
            ty1 = max(0, y1 - pad_y)
            tx2 = min(width, x2 + pad_x)
            ty2 = min(height, y2 + pad_y)
            thumbnail_crop = image[ty1:ty2, tx1:tx2]

            detections.append(
                {
                    "scene_id": scene_id,
                    "image_path": image_path,
                    "bbox": (x1, y1, x2, y2),
                    "det_conf": det_conf,
                    "quality": quality,
                    "embedding": embedding,
                    "crop": thumbnail_crop,
                }
            )
    return detections


def _cluster_detections(detections: list[dict[str, Any]], similarity_threshold: float) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for detection in detections:
        assigned_idx = None
        best_sim = -1.0
        for idx, cluster in enumerate(clusters):
            similarity = float(np.dot(detection["embedding"], cluster["centroid"]))
            if similarity > similarity_threshold and similarity > best_sim:
                best_sim = similarity
                assigned_idx = idx

        if assigned_idx is None:
            clusters.append(
                {
                    "members": [detection],
                    "centroid": detection["embedding"].copy(),
                    "representative": detection,
                }
            )
            detection["cluster_index"] = len(clusters) - 1
            continue

        cluster = clusters[assigned_idx]
        cluster["members"].append(detection)
        member_embeddings = np.stack([m["embedding"] for m in cluster["members"]], axis=0)
        centroid = np.mean(member_embeddings, axis=0)
        centroid_norm = float(np.linalg.norm(centroid))
        cluster["centroid"] = centroid / centroid_norm if centroid_norm > 0 else centroid
        if detection["quality"] > cluster["representative"]["quality"]:
            cluster["representative"] = detection
        detection["cluster_index"] = assigned_idx

    for cluster in clusters:
        cluster["representative"]["embedding"] = cluster["centroid"]
    return clusters


def _internal_headers(settings: Any, org_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.drive_internal_api_key}",
        "X-Heimdex-Org-Id": org_id,
        "Content-Type": "application/json",
    }


def _match_faces(
    settings: Any,
    org_id: str,
    embeddings: list[list[float]],
    threshold: float,
) -> list[dict[str, Any] | None]:
    if not embeddings:
        return []
    url = f"{settings.drive_api_base_url.rstrip('/')}/internal/face/match"
    resp = requests.post(
        url,
        json={
            "org_id": org_id,
            "embeddings": embeddings,
            "threshold": threshold,
        },
        headers=_internal_headers(settings, org_id),
        timeout=300,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"face_match_failed {resp.status_code}: {resp.text[:500]}")
    payload = resp.json()
    matches = payload.get("matches", [])
    if not isinstance(matches, list):
        raise RuntimeError("face_match_invalid_response")
    return matches


def _build_identity_rows(
    clusters: list[dict[str, Any]],
    matches: list[dict[str, Any] | None],
    org_id: str,
    video_id: str,
) -> tuple[list[dict[str, Any]], dict[int, str]]:
    identities: list[dict[str, Any]] = []
    cluster_id_by_index: dict[int, str] = {}
    for idx, cluster in enumerate(clusters):
        representative = cluster["representative"]
        matched = matches[idx] if idx < len(matches) else None
        matched_cluster_id = matched.get("cluster_id") if isinstance(matched, dict) else None
        is_new = not bool(matched_cluster_id)
        cluster_id = matched_cluster_id or f"person_{uuid.uuid4().hex[:12]}"
        cluster_id_by_index[idx] = cluster_id

        identities.append(
            {
                "cluster_id": cluster_id,
                "embedding": representative["embedding"].tolist(),
                "quality": float(representative["quality"]),
                "video_id": video_id,
                "scene_id": representative["scene_id"],
                "is_new": is_new,
                "org_id": org_id,
            }
        )
    return identities, cluster_id_by_index


def _upsert_identities(settings: Any, org_id: str, identities: list[dict[str, Any]]) -> dict[str, Any]:
    if not identities:
        return {"ok": True}
    url = f"{settings.drive_api_base_url.rstrip('/')}/internal/face/identities"
    resp = requests.post(
        url,
        json={"org_id": org_id, "identities": identities},
        headers=_internal_headers(settings, org_id),
        timeout=300,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"face_identity_upsert_failed {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def _build_scene_people_map(
    detections: list[dict[str, Any]],
    cluster_id_by_index: dict[int, str],
) -> dict[str, list[str]]:
    scene_to_ids: dict[str, set[str]] = {}
    for detection in detections:
        scene_id = detection["scene_id"]
        cluster_index = detection.get("cluster_index")
        if cluster_index is None:
            continue
        cluster_id = cluster_id_by_index.get(cluster_index)
        if cluster_id is None:
            continue
        scene_to_ids.setdefault(scene_id, set()).add(cluster_id)
    return {scene_id: sorted(cluster_ids) for scene_id, cluster_ids in scene_to_ids.items()}


def _post_enrich_to_api(
    api_client: Any,
    org_id: str,
    video_id: str,
    scene_cluster_map: dict[str, list[str]],
) -> dict[str, Any]:
    scenes = [
        {"scene_id": scene_id, "people_cluster_ids": cluster_ids}
        for scene_id, cluster_ids in scene_cluster_map.items()
    ]
    if not scenes:
        return {"updated_count": 0, "video_id": video_id}
    url = f"{api_client.base_url.rstrip('/')}/internal/ingest/enrich"
    return api_client._request_with_retry(
        "POST",
        url,
        json={"video_id": video_id, "scenes": scenes},
        headers={"X-Heimdex-Org-Id": org_id},
        timeout=300,
    )


def _upload_thumbnails(
    settings: Any,
    org_id: str,
    cluster_id_by_index: dict[int, str],
    clusters: list[dict[str, Any]],
) -> None:
    for index, cluster_id in cluster_id_by_index.items():
        representative = clusters[index]["representative"]
        crop = representative.get("crop")
        if crop is None or crop.size == 0:
            continue
        ok, encoded = cv2.imencode(".jpg", crop)
        if not ok:
            continue
        url = f"{settings.drive_api_base_url.rstrip('/')}/internal/ingest/thumbnails/face/{cluster_id}"
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.drive_internal_api_key}",
                "X-Heimdex-Org-Id": org_id,
            },
            files={"file": (f"{cluster_id}.jpg", encoded.tobytes(), "image/jpeg")},
            timeout=300,
        )
        if resp.status_code >= 300:
            raise RuntimeError(
                f"face_thumbnail_upload_failed {cluster_id} {resp.status_code}: {resp.text[:500]}"
            )


def _upload_exemplar_crops(
    settings: Any,
    org_id: str,
    upsert_result: dict[str, Any],
    clusters: list[dict[str, Any]],
    cluster_id_by_index: dict[int, str],
) -> None:
    """Upload per-detection exemplar crops for the gallery picker."""
    exemplar_ids = upsert_result.get("exemplar_ids", [])
    if not exemplar_ids:
        return

    # Build mapping: cluster_id -> list of exemplar_ids (in order)
    cluster_exemplar_map: dict[str, list[str]] = {}
    for mapping in exemplar_ids:
        cid = mapping["cluster_id"]
        cluster_exemplar_map.setdefault(cid, []).append(mapping["exemplar_id"])

    for index, cluster_id in cluster_id_by_index.items():
        eid_list = cluster_exemplar_map.get(cluster_id, [])
        if not eid_list:
            continue
        # The last exemplar_id corresponds to the detection just uploaded
        exemplar_id = eid_list[-1]

        # Upload all member crops for this cluster (up to 20)
        members = clusters[index]["members"]
        for member in members[:20]:
            crop = member.get("crop")
            if crop is None or crop.size == 0:
                continue
            ok, encoded = cv2.imencode(".jpg", crop)
            if not ok:
                continue

            url = f"{settings.drive_api_base_url.rstrip('/')}/internal/ingest/thumbnails/face-exemplar/{exemplar_id}"
            resp = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {settings.drive_internal_api_key}",
                    "X-Heimdex-Org-Id": org_id,
                },
                files={"file": (f"{exemplar_id}.jpg", encoded.tobytes(), "image/jpeg")},
                timeout=60,
            )
            if resp.status_code >= 300:
                logger.warning(
                    "exemplar_crop_upload_failed",
                    extra={
                        "exemplar_id": exemplar_id,
                        "cluster_id": cluster_id,
                        "status": resp.status_code,
                    },
                )
            break  # Only upload one crop per exemplar_id
