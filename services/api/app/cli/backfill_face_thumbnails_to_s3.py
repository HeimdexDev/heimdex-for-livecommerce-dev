"""
One-time backfill: upload existing face thumbnails from disk to S3.

Usage:
    docker compose exec -T api python -m app.cli.backfill_face_thumbnails_to_s3
    docker compose exec -T api python -m app.cli.backfill_face_thumbnails_to_s3 --dry-run
    docker compose exec -T api python -m app.cli.backfill_face_thumbnails_to_s3 --org <org_id>
"""
import argparse
import sys
import time
from pathlib import Path

from app.config import get_settings
from app.modules.drive.keys import exemplar_thumbnail_s3_key, face_thumbnail_s3_key
from app.storage.s3 import S3Client


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill face thumbnails from disk to S3")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be uploaded without uploading")
    parser.add_argument("--org", type=str, default=None, help="Limit to a specific org_id directory")
    parser.add_argument("--skip-existing", action="store_true", help="Skip S3 keys that already exist")
    args = parser.parse_args()

    settings = get_settings()
    root = Path(settings.thumbnail_storage_dir)
    s3 = S3Client(bucket=settings.drive_s3_bucket)

    if not root.exists():
        print(f"Thumbnail root {root} does not exist, nothing to backfill.")
        return

    org_dirs = [root / args.org] if args.org else sorted(root.iterdir())

    stats = {"uploaded": 0, "skipped": 0, "errors": 0, "faces": 0, "exemplars": 0}
    start = time.monotonic()

    for org_dir in org_dirs:
        if not org_dir.is_dir():
            continue

        org_id = org_dir.name
        faces_dir = org_dir / "faces"
        if not faces_dir.is_dir():
            continue

        # Main face thumbnails
        for face_file in sorted(faces_dir.glob("*.jpg")):
            cluster_id = face_file.stem
            s3_key = face_thumbnail_s3_key(org_id, cluster_id)
            _upload_one(s3, face_file, s3_key, args, stats)
            stats["faces"] += 1

        # Exemplar crops
        exemplars_dir = faces_dir / "exemplars"
        if exemplars_dir.is_dir():
            for exemplar_file in sorted(exemplars_dir.glob("*.jpg")):
                exemplar_id = exemplar_file.stem
                s3_key = exemplar_thumbnail_s3_key(org_id, exemplar_id)
                _upload_one(s3, exemplar_file, s3_key, args, stats)
                stats["exemplars"] += 1

    elapsed = time.monotonic() - start
    print(
        f"\nDone in {elapsed:.1f}s — "
        f"faces={stats['faces']}, exemplars={stats['exemplars']}, "
        f"uploaded={stats['uploaded']}, skipped={stats['skipped']}, errors={stats['errors']}"
    )


def _upload_one(s3: S3Client, local_path: Path, s3_key: str, args, stats: dict) -> None:
    if args.dry_run:
        print(f"[dry-run] {local_path} -> s3://{s3.bucket}/{s3_key}")
        stats["skipped"] += 1
        return

    if args.skip_existing and s3.exists(s3_key):
        stats["skipped"] += 1
        return

    try:
        s3.upload_file(local_path, s3_key, content_type="image/jpeg")
        stats["uploaded"] += 1
        print(f"  uploaded {s3_key} ({local_path.stat().st_size} bytes)")
    except Exception as exc:
        stats["errors"] += 1
        print(f"  ERROR {s3_key}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
