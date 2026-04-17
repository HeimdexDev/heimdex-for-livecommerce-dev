import asyncio
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.config import get_settings
from app.logging_config import setup_logging, get_logger
from app.modules.orgs.models import Org
from app.modules.users.models import User, UserRole
from app.modules.libraries.models import Library
from app.modules.profiles.models import LibraryProfile, ProfileStatus
from app.modules.people.models import DriveNicknameRegistry, PeopleClusterLabel
from app.modules.text_templates.models import TextTemplate
from app.modules.face.models import FaceIdentity, FaceExemplar
from app.modules.drive.models import DriveConnection, DriveFile
from app.modules.blur.models import BlurJob
from app.modules.search.client import OpenSearchClient
from app.modules.search.scene_client import SceneSearchClient
from app.modules.search.embedding import generate_mock_embedding

setup_logging()
logger = get_logger(__name__)

KOREAN_TRANSCRIPTS = [
    "안녕하세요. 오늘 회의에서 논의할 주요 안건은 신규 프로젝트 일정입니다.",
    "이번 분기 매출 목표를 달성하기 위해 마케팅 전략을 수정해야 합니다.",
    "고객 피드백을 분석한 결과, 사용자 인터페이스 개선이 필요합니다.",
    "다음 주에 있을 제품 출시를 위해 최종 점검을 진행하겠습니다.",
    "팀 워크샵에서 새로운 아이디어들이 많이 나왔습니다.",
    "클라우드 인프라 마이그레이션 프로젝트가 성공적으로 완료되었습니다.",
    "인공지능 기반 추천 시스템 개발에 대해 설명드리겠습니다.",
    "보안 취약점 패치가 완료되어 시스템이 더 안전해졌습니다.",
    "사용자 경험을 개선하기 위한 A/B 테스트 결과를 공유합니다.",
    "데이터베이스 최적화로 쿼리 성능이 50% 향상되었습니다.",
    "모바일 앱 업데이트에 새로운 기능이 추가되었습니다.",
    "고객 지원 팀의 응답 시간이 크게 단축되었습니다.",
    "신규 파트너십 체결로 사업 확장의 기회가 생겼습니다.",
    "분기별 실적 보고서를 검토하고 있습니다.",
    "프로젝트 마일스톤 달성을 축하드립니다.",
    "기술 문서화 작업이 완료되어 온보딩이 수월해질 것입니다.",
    "서버 모니터링 시스템 구축이 완료되었습니다.",
    "코드 리뷰 프로세스 개선 방안을 논의하겠습니다.",
    "자동화 테스트 커버리지가 80%를 달성했습니다.",
    "다국어 지원 기능이 추가되어 글로벌 확장이 가능해졌습니다.",
    "머신러닝 모델 학습 파이프라인을 구축했습니다.",
    "스프린트 회고에서 도출된 개선점을 공유합니다.",
    "API 문서가 업데이트되어 개발자 경험이 향상되었습니다.",
    "성능 테스트 결과 목표치를 초과 달성했습니다.",
    "장애 대응 프로세스가 개선되어 복구 시간이 단축되었습니다.",
]

ENGLISH_TRANSCRIPTS = [
    "Welcome to today's presentation on quarterly results.",
    "Let's discuss the roadmap for the upcoming release.",
    "The customer satisfaction survey shows positive trends.",
    "We need to address the scalability concerns immediately.",
    "The new feature deployment was successful.",
    "Team collaboration has improved significantly this month.",
    "Security audit findings require immediate attention.",
    "The migration to the new platform is progressing well.",
    "User engagement metrics have exceeded expectations.",
    "Let's review the action items from yesterday's meeting.",
]

# Seed fixtures (scene metadata + color data generated offline from real
# live-commerce footage by scripts/extract_seed_fixtures.py).
FIXTURES_DIR = Path(__file__).parent / "db" / "seed" / "fixtures"
FIXTURE_PATH = FIXTURES_DIR / "scenes.json"
FACE_EMBEDDINGS_PATH = FIXTURES_DIR / "face_embeddings.json"
VISUAL_EMBEDDINGS_PATH = FIXTURES_DIR / "visual_embeddings.json"


def _load_scene_fixtures() -> list[dict]:
    """Load the seed scene fixtures produced by extract_seed_fixtures.py.

    Each entry carries the complete color signal (dominant_colors,
    color_embedding, color_family) and temporal anchors (start_ms, end_ms,
    keyframe_timestamp_ms) derived from real assets. Seed runtime only adds
    org/library ids and the random metadata fields (transcript, speaker,
    people, source_type) on top.
    """
    with FIXTURE_PATH.open(encoding="utf-8") as f:
        return json.load(f)["scenes"]


def _classify_orientation(width: int, height: int) -> str:
    """Map image dimensions to landscape/portrait/square (matches ingest)."""
    if width > height:
        return "landscape"
    if height > width:
        return "portrait"
    return "square"


def _build_speaker_transcript(transcript_parts: list[str]) -> tuple[str, int]:
    """Assign existing transcript parts to SPEAKER_00/SPEAKER_01.

    Produces the same \\n-delimited format the real diarization pipeline
    emits so BM25 search over speaker_transcript finds the same tokens
    as transcript_norm.
    """
    if not transcript_parts:
        return "", 0

    # 70% chance of dialog (2 speakers), 30% monologue (1 speaker).
    speaker_count = 2 if random.random() < 0.7 and len(transcript_parts) >= 2 else 1

    lines: list[str] = []
    for idx, part in enumerate(transcript_parts):
        speaker_idx = idx % speaker_count
        lines.append(f"SPEAKER_{speaker_idx:02d}: {part}")
    return "\n".join(lines), speaker_count


# --- AI Tags Pool (전부 한국어, vocabulary.py 기준) ---

# 행동/상황 태그 (VLM_KEYWORD_TAGS 한국어 display name)
KEYWORD_TAGS_POOL = [
    "제품 시연", "제품 리뷰", "언박싱", "사용법/튜토리얼", "비교", "비포/애프터",
    "가격 공개", "할인/특가", "세트/구성 소개", "한정 수량/타임딜",
    "쿠폰/이벤트", "무료배송", "사은품 증정",
    "질문/답변", "시청자 요청", "실시간 반응", "경품 추첨",
    "클로즈업/디테일", "발색/테스트", "성분 설명", "제형/텍스처",
    "사이즈 비교", "패키징", "착용/착화", "조리/시식",
]

# 제품 카테고리 태그 (VLM_PRODUCT_TAGS 한국어 display name)
PRODUCT_TAGS_POOL = [
    "스킨케어", "메이크업", "헤어케어", "바디케어", "향수/프래그런스", "네일", "뷰티 디바이스",
    "의류", "신발", "가방", "액세서리/주얼리",
    "식품", "건강식품/영양제", "가전", "주방용품", "인테리어/리빙", "반려동물",
    "전자기기", "모바일 액세서리", "유아/아동",
]

# 구체적 제품명 풀 (자유 형식)
PRODUCT_ENTITIES_POOL = [
    "레티놀 세럼", "비타민C 앰플", "히알루론산 토너",
    "매트 립스틱", "글로우 쿠션", "아이섀도 팔레트",
    "다이슨 에어랩", "스타일러 고데기", "헤어 트리트먼트",
    "센텔리안24 마데카 크림", "고주파 뷰티 디바이스", "LED 마스크",
    "프리미엄 한우 세트", "건강즙 세트", "비타민 영양제",
    "무선 청소기", "에어프라이어", "커피 머신",
    "메디큐브 AGR", "클렌징 디바이스", "폼 클렌저", "클렌징 오일",
    "크린랩", "주방용 랩", "위생 랩",
]

# AI 자유 형식 한국어 태그 (VLM이 상황 보고 자유롭게 붙이는 태그)
AI_TAGS_POOL = [
    "신제품 언박싱", "성분 설명", "실사용 후기", "가격 비교",
    "한정판 출시", "베스트셀러 소개", "MD 추천템", "사은품 증정 이벤트",
    "피부 타입별 추천", "데일리 메이크업", "프리미엄 라인",
    "계절 한정", "시즌 오프", "선물용 추천",
    "인플루언서 협업", "브랜드 앰버서더",
]



async def seed_database():
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with session_factory() as session:
        existing = await session.execute(select(Org).where(Org.slug == "devorg"))
        if existing.scalar_one_or_none():
            logger.info("seed_already_exists", msg="Database already seeded")
            return
        
        logger.info("seeding_database")
        
        org = Org(
            slug="devorg",
            name="Development Organization",
            auth0_org_id="org_V0Y81197qiMgjFFX",
        )
        session.add(org)
        await session.flush()
        logger.info("created_org", org_id=str(org.id), slug=org.slug)
        
        admin = User(org_id=org.id, email="admin@devorg.example.com", role=UserRole.ADMIN)
        member = User(org_id=org.id, email="member@devorg.example.com", role=UserRole.MEMBER)
        session.add_all([admin, member])
        await session.flush()
        logger.info("created_users", count=2)
        
        libraries = [
            Library(org_id=org.id, name="라이브커머스 영상", created_by_user_id=admin.id),
        ]
        session.add_all(libraries)
        await session.flush()
        logger.info("created_libraries", count=len(libraries))
        
        profiles = []
        for lib in libraries:
            profile = LibraryProfile(
                org_id=org.id,
                library_id=lib.id,
                status=ProfileStatus.ACTIVE,
                activated_at=datetime.now(timezone.utc),
            )
            profiles.append(profile)
        session.add_all(profiles)
        await session.flush()
        logger.info("created_profiles", count=len(profiles))
        
        drive_entries = [
            DriveNicknameRegistry(
                org_id=org.id,
                source_fingerprint_hash="abc123def456",
                nickname="작업용 외장 하드",
            ),
            DriveNicknameRegistry(
                org_id=org.id,
                source_fingerprint_hash="xyz789uvw012",
                nickname="Backup Drive",
            ),
        ]
        session.add_all(drive_entries)
        await session.flush()
        logger.info("created_drive_nicknames", count=len(drive_entries))
        
        people_clusters = [
            PeopleClusterLabel(org_id=org.id, person_cluster_id="cluster_001", label="김철수"),
            PeopleClusterLabel(org_id=org.id, person_cluster_id="cluster_002", label="이영희"),
            PeopleClusterLabel(org_id=org.id, person_cluster_id="cluster_003", label="John Smith"),
            PeopleClusterLabel(org_id=org.id, person_cluster_id="cluster_004", label=None),
            PeopleClusterLabel(org_id=org.id, person_cluster_id="cluster_005", label=None),
        ]
        session.add_all(people_clusters)
        await session.flush()
        logger.info("created_people_clusters", count=len(people_clusters))

        await seed_text_templates(session, org.id)

        # Fixture video_id 앞쪽 7개를 Face용으로 공유 —
        # FaceExemplar.video_id가 같은 fixture에서 만들어진 OpenSearch 장면과 조인됨.
        #
        # ``dict.fromkeys`` dedupes while preserving insertion order. A set
        # comprehension would work in CPython but ``list(set)`` ordering
        # depends on PYTHONHASHSEED so face↔scene joins could quietly shift
        # between `make seed` runs, breaking the people-video view.
        fixture_video_ids = list(
            dict.fromkeys(f["video_id"] for f in _load_scene_fixtures())
        )
        face_video_ids = fixture_video_ids[:7]
        await seed_faces(session, org.id, face_video_ids)

        drive_connection, drive_files = await seed_drive_files(
            session, org, libraries[0], admin, fixture_video_ids,
        )
        await seed_blur_jobs(session, org, admin, drive_files)

        await session.commit()

        await seed_opensearch(org, libraries, profiles, people_clusters, drive_entries)
        await seed_scenes(org, libraries, profiles, people_clusters, drive_entries)


SYSTEM_TEXT_PRESETS = [
    {
        "name": "기본",
        "font_family": "Noto Sans KR", "font_size_px": 48, "font_color": "#FFFFFF",
        "font_weight": 700, "line_height": 1.4, "letter_spacing": 0,
        "text_align": "center", "position_x": 0.5, "position_y": 0.85,
        "shadow_enabled": True, "shadow_color": "#000000",
        "shadow_offset_x": 2, "shadow_offset_y": 2, "shadow_blur": 4,
        "background_enabled": False, "background_color": None, "background_padding": 8,
    },
    {
        "name": "강조",
        "font_family": "Pretendard", "font_size_px": 64, "font_color": "#FFD700",
        "font_weight": 700, "line_height": 1.3, "letter_spacing": 0,
        "text_align": "center", "position_x": 0.5, "position_y": 0.5,
        "shadow_enabled": True, "shadow_color": "#000000",
        "shadow_offset_x": 3, "shadow_offset_y": 3, "shadow_blur": 6,
        "background_enabled": False, "background_color": None, "background_padding": 8,
    },
    {
        "name": "제품소개",
        "font_family": "Noto Sans KR", "font_size_px": 36, "font_color": "#FFFFFF",
        "font_weight": 400, "line_height": 1.5, "letter_spacing": 0,
        "text_align": "left", "position_x": 0.08, "position_y": 0.12,
        "shadow_enabled": False, "shadow_color": "#000000",
        "shadow_offset_x": 0, "shadow_offset_y": 0, "shadow_blur": 0,
        "background_enabled": True, "background_color": "#000000B3", "background_padding": 12,
    },
    {
        "name": "가격",
        "font_family": "Pretendard", "font_size_px": 56, "font_color": "#FF4444",
        "font_weight": 700, "line_height": 1.3, "letter_spacing": 0,
        "text_align": "center", "position_x": 0.5, "position_y": 0.5,
        "shadow_enabled": True, "shadow_color": "#FFFFFF",
        "shadow_offset_x": 2, "shadow_offset_y": 2, "shadow_blur": 4,
        "background_enabled": False, "background_color": None, "background_padding": 8,
    },
    {
        "name": "엔딩",
        "font_family": "Noto Sans KR", "font_size_px": 42, "font_color": "#FFFFFF",
        "font_weight": 700, "line_height": 1.4, "letter_spacing": 0,
        "text_align": "center", "position_x": 0.5, "position_y": 0.5,
        "shadow_enabled": True, "shadow_color": "#000000",
        "shadow_offset_x": 3, "shadow_offset_y": 3, "shadow_blur": 8,
        "background_enabled": False, "background_color": None, "background_padding": 8,
    },
]


async def seed_text_templates(session: AsyncSession, org_id) -> None:
    """시스템 프리셋 텍스트 템플릿 시딩. 이미 존재하는 이름은 건너뜀."""
    existing = await session.execute(
        select(TextTemplate).where(
            TextTemplate.org_id == org_id,
            TextTemplate.is_system_preset.is_(True),
        )
    )
    existing_names = {t.name for t in existing.scalars().all()}

    created = 0
    for preset in SYSTEM_TEXT_PRESETS:
        if preset["name"] in existing_names:
            continue
        template = TextTemplate(
            org_id=org_id,
            user_id=None,
            is_system_preset=True,
            **preset,
        )
        session.add(template)
        created += 1

    if created:
        await session.flush()
    logger.info("seeded_text_templates", created=created, skipped=len(existing_names))


async def seed_faces(session: AsyncSession, org_id, face_video_ids: list[str]) -> None:
    """얼굴 임베딩 시드 데이터 생성.

    face_embeddings.json (실제 영상에서 InsightFace ArcFace로 추출한 512차원 벡터)을
    읽어서 FaceIdentity + FaceExemplar를 Postgres pgvector에 저장.

    Idempotent: if the org already has any ``FaceIdentity`` rows, this
    function logs and returns without touching the DB. ``make seed`` is
    re-run frequently during local dev and we must not double-write the
    ArcFace rows — each re-seed would otherwise silently duplicate every
    identity + exemplar row, breaking the person-video count invariants.
    """
    existing = await session.execute(
        select(FaceIdentity).where(FaceIdentity.org_id == org_id).limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        logger.info("seed_faces_skipped", reason="existing rows for org")
        return

    with FACE_EMBEDDINGS_PATH.open(encoding="utf-8") as f:
        data = json.load(f)

    identities_data = data["identities"] + data.get("merge_test_identities", [])
    identity_count = 0
    exemplar_count = 0

    for i, ident_data in enumerate(identities_data):
        video_id = face_video_ids[i % len(face_video_ids)]

        # exemplar 중 가장 높은 품질 점수
        best_quality = max(ex["quality"] for ex in ident_data["exemplars"])

        identity = FaceIdentity(
            org_id=org_id,
            cluster_id=ident_data["cluster_id"],
            centroid_embedding=ident_data["centroid_embedding"],
            exemplar_count=len(ident_data["exemplars"]),
            best_quality=best_quality,
            best_thumbnail_video_id=video_id,
        )
        session.add(identity)
        await session.flush()
        identity_count += 1

        for j, ex in enumerate(ident_data["exemplars"]):
            scene_id = f"{video_id}_scene_{j:03d}"
            exemplar = FaceExemplar(
                identity_id=identity.id,
                org_id=org_id,
                video_id=video_id,
                scene_id=scene_id,
                embedding=ex["embedding"],
                quality=ex["quality"],
                bbox_json=ex["bbox"],
            )
            session.add(exemplar)
            exemplar_count += 1

    await session.flush()
    logger.info("seeded_faces", identities=identity_count, exemplars=exemplar_count)


async def seed_drive_files(
    session: AsyncSession, org, library, admin, fixture_video_ids: list[str],
) -> tuple[DriveConnection, list[DriveFile]]:
    """Create a DriveConnection and DriveFile per fixture video.

    DriveFiles are the Postgres counterpart to OpenSearch scenes — they let
    the video detail page resolve video_id → file UUID for blur, export,
    and metadata endpoints.
    """
    connection = DriveConnection(
        org_id=org.id,
        library_id=library.id,
        scope_type="drive",
        drive_id="seed_shared_drive_001",
        drive_name="Seed Shared Drive",
        status="active",
    )
    session.add(connection)
    await session.flush()

    fixtures = _load_scene_fixtures()
    video_meta: dict[str, dict] = {}
    for f in fixtures:
        vid = f["video_id"]
        if vid not in video_meta:
            video_meta[vid] = {
                "video_title": f.get("video_title", vid),
                "content_type": f.get("content_type", "video"),
                "start_ms": f.get("start_ms", 0),
                "end_ms": f.get("end_ms", 0),
                "image_width": f.get("image_width"),
                "image_height": f.get("image_height"),
            }
        else:
            end = f.get("end_ms", 0)
            if end > video_meta[vid]["end_ms"]:
                video_meta[vid]["end_ms"] = end

    drive_files = []
    for vid in fixture_video_ids:
        meta = video_meta.get(vid, {})
        scene_count = sum(1 for f in fixtures if f["video_id"] == vid)
        duration_ms = meta.get("end_ms", 300000)

        df = DriveFile(
            org_id=org.id,
            connection_id=connection.id,
            google_file_id=f"seed_{vid}",
            file_name=f"{meta.get('video_title', vid)}.mp4",
            mime_type="video/mp4" if meta.get("content_type") == "video" else "image/jpeg",
            video_id=vid,
            processing_status="indexed",
            scene_count=scene_count,
            proxy_s3_key=f"{org.id}/drive/proxies/{vid}/proxy.mp4",
            proxy_duration_ms=duration_ms,
            video_width=meta.get("image_width") or 1920,
            video_height=meta.get("image_height") or 1080,
            video_fps=30.0,
        )
        session.add(df)
        drive_files.append(df)

    await session.flush()
    logger.info("seeded_drive_files", count=len(drive_files))
    return connection, drive_files


async def seed_blur_jobs(
    session: AsyncSession, org, admin, drive_files: list[DriveFile],
) -> None:
    """Seed a completed blur job for the first video so the blur UI renders."""
    import hashlib

    video_files = [df for df in drive_files if df.mime_type == "video/mp4"]
    if not video_files:
        return

    target = video_files[0]
    job_id = uuid4()

    detections_summary = {"face": 12, "license_plate": 3}
    options = {
        "do_faces": True,
        "categories": ["face", "license_plate"],
    }
    options_hash = hashlib.sha256(json.dumps(options, sort_keys=True).encode()).hexdigest()

    now = datetime.now(timezone.utc)
    job = BlurJob(
        id=job_id,
        org_id=org.id,
        file_id=target.id,
        video_id=target.video_id,
        requested_by=admin.id,
        status="done",
        options=options,
        options_hash=options_hash,
        source_s3_key=target.proxy_s3_key or "",
        source_kind="proxy",
        blurred_s3_key=f"blurred/{target.video_id}/{job_id}/blurred.mp4",
        manifest_s3_key=f"blurred/{target.video_id}/{job_id}/manifest.json",
        mask_s3_keys={
            "face": f"blurred/{target.video_id}/{job_id}/masks/face.mkv",
            "license_plate": f"blurred/{target.video_id}/{job_id}/masks/license_plate.mkv",
        },
        detections_summary=detections_summary,
        progress_pct=100,
        phase="finalizing",
        requested_at=now - timedelta(minutes=10),
        started_at=now - timedelta(minutes=9),
        completed_at=now - timedelta(minutes=5),
    )
    session.add(job)
    await session.flush()

    await _upload_blur_manifest(org.id, target.video_id, str(job_id))
    logger.info("seeded_blur_job", job_id=str(job_id), video_id=target.video_id)


async def _upload_blur_manifest(org_id, video_id: str, job_id: str) -> None:
    """Upload a static blur manifest JSON to MinIO."""
    import boto3
    from botocore.config import Config as BotoConfig

    settings = get_settings()

    # Seed runs inside Docker — always use the internal hostname for uploads,
    # even when MINIO_ENDPOINT is set to localhost for browser presigned URLs.
    import os
    internal_endpoint = os.environ.get("MINIO_INTERNAL_ENDPOINT", "minio:9000")

    s3 = boto3.client(
        "s3",
        endpoint_url=f"http://{internal_endpoint}",
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        region_name=settings.s3_region,
        config=BotoConfig(signature_version="s3v4"),
    )

    bucket = settings.drive_s3_bucket
    try:
        s3.head_bucket(Bucket=bucket)
    except Exception:
        s3.create_bucket(Bucket=bucket)

    manifest = {
        "schema_version": "1.0",
        "video": {
            "fps": 30.0,
            "width": 1920,
            "height": 1080,
            "frame_count": 9000,
        },
        "summary": {"face": 12, "license_plate": 3},
        "detections": _generate_mock_detections(9000, 30.0),
        "mask_s3_keys": {
            "face": f"blurred/{video_id}/{job_id}/masks/face.mkv",
            "license_plate": f"blurred/{video_id}/{job_id}/masks/license_plate.mkv",
        },
    }

    key = f"blurred/{video_id}/{job_id}/manifest.json"
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(manifest),
        ContentType="application/json",
    )
    logger.info("uploaded_blur_manifest", key=key)


def _generate_mock_detections(frame_count: int, fps: float) -> list[dict]:
    detections = []
    rng = random.Random(42)

    for i in range(12):
        frame_idx = rng.randint(0, frame_count - 1)
        detections.append({
            "frame_idx": frame_idx,
            "t_ms": int(frame_idx / fps * 1000),
            "category": "face",
            "label": "person",
            "confidence": round(rng.uniform(0.85, 0.99), 3),
            "bbox_norm": [
                round(rng.uniform(0.1, 0.7), 3),
                round(rng.uniform(0.1, 0.5), 3),
                round(rng.uniform(0.05, 0.2), 3),
                round(rng.uniform(0.1, 0.3), 3),
            ],
            "from_cache": False,
        })

    for i in range(3):
        frame_idx = rng.randint(0, frame_count - 1)
        detections.append({
            "frame_idx": frame_idx,
            "t_ms": int(frame_idx / fps * 1000),
            "category": "license_plate",
            "label": "license plate",
            "confidence": round(rng.uniform(0.7, 0.95), 3),
            "bbox_norm": [
                round(rng.uniform(0.2, 0.6), 3),
                round(rng.uniform(0.4, 0.8), 3),
                round(rng.uniform(0.08, 0.15), 3),
                round(rng.uniform(0.03, 0.08), 3),
            ],
            "from_cache": False,
        })

    detections.sort(key=lambda d: d["frame_idx"])
    return detections


async def seed_opensearch(org, libraries, profiles, people_clusters, drive_entries):
    logger.info("seeding_opensearch")
    
    client = OpenSearchClient()
    
    try:
        await client.ensure_index_exists()
        
        documents = []
        cluster_ids = [p.person_cluster_id for p in people_clusters]
        drive_nicknames = {d.source_fingerprint_hash: d.nickname for d in drive_entries}
        
        for lib_idx, (library, profile) in enumerate(zip(libraries, profiles)):
            num_videos = random.randint(10, 20)
            
            for video_idx in range(num_videos):
                video_id = str(uuid4())
                is_korean_lib = lib_idx == 0
                
                source_type = random.choice(["gdrive", "removable_disk", "local"])
                required_drive = None
                if source_type == "removable_disk":
                    fingerprint = random.choice(list(drive_nicknames.keys()))
                    required_drive = drive_nicknames[fingerprint]
                
                num_segments = random.randint(5, 15)
                current_ms = 0
                
                for seg_idx in range(num_segments):
                    segment_id = f"{video_id}_seg_{seg_idx:03d}"
                    duration_ms = random.randint(2000, 60000)
                    start_ms = current_ms
                    end_ms = current_ms + duration_ms
                    current_ms = end_ms + 100
                    
                    if is_korean_lib or random.random() < 0.3:
                        transcript = random.choice(KOREAN_TRANSCRIPTS)
                    else:
                        transcript = random.choice(ENGLISH_TRANSCRIPTS)
                    
                    segment_people = random.sample(
                        cluster_ids, k=random.randint(0, min(3, len(cluster_ids)))
                    )
                    
                    capture_time = datetime.now(timezone.utc) - timedelta(
                        days=random.randint(1, 365),
                        hours=random.randint(0, 23),
                    )
                    
                    embedding = generate_mock_embedding(transcript)
                    
                    doc = {
                        "org_id": str(org.id),
                        "library_id": str(library.id),
                        "library_profile_id": str(profile.id),
                        "library_name": library.name,
                        "video_id": video_id,
                        "segment_id": segment_id,
                        "start_ms": start_ms,
                        "end_ms": end_ms,
                        "transcript_raw": transcript,
                        "transcript_norm": transcript.lower(),
                        "source_type": source_type,
                        "required_drive_nickname": required_drive,
                        "people_cluster_ids": segment_people,
                        "capture_time": capture_time.isoformat(),
                        "ingest_time": datetime.now(timezone.utc).isoformat(),
                        "thumbnail_url": f"https://placeholder.heimdex.local/thumb/{segment_id}.jpg",
                        "sprite_url": f"https://placeholder.heimdex.local/sprite/{segment_id}.jpg",
                        "word_timing_uri": f"s3://heimdex-assets/{org.id}/timings/{segment_id}.json",
                        "embedding_vector": embedding,
                    }
                    
                    documents.append((segment_id, doc))
        
        batch_size = 100
        for i in range(0, len(documents), batch_size):
            batch = documents[i : i + batch_size]
            await client.bulk_index(batch)
        
        logger.info("opensearch_seeding_complete", total_documents=len(documents))
        
    finally:
        await client.close()


async def seed_scenes(org, libraries, profiles, people_clusters, drive_entries):
    """OpenSearch scenes 인덱스 시드 데이터 생성 (fixture 기반).

    scenes.json (scripts/extract_seed_fixtures.py + recover_timestamps.py
    로 실제 라이브커머스 자산에서 추출)이 재시드해도 변하지 않아야 하는
    필드의 소유자:
      - scene_id / video_id / video_title
      - content_type ("video" | "image")
      - start_ms / end_ms / keyframe_timestamp_ms
      - image_width / image_height
      - dominant_colors + color_embedding (27차원 HSL 히스토그램)

    런타임에서 채우는 랜덤 필드: transcript, speaker_transcript,
    people_cluster_ids, source_type, required_drive, capture_time.

    VAF 워커 산출물은 seed 풀에서 주입:
      - visual_embedding (SigLIP2 768dim — visual_embeddings.json 풀)
      - keyword_tags / product_tags / product_entities / ai_tags
        (이 모듈 상단의 한국어 풀)

    Face 쪽 video_id는 seed_database에서 fixture video_id 앞쪽 7개를
    face_video_ids로 전달 → FaceExemplar.video_id가 같은 fixture에서
    만들어진 OpenSearch 장면 문서와 조인됨.

    같은 video_id의 모든 장면은 source_type / required_drive /
    capture_time을 공유 (실 파이프라인이 영상 단위로 부여하는 방식 반영).
    """
    logger.info("seeding_scenes")

    client = SceneSearchClient()

    # visual_embeddings.json에서 SigLIP2 768dim 벡터를 video_id 단위로 로드.
    #
    # Keeping the per-video structure (instead of flattening into a global
    # pool) means every scene from the same video draws its visual embedding
    # from that video's own keyframe pool. Vector search over a seeded video
    # then returns the same video's other scenes as near-neighbours, which
    # is the correct dev demo. Flattening and random-sampling across videos
    # would return semantically unrelated neighbours and make visual-search
    # look broken in local dev.
    visual_embeddings_by_video: dict[str, list[list[float]]] = {}
    visual_embedding_fallback_pool: list[list[float]] = []
    try:
        with VISUAL_EMBEDDINGS_PATH.open(encoding="utf-8") as f:
            visual_data = json.load(f)
        for vid, video_embs in visual_data.get("videos", {}).items():
            vecs = [emb["embedding"] for emb in video_embs if emb.get("embedding")]
            if vecs:
                visual_embeddings_by_video[vid] = vecs
                visual_embedding_fallback_pool.extend(vecs)
        logger.info(
            "loaded_visual_embeddings",
            videos=len(visual_embeddings_by_video),
            total_vectors=len(visual_embedding_fallback_pool),
        )
    except FileNotFoundError:
        logger.warning("visual_embeddings_not_found", path=str(VISUAL_EMBEDDINGS_PATH))

    try:
        await client.ensure_index_exists()

        fixtures = _load_scene_fixtures()
        cluster_ids = [p.person_cluster_id for p in people_clusters]
        drive_nicknames = {d.source_fingerprint_hash: d.nickname for d in drive_entries}

        library = libraries[0]
        org_id_str = str(org.id)

        scenes_by_video: dict[str, list[dict]] = {}
        for fixture in fixtures:
            scenes_by_video.setdefault(fixture["video_id"], []).append(fixture)

        documents: list[tuple[str, dict]] = []
        video_count = 0
        image_count = 0

        for video_id, video_fixtures in scenes_by_video.items():
            source_type = random.choice(["gdrive", "removable_disk", "local"])
            required_drive = None
            if source_type == "removable_disk":
                fingerprint = random.choice(list(drive_nicknames.keys()))
                required_drive = drive_nicknames[fingerprint]

            capture_time = datetime.now(timezone.utc) - timedelta(
                days=random.randint(1, 365),
                hours=random.randint(0, 23),
            )

            is_image = video_fixtures[0]["content_type"] == "image"
            if is_image:
                image_count += len(video_fixtures)
            else:
                video_count += 1

            # Resolve this video's visual-embedding pool ONCE so every
            # scene in this video shares the same pool. Falls back to the
            # flattened cross-video pool only if the fixture has no
            # entry for this video_id (happens e.g. for image-only
            # assets where keyframe extraction never ran).
            video_visual_pool = visual_embeddings_by_video.get(
                video_id,
                visual_embedding_fallback_pool,
            )

            for scene_idx, fixture in enumerate(video_fixtures):
                if fixture["content_type"] == "image":
                    doc_entry = _build_image_scene_doc(
                        fixture=fixture,
                        org_id_str=org_id_str,
                        library=library,
                        source_type=source_type,
                        required_drive=required_drive,
                        capture_time=capture_time,
                        cluster_ids=cluster_ids,
                    )
                else:
                    doc_entry = _build_video_scene_doc(
                        fixture=fixture,
                        org_id_str=org_id_str,
                        library=library,
                        source_type=source_type,
                        required_drive=required_drive,
                        capture_time=capture_time,
                        cluster_ids=cluster_ids,
                    )

                # VAF 워커 산출물 주입 — helper에서 zero/empty placeholder로 넣어둔 자리.
                # Visual embedding is round-robin'd through this video's own
                # keyframe pool (indexed by scene position) so scenes from
                # the same video cluster together in vector space, making
                # local vector-search demos return visually related results.
                _, scene_doc = doc_entry
                if video_visual_pool:
                    scene_doc["visual_embedding"] = video_visual_pool[
                        scene_idx % len(video_visual_pool)
                    ]
                scene_doc["keyword_tags"] = random.sample(KEYWORD_TAGS_POOL, k=random.randint(0, 3))
                scene_doc["product_tags"] = random.sample(PRODUCT_TAGS_POOL, k=random.randint(0, 2))
                scene_doc["product_entities"] = random.sample(PRODUCT_ENTITIES_POOL, k=random.randint(0, 2))
                scene_doc["ai_tags"] = random.sample(AI_TAGS_POOL, k=random.randint(0, 2))

                documents.append(doc_entry)

        batch_size = 100
        for i in range(0, len(documents), batch_size):
            batch = documents[i : i + batch_size]
            await client.bulk_index_scenes(batch)

        logger.info(
            "scene_seeding_complete",
            total_documents=len(documents),
            video_assets=video_count,
            image_assets=image_count,
        )

    finally:
        await client.close()


def _build_video_scene_doc(
    *,
    fixture: dict,
    org_id_str: str,
    library,
    source_type: str,
    required_drive: str | None,
    capture_time: datetime,
    cluster_ids: list[str],
) -> tuple[str, dict]:
    """Build a video-type scene document from a fixture entry.

    transcript / speaker_transcript / people_cluster_ids are generated
    here — the real pipeline sources them from STT + diarization, which
    the color-focused seed does not model. visual_embedding /
    keyword_tags / product_tags / ai_tags are zero/empty placeholders
    because those fields belong to Jaehee's workers.
    """
    scene_id = fixture["scene_id"]
    video_id = fixture["video_id"]

    num_speech_segments = random.randint(2, 4)
    transcript_parts = [
        random.choice(KOREAN_TRANSCRIPTS)
        for _ in range(num_speech_segments)
    ]
    transcript_raw = " ".join(transcript_parts)
    speaker_transcript, speaker_count = _build_speaker_transcript(transcript_parts)
    embedding = generate_mock_embedding(transcript_raw)

    scene_people = random.sample(
        cluster_ids, k=random.randint(0, min(3, len(cluster_ids)))
    )

    doc = {
        "org_id": org_id_str,
        "library_id": str(library.id),
        "video_id": video_id,
        "video_title": fixture["video_title"],
        "scene_id": scene_id,
        "start_ms": fixture["start_ms"],
        "end_ms": fixture["end_ms"],
        "keyframe_timestamp_ms": fixture["keyframe_timestamp_ms"],
        "transcript_raw": transcript_raw,
        "transcript_norm": transcript_raw.lower(),
        "transcript_char_count": len(transcript_raw),
        "speech_segment_count": num_speech_segments,
        "speaker_transcript": speaker_transcript,
        "speaker_count": speaker_count,
        "content_type": "video",
        "source_type": source_type,
        "required_drive_nickname": required_drive,
        "people_cluster_ids": scene_people,
        "capture_time": capture_time.isoformat(),
        "ingest_time": datetime.now(timezone.utc).isoformat(),
        "thumbnail_url": f"https://placeholder.heimdex.local/thumb/{scene_id}.jpg",
        "embedding_vector": embedding,
        "dominant_colors": fixture["dominant_colors"],
        "color_embedding": fixture["color_embedding"],
        "visual_embedding": [0.0] * 768,
        "keyword_tags": [],
        "product_tags": [],
        "ai_tags": [],
    }

    return (f"{org_id_str}:{scene_id}", doc)


def _build_image_scene_doc(
    *,
    fixture: dict,
    org_id_str: str,
    library,
    source_type: str,
    required_drive: str | None,
    capture_time: datetime,
    cluster_ids: list[str],
) -> tuple[str, dict]:
    """Build a single-scene image asset document from a fixture entry.

    Image scenes have no spoken transcript or speaker data; filename_text
    carries the primary text signal for BM25 search (matches ingest).
    """
    scene_id = fixture["scene_id"]
    video_id = fixture["video_id"]
    filename = fixture["video_title"]
    width = fixture["image_width"]
    height = fixture["image_height"]
    orientation = _classify_orientation(width, height)

    # Feed the filename into the semantic vector so text search over
    # images still surfaces them (e.g. "립스틱" hits the lipstick image).
    embedding = generate_mock_embedding(filename)

    scene_people = random.sample(
        cluster_ids, k=random.randint(0, min(2, len(cluster_ids)))
    )

    doc = {
        "org_id": org_id_str,
        "library_id": str(library.id),
        "video_id": video_id,
        "video_title": filename,
        "scene_id": scene_id,
        "start_ms": 0,
        "end_ms": 0,
        "keyframe_timestamp_ms": 0,
        "transcript_raw": "",
        "transcript_norm": "",
        "transcript_char_count": 0,
        "speech_segment_count": 0,
        "speaker_transcript": "",
        "speaker_count": 0,
        "content_type": "image",
        "filename_text": filename,
        "image_width": width,
        "image_height": height,
        "image_orientation": orientation,
        "source_type": source_type,
        "required_drive_nickname": required_drive,
        "people_cluster_ids": scene_people,
        "capture_time": capture_time.isoformat(),
        "ingest_time": datetime.now(timezone.utc).isoformat(),
        "thumbnail_url": f"https://placeholder.heimdex.local/thumb/{scene_id}.jpg",
        "embedding_vector": embedding,
        "dominant_colors": fixture["dominant_colors"],
        "color_embedding": fixture["color_embedding"],
        "visual_embedding": [0.0] * 768,
        "keyword_tags": [],
        "product_tags": [],
        "ai_tags": [],
    }

    return (f"{org_id_str}:{scene_id}", doc)


async def main():
    try:
        await seed_database()
        logger.info("seeding_complete")
    except Exception as e:
        logger.exception("seeding_failed", error=str(e))
        raise


if __name__ == "__main__":
    asyncio.run(main())
