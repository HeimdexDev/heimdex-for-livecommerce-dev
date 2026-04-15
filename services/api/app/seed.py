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
FIXTURE_PATH = Path(__file__).parent / "db" / "seed" / "fixtures" / "scenes.json"


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
    """Seed system preset text templates. Idempotent — skips existing by name."""
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
    """Seed the scenes index from fixture data extracted from real assets.

    scenes.json (produced by scripts/extract_seed_fixtures.py and patched
    with real timestamps by scripts/recover_timestamps.py) owns the fields
    that must stay stable across reseeds so the color-search work has a
    realistic, reproducible corpus:
      - scene_id / video_id / video_title
      - content_type ("video" or "image")
      - start_ms / end_ms / keyframe_timestamp_ms
      - image_width / image_height
      - dominant_colors + color_embedding (27-dim HSL histogram)

    Seed runtime fills the random, per-run fields (transcript, speaker
    transcript, people_cluster_ids, source_type, required_drive, capture
    time). Fields owned by Jaehee's workers (visual_embedding,
    keyword_tags, product_tags, ai_tags) are inserted as zero/empty
    placeholders and rebased in when those workers land.

    All scenes from the same video_id share a single source_type /
    required drive nickname / capture_time, matching how the real ingest
    pipeline assigns those at the video level.
    """
    logger.info("seeding_scenes")

    client = SceneSearchClient()

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

            for fixture in video_fixtures:
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
