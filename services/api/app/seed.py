import asyncio
import random
from datetime import datetime, timedelta, timezone
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

# Human-readable video titles for seed data (simulates agent-derived filenames)
KOREAN_VIDEO_TITLES = [
    "2025년 1분기 전사 회의",
    "신규 프로젝트 킥오프 미팅",
    "마케팅 전략 수정 회의",
    "고객 피드백 분석 결과 공유",
    "제품 출시 최종 점검",
    "팀 워크샵 아이디어 발표",
    "클라우드 마이그레이션 완료 보고",
    "AI 추천 시스템 기술 세미나",
    "보안 취약점 패치 리뷰",
    "UX 개선 A/B 테스트 결과",
    "데이터베이스 최적화 성과 발표",
    "모바일 앱 업데이트 데모",
    "고객지원 프로세스 개선 회의",
    "신규 파트너십 논의",
    "분기별 실적 보고",
]

ENGLISH_VIDEO_TITLES = [
    "Q1 2025 Quarterly Results Review",
    "Product Roadmap Planning Session",
    "Customer Satisfaction Deep Dive",
    "Scalability Workshop Part 1",
    "Feature Launch Retrospective",
    "Team Collaboration Best Practices",
    "Security Audit Findings Review",
    "Platform Migration Status Update",
    "User Engagement Analytics Demo",
    "Sprint Planning - Week 12",
    "Onboarding Training Session",
    "API Integration Workshop",
    "Performance Optimization Results",
    "Cross-Team Sync Meeting",
    "Year-End Review Presentation",
]

TRAINING_VIDEO_TITLES = [
    "New Employee Onboarding Guide",
    "Git Workflow Training",
    "Cloud Infrastructure Basics",
    "CI/CD Pipeline Setup Tutorial",
    "Code Review Best Practices",
    "Incident Response Playbook",
    "Data Privacy Compliance Training",
    "Agile Methodology Overview",
    "Kubernetes Deployment Training",
    "Monitoring and Alerting Setup",
]

# Live-commerce style product image filenames (simulates Drive assets).
KOREAN_IMAGE_FILENAMES = [
    "봄신상_립스틱_정면.jpg",
    "여름컬렉션_원피스_상세01.jpg",
    "겨울_패딩_후드업_뒷면.jpg",
    "리얼핏_부츠_측면.jpg",
    "스킨케어_로션_500ml_제품컷.jpg",
    "네일아트_레드톤_핸드샷.jpg",
    "뷰티_세럼_패키지_정면.jpg",
    "가방_크로스백_베이지_스튜디오.jpg",
    "아우터_트렌치코트_모델착장.jpg",
    "주방용품_프라이팬_28cm.jpg",
]

ENGLISH_IMAGE_FILENAMES = [
    "SS25_RED_SKU001_front.jpg",
    "FW24_OUTERWEAR_NAVY_back.jpg",
    "HERO_BANNER_SERUM_1920x1080.jpg",
    "LOOKBOOK_SPRING_EDITORIAL_03.jpg",
    "PDP_MAIN_SNEAKER_WHITE_side.jpg",
    "CAMPAIGN_SUMMER_BEACH_landscape.jpg",
    "DETAIL_SHOT_WATCH_SILVER_close.jpg",
    "PACKSHOT_SKINCARE_KIT_studio.jpg",
    "THUMB_NEW_ARRIVAL_BAG_beige.jpg",
    "COLLECTION_NAVY_COAT_model.jpg",
]

# Common product-photography aspect ratios in landscape/portrait/square.
SEED_IMAGE_DIMENSIONS: list[tuple[int, int]] = [
    (1920, 1080),  # landscape 16:9
    (1280, 720),   # landscape 16:9
    (1200, 800),   # landscape 3:2
    (1080, 1920),  # portrait 9:16 (mobile-first)
    (720, 1280),   # portrait 9:16
    (800, 1200),   # portrait 2:3
    (1080, 1080),  # square 1:1
    (1200, 1200),  # square 1:1
]


def _classify_orientation(width: int, height: int) -> str:
    """Map image dimensions to landscape/portrait/square (matches ingest)."""
    if width > height:
        return "landscape"
    if height > width:
        return "portrait"
    return "square"


def _build_speaker_transcript(
    transcript_parts: list[str], rng: random.Random
) -> tuple[str, int]:
    """Assign existing transcript parts to SPEAKER_00/SPEAKER_01.

    Produces the same \\n-delimited format the real diarization pipeline
    emits so BM25 search over speaker_transcript finds the same tokens
    as transcript_norm.
    """
    if not transcript_parts:
        return "", 0

    # 70% chance of dialog (2 speakers), 30% monologue (1 speaker).
    speaker_count = 2 if rng.random() < 0.7 and len(transcript_parts) >= 2 else 1

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
            Library(org_id=org.id, name="회사 회의 영상", created_by_user_id=admin.id),
            Library(org_id=org.id, name="Product Demos", created_by_user_id=admin.id),
            Library(org_id=org.id, name="Training Videos", created_by_user_id=member.id),
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
    """Seed the scenes index with fabricated scene documents.

    Content mix:
      - ~90% of assets are videos with 3-5 scenes each.
      - ~10% are single-scene image assets (content_type="image") with
        image_width/height/orientation + filename_text so the image-only
        and mixed content_types filters have something to return locally.

    Doc IDs follow the "{org_id}:{scene_id}" convention required by mget_scenes.
    """
    logger.info("seeding_scenes")

    client = SceneSearchClient()

    try:
        await client.ensure_index_exists()

        documents: list[tuple[str, dict]] = []
        cluster_ids = [p.person_cluster_id for p in people_clusters]
        drive_nicknames = {d.source_fingerprint_hash: d.nickname for d in drive_entries}
        org_id_str = str(org.id)

        image_ratio = 0.10  # ~10% of assets are still images
        video_count = 0
        image_count = 0

        for lib_idx, (library, profile) in enumerate(zip(libraries, profiles)):
            num_videos = random.randint(5, 10)
            is_korean_lib = lib_idx == 0

            if lib_idx == 0:
                title_pool = KOREAN_VIDEO_TITLES
                image_pool = KOREAN_IMAGE_FILENAMES
            elif lib_idx == 2:
                title_pool = TRAINING_VIDEO_TITLES
                image_pool = ENGLISH_IMAGE_FILENAMES
            else:
                title_pool = ENGLISH_VIDEO_TITLES
                image_pool = ENGLISH_IMAGE_FILENAMES

            for video_idx in range(num_videos):
                video_id = str(uuid4())
                is_image_asset = random.random() < image_ratio

                source_type = random.choice(["gdrive", "removable_disk", "local"])
                required_drive = None
                if source_type == "removable_disk":
                    fingerprint = random.choice(list(drive_nicknames.keys()))
                    required_drive = drive_nicknames[fingerprint]

                capture_time = datetime.now(timezone.utc) - timedelta(
                    days=random.randint(1, 365),
                    hours=random.randint(0, 23),
                )

                if is_image_asset:
                    documents.append(
                        _build_image_scene_doc(
                            org_id_str=org_id_str,
                            library=library,
                            video_id=video_id,
                            image_pool=image_pool,
                            source_type=source_type,
                            required_drive=required_drive,
                            capture_time=capture_time,
                            cluster_ids=cluster_ids,
                        )
                    )
                    image_count += 1
                    continue

                video_title = title_pool[video_idx % len(title_pool)]
                num_scenes = random.randint(3, 5)
                current_ms = 0

                for scene_idx in range(num_scenes):
                    scene_id = f"{video_id}_scene_{scene_idx:03d}"

                    duration_ms = random.randint(10000, 90000)
                    start_ms = current_ms
                    end_ms = current_ms + duration_ms
                    current_ms = end_ms

                    num_speech_segments = random.randint(2, 4)
                    transcript_pool = KOREAN_TRANSCRIPTS if (is_korean_lib or random.random() < 0.3) else ENGLISH_TRANSCRIPTS
                    transcript_parts = [
                        random.choice(transcript_pool)
                        for _ in range(num_speech_segments)
                    ]
                    transcript_raw = " ".join(transcript_parts)

                    speaker_transcript, speaker_count = _build_speaker_transcript(
                        transcript_parts, random
                    )

                    scene_people = random.sample(
                        cluster_ids, k=random.randint(0, min(3, len(cluster_ids)))
                    )

                    embedding = generate_mock_embedding(transcript_raw)

                    doc = {
                        "org_id": org_id_str,
                        "library_id": str(library.id),
                        "video_id": video_id,
                        "video_title": video_title,
                        "scene_id": scene_id,
                        "start_ms": start_ms,
                        "end_ms": end_ms,
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
                        "keyframe_timestamp_ms": (start_ms + end_ms) // 2,
                        "embedding_vector": embedding,
                    }

                    documents.append((f"{org_id_str}:{scene_id}", doc))

                video_count += 1

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


def _build_image_scene_doc(
    *,
    org_id_str: str,
    library,
    video_id: str,
    image_pool: list[str],
    source_type: str,
    required_drive: str | None,
    capture_time: datetime,
    cluster_ids: list[str],
) -> tuple[str, dict]:
    """Build a single-scene image asset document.

    Image scenes have no spoken transcript or speaker data; filename_text
    carries the primary text signal for BM25 search (matches ingest).
    """
    scene_id = f"{video_id}_scene_000"
    filename = random.choice(image_pool)
    width, height = random.choice(SEED_IMAGE_DIMENSIONS)
    orientation = _classify_orientation(width, height)

    # Generate the semantic vector from the filename so text search over
    # images behaves sensibly (e.g. "립스틱" still surfaces image assets).
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
        "keyframe_timestamp_ms": 0,
        "embedding_vector": embedding,
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
