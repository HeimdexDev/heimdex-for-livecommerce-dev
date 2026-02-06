# Search Quality Evaluation Plan

## Objective
Establish a baseline for Korean search quality using a "Golden Set" of queries with expected results.

## Golden Query Set (Korean)
Based on `seed.py` transcripts.

| Query | Intent | Expected Keywords in Transcript |
|-------|--------|---------------------------------|
| "회의 일정" | Find meeting schedules | "오늘 회의", "주요 안건", "일정" |
| "매출 목표" | Business goals | "분기 매출", "목표", "달성" |
| "마케팅 전략" | Strategy documents | "마케팅", "전략", "수정" |
| "사용자 인터페이스" | UX/UI discussions | "사용자", "인터페이스", "개선" |
| "보안 패치" | Security updates | "보안", "취약점", "패치" |
| "데이터베이스 최적화" | Engineering | "데이터베이스", "최적화", "쿼리" |
| "클라우드 마이그레이션" | Infrastructure | "클라우드", "인프라", "마이그레이션" |
| "온보딩" | HR/Team | "문서화", "온보딩", "수월" |
| "글로벌 확장" | Business expansion | "다국어", "지원", "글로벌" |
| "API 문서" | Dev experience | "API", "문서", "업데이트" |

## Test Implementation: `services/api/tests/test_search_quality.py`

```python
import pytest
from app.modules.search.client import OpenSearchClient

GOLDEN_QUERIES = [
    ("회의 일정", ["오늘 회의", "신규 프로젝트"]),
    ("매출 목표", ["매출 목표", "마케팅 전략"]),
    ("보안 패치", ["보안 취약점", "시스템이 더 안전"]),
    ("온보딩", ["기술 문서화", "온보딩"]),
]

@pytest.mark.integration
class TestSearchQuality:
    @pytest.mark.asyncio
    async def test_korean_recall_at_20(self):
        """
        Run golden queries at different alpha levels.
        We expect meaningful results to appear in top 20.
        """
        client = OpenSearchClient()
        # Ensure we have data
        await client.ensure_index_exists()
        
        results_summary = []
        
        for query, expected_phrases in GOLDEN_QUERIES:
            # Test Alpha=0.5 (Hybrid)
            hits = await client.search_lexical(
                query=query, 
                org_id="devorg",  # Assumes 'devorg' seeded
                filters={}, 
                size=20
            )
            
            # Check if any expected phrase appears in the hits
            found = False
            for hit in hits:
                transcript = hit["_source"]["transcript_raw"]
                if any(phrase in transcript for phrase in expected_phrases):
                    found = True
                    break
            
            results_summary.append({"query": query, "found": found})
            
        # Assert minimal quality baseline (e.g., > 80% recall for known seeds)
        success_rate = sum(1 for r in results_summary if r["found"]) / len(results_summary)
        print(f"Recall@20: {success_rate*100}%")
        assert success_rate >= 0.8
```

## Tuning Parameters to Test
- `SEARCH_RRF_K`: Currently 60. Try 10, 100.
- `alpha`: 0.0 (Lexical), 0.5 (Hybrid), 1.0 (Semantic).
- `decompound_mode`: "mixed" (current default).
