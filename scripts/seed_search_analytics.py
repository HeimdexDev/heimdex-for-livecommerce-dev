"""Golden-dataset seed generator for Looker preview.

Emits 30 daily Parquet files matching `export_analytics._rows_to_parquet`
schema, so they can be uploaded to S3 under
`analytics_seed/search_events/year=.../month=.../day=.../YYYY-MM-DD.parquet`
and picked up by a seed-only BQ External Table.

Story:
  - Weekday 300 / weekend 100 rows → ~7,000 total over 30 days
  - Semantic ratio grows over time (20% → 40%) — adoption trend
  - Color popularity: pink > red > brown > ... (brown zero_rate higher)
  - Day x hour distribution: weekday 10-17 peak
  - Filter usage: include_ocr 30 / person 15 / source 20 / date 25 / color 25
  - Per-mode latency: metadata mu=300 / lexical mu=800 / semantic mu=2000 ms

Usage (host):
  python3 scripts/seed_search_analytics.py --out scripts/seed_output

Upload to S3 (example):
  aws s3 sync scripts/seed_output/ \\
    s3://heimdex-drive-staging/analytics_seed/search_events/

Deterministic (seed=42) — rerunning produces the same files.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import random
import sys
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SEED = 42
END_DATE = date(2026, 4, 14)
DAYS = 30
START_DATE = END_DATE - timedelta(days=DAYS - 1)

# ---------------------------------------------------------------------------
# Fixed orgs/users (separate UUID pool — not staging collisions, for dataset A)
# ---------------------------------------------------------------------------
ORGS = [
    {"id": "11111111-1111-4111-8111-111111111111", "name": "livenow-seed"},
    {"id": "22222222-2222-4222-8222-222222222222", "name": "ebsdemo-seed"},
    {"id": "33333333-3333-4333-8333-333333333333", "name": "devorg-seed"},
    {"id": "44444444-4444-4444-8444-444444444444", "name": "brandlab-seed"},
]
ORG_WEIGHTS = [0.55, 0.20, 0.15, 0.10]  # top org dominates per §3-10


def _build_user_pool() -> list[dict]:
    rng = random.Random(SEED)
    users: list[dict] = []
    for org in ORGS:
        n = rng.randint(5, 10)
        for i in range(n):
            uid = str(uuid.UUID(int=rng.getrandbits(128), version=4))
            users.append(
                {
                    "id": uid,
                    "email": f"seed-user-{i+1:02d}@{org['name']}.local",
                    "org_id": org["id"],
                    "org_name": org["name"],
                }
            )
    return users


# ---------------------------------------------------------------------------
# Color story (§3-11, §4-4)
# ---------------------------------------------------------------------------
COLOR_WEIGHTS = {
    "pink": 18, "red": 16, "brown": 14, "blue": 10, "white": 9,
    "teal": 8, "orange": 6, "green": 5, "purple": 5, "gray": 4,
    "black": 3, "yellow": 2,
}
COLOR_ZERO_RATE = {
    "pink": 0.08, "red": 0.10, "brown": 0.30, "blue": 0.12, "white": 0.15,
    "teal": 0.18, "orange": 0.18, "green": 0.15, "purple": 0.20, "gray": 0.15,
    "black": 0.10, "yellow": 0.25,
}

# ---------------------------------------------------------------------------
# Query pools per mode (§3-6)
# ---------------------------------------------------------------------------
BRANDS = [
    "아이소이", "콜라겐", "센트룸", "라이크유", "센소다인",
    "블렘토", "펠리코", "롯데웰푸드", "베노프", "히니크", "농수산",
]
PRODUCT_NAMES = [
    "화장품", "립스틱", "원피스", "건강식품", "치약", "프로틴",
    "비타민", "크림", "세럼", "립밤", "영양제",
]
COLOR_PHRASES = [
    "분홍 원피스", "빨강 립스틱", "파랑 원피스", "검정 코트", "흰색 블라우스",
    "주황 가방", "노랑 티셔츠", "초록 스웨터", "갈색 부츠", "보라 스카프",
    "회색 자켓", "분홍 립스틱", "빨강 원피스", "파랑 티셔츠", "검정 부츠",
    "흰색 크림", "갈색 코트", "분홍 블라우스", "빨강 자켓", "파랑 스카프",
    "초록 원피스", "노랑 가방", "주황 립스틱",
]
PERSON_NAMES = ["김진행자", "이호스트", "박쇼호스트", "최앵커", "정진행"]
NATURAL = [
    "제품 소개 장면", "모델이 착용한 것", "진행자가 설명하는 부분",
    "제품 비교 장면", "박스 언박싱 장면", "성분 설명 구간",
    "할인 안내 장면", "시연하는 모습",
]
FILE_STYLE = [
    "260303_센트룸", "260304_펠리코", "260304_히니크", "260309_센소다인",
    "260310_라이크유", "260311_베노프", "260312_농수산", "260312_블렘토",
    "260314_아이소이", "260315_롯데웰푸드", "20260301", "20260315",
]
ZERO_QUERIES = [
    "보이지않는상품", "존재하지않는제품", "랜덤쿼리xyz", "없는것",
    "qwerasdf", "없는상품명", "오타쿼리", "비어있는검색", "결과없음테스트",
    "nonexistent", "unknown-item", "테스트존재안함",
]

SOURCE_TYPES_POOL = [
    ["upload"], ["youtube"], ["upload", "youtube"], ["drive"],
    ["upload", "drive"],
]

# ---------------------------------------------------------------------------
# Distribution helpers
# ---------------------------------------------------------------------------


def _semantic_ratio_on(day_idx: int, total_days: int) -> float:
    """Adoption curve: 20% → 40% linear over the month."""
    return 0.20 + (0.20 * day_idx / max(total_days - 1, 1))


def _mode_for(rng: random.Random, day_idx: int, total_days: int) -> str:
    semantic = _semantic_ratio_on(day_idx, total_days)
    remaining = 1.0 - semantic
    # metadata : lexical = 15 : 55 baseline → keep proportions of remainder
    metadata_share = remaining * (15 / 70)
    r = rng.random()
    if r < semantic:
        return "semantic"
    if r < semantic + remaining - metadata_share:
        return "lexical"
    return "metadata"


def _pick_hour_weekday(rng: random.Random) -> int:
    """Peak 10-17 heavy (~70% of weekday volume)."""
    r = rng.random()
    if r < 0.70:
        return rng.randint(10, 17)
    if r < 0.90:
        return rng.choice([8, 9, 18, 19, 20])
    return rng.choice([0, 1, 2, 3, 4, 5, 6, 7, 21, 22, 23])


def _pick_hour_weekend(rng: random.Random) -> int:
    r = rng.random()
    if r < 0.40:
        return rng.randint(12, 20)
    if r < 0.75:
        return rng.choice([9, 10, 11, 21, 22])
    return rng.choice([0, 1, 2, 3, 4, 5, 6, 7, 8, 23])


def _pick_color(rng: random.Random) -> str:
    colors = list(COLOR_WEIGHTS.keys())
    weights = list(COLOR_WEIGHTS.values())
    return rng.choices(colors, weights=weights, k=1)[0]


def _response_ms(rng: random.Random, mode: str) -> int:
    mu = {"metadata": 300, "lexical": 800, "semantic": 2000}[mode]
    sigma = {"metadata": 80, "lexical": 250, "semantic": 600}[mode]
    v = int(rng.gauss(mu, sigma))
    # Tail — 5% chance of >3000 ms for slow-query bucket
    if rng.random() < 0.05:
        v = rng.randint(3000, 6000)
    return max(50, v)


def _alpha(rng: random.Random) -> float:
    r = rng.random()
    if r < 0.60:
        return 0.5
    if r < 0.85:
        return round(rng.uniform(0.7, 1.0), 2)
    return round(rng.uniform(0.0, 0.3), 2)


def _query_text(rng: random.Random, mode: str, color: str | None, is_zero: bool) -> str:
    # Color-filtered rows — 3-way split:
    #   40% color+product phrase (query text already names the color)
    #   30% brand/product name only (color applied via filter, not text)
    #   30% empty string (color-only search → Page 2 Top Query #1)
    if color:
        r = rng.random()
        if r < 0.40:
            return rng.choice(COLOR_PHRASES)
        if r < 0.70:
            if rng.random() < 0.5:
                return rng.choice(BRANDS)
            return rng.choice(PRODUCT_NAMES)
        return ""
    if is_zero:
        return rng.choice(ZERO_QUERIES)
    if mode == "metadata":
        return rng.choice(FILE_STYLE)
    if mode == "semantic":
        return rng.choice(NATURAL)
    # lexical
    r = rng.random()
    if r < 0.50:
        return rng.choice(BRANDS)
    if r < 0.75:
        return rng.choice(PRODUCT_NAMES)
    if r < 0.90:
        return rng.choice(PERSON_NAMES)
    return rng.choice(FILE_STYLE)


def _metadata(
    rng: random.Random,
    *,
    include_ocr: bool,
    color_family: str | None,
    has_person: bool,
    has_source: bool,
    has_date: bool,
    alpha: float,
) -> dict:
    md: dict[str, Any] = {"alpha": alpha, "group_by": "scene"}
    if include_ocr:
        md["include_ocr"] = True
    if color_family:
        md["color_family"] = color_family
    if has_person:
        md["person_cluster_ids"] = [f"cluster_{rng.randint(100, 199):03d}"]
        if rng.random() < 0.3:
            md["person_cluster_ids"].append(f"cluster_{rng.randint(100, 199):03d}")
    if has_source:
        md["source_types"] = rng.choice(SOURCE_TYPES_POOL)
    if has_date:
        days_back = rng.randint(7, 60)
        df = (END_DATE - timedelta(days=days_back)).isoformat()
        md["date_from"] = df
        if rng.random() < 0.5:
            md["date_to"] = END_DATE.isoformat()
    return md


def _result_count(rng: random.Random, mode: str, is_zero: bool) -> int:
    if is_zero:
        return 0
    mu = {"metadata": 3, "lexical": 8, "semantic": 15}[mode]
    sigma = {"metadata": 2, "lexical": 4, "semantic": 7}[mode]
    return max(1, int(rng.gauss(mu, sigma)))


def _is_zero_result(rng: random.Random, color: str | None) -> bool:
    if color:
        return rng.random() < COLOR_ZERO_RATE[color]
    return rng.random() < 0.15


# ---------------------------------------------------------------------------
# Row builder
# ---------------------------------------------------------------------------


def build_day_rows(
    target: date,
    day_idx: int,
    total_days: int,
    users: list[dict],
    rng: random.Random,
    next_id: list[int],
) -> list[dict]:
    """Build one day of search_events rows."""
    is_weekend = target.weekday() >= 5
    n = rng.randint(80, 120) if is_weekend else rng.randint(260, 340)

    rows: list[dict] = []
    for _ in range(n):
        org = rng.choices(ORGS, weights=ORG_WEIGHTS, k=1)[0]
        pool = [u for u in users if u["org_id"] == org["id"]]
        user = rng.choice(pool)

        mode = _mode_for(rng, day_idx, total_days)
        has_color = rng.random() < 0.25
        color = _pick_color(rng) if has_color else None
        is_zero = _is_zero_result(rng, color)
        query = _query_text(rng, mode, color, is_zero)

        metadata = _metadata(
            rng,
            include_ocr=rng.random() < 0.30,
            color_family=color,
            has_person=rng.random() < 0.15,
            has_source=rng.random() < 0.20,
            has_date=rng.random() < 0.25,
            alpha=_alpha(rng),
        )

        hour = _pick_hour_weekend(rng) if is_weekend else _pick_hour_weekday(rng)
        minute = rng.randint(0, 59)
        second = rng.randint(0, 59)
        created_at = datetime.combine(
            target, time(hour, minute, second), tzinfo=timezone.utc
        )

        rows.append(
            {
                "id": next_id[0],
                "org_id": org["id"],
                "org_name": org["name"],
                "user_id": user["id"],
                "user_email": user["email"],
                "query_text": query,
                "search_mode": mode,
                "result_count": _result_count(rng, mode, is_zero),
                "response_ms": _response_ms(rng, mode),
                "metadata": metadata,
                "created_at": created_at,
            }
        )
        next_id[0] += 1

    rows.sort(key=lambda r: r["created_at"])
    return rows


# ---------------------------------------------------------------------------
# Parquet writer (exact schema from export_analytics._rows_to_parquet)
# ---------------------------------------------------------------------------


def rows_to_parquet_bytes(rows: list[dict]) -> bytes:
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = pa.schema(
        [
            ("id", pa.int64()),
            ("org_id", pa.string()),
            ("org_name", pa.string()),
            ("user_id", pa.string()),
            ("user_email", pa.string()),
            ("query_text", pa.string()),
            ("search_mode", pa.string()),
            ("result_count", pa.int32()),
            ("response_ms", pa.int32()),
            ("metadata", pa.string()),
            ("created_at", pa.timestamp("us", tz="UTC")),
        ]
    )
    arrays = [
        pa.array([r["id"] for r in rows], type=pa.int64()),
        pa.array([r["org_id"] for r in rows], type=pa.string()),
        pa.array([r["org_name"] for r in rows], type=pa.string()),
        pa.array([r["user_id"] for r in rows], type=pa.string()),
        pa.array([r["user_email"] for r in rows], type=pa.string()),
        pa.array([r["query_text"] for r in rows], type=pa.string()),
        pa.array([r["search_mode"] for r in rows], type=pa.string()),
        pa.array([r["result_count"] for r in rows], type=pa.int32()),
        pa.array([r["response_ms"] for r in rows], type=pa.int32()),
        pa.array(
            [json.dumps(r["metadata"], ensure_ascii=False) for r in rows],
            type=pa.string(),
        ),
        pa.array([r["created_at"] for r in rows], type=pa.timestamp("us", tz="UTC")),
    ]
    table = pa.table(arrays, schema=schema)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="scripts/seed_output", help="Output dir")
    parser.add_argument(
        "--id-offset",
        type=int,
        default=900_000,
        help="Starting search_events.id (avoid collision with real rows)",
    )
    args = parser.parse_args()

    out_root = Path(args.out) / "search_events"
    out_root.mkdir(parents=True, exist_ok=True)

    rng = random.Random(SEED)
    users = _build_user_pool()
    logger.info("user pool: %d users across %d orgs", len(users), len(ORGS))

    next_id = [args.id_offset]
    total_rows = 0
    summary_rows: list[dict] = []

    for day_idx in range(DAYS):
        target = START_DATE + timedelta(days=day_idx)
        rows = build_day_rows(target, day_idx, DAYS, users, rng, next_id)
        total_rows += len(rows)
        summary_rows.extend(rows)

        key_dir = out_root / f"year={target.year}" / f"month={target.month:02d}" / f"day={target.day:02d}"
        key_dir.mkdir(parents=True, exist_ok=True)
        path = key_dir / f"{target.isoformat()}.parquet"
        path.write_bytes(rows_to_parquet_bytes(rows))
        logger.info("wrote %s rows=%d", path, len(rows))

    logger.info("=== DONE === %d files, %d total rows", DAYS, total_rows)

    # Print a quick distribution sanity check so we can eyeball on stdout
    from collections import Counter
    mode_counter = Counter(r["search_mode"] for r in summary_rows)
    color_counter = Counter(
        r["metadata"].get("color_family") for r in summary_rows
        if r["metadata"].get("color_family")
    )
    zero_counter = Counter(r["result_count"] == 0 for r in summary_rows)
    org_counter = Counter(r["org_id"] for r in summary_rows)

    logger.info("mode: %s", dict(mode_counter))
    logger.info("color_top5: %s", color_counter.most_common(5))
    logger.info(
        "zero_rate: %.1f%% (%d / %d)",
        100 * zero_counter[True] / total_rows,
        zero_counter[True],
        total_rows,
    )
    logger.info("org distribution: %s", dict(org_counter))

    return 0


if __name__ == "__main__":
    sys.exit(main())
