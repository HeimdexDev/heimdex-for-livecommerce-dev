"""
Read-only verification of font_family usage across stored shorts compositions.

Why
---
Before tightening ``SubtitleStyleSpec.font_family`` from ``str`` to
``Literal["Pretendard", "Noto Sans KR"]`` we need to know whether any
historically rendered short uses a value outside the supported set.
The Pydantic Literal validator would reject those payloads on read /
re-render, so an unknown value here is a migration concern.

Scope
-----
- Reads ``shorts_render_jobs.input_spec`` JSONB.
- Walks every ``subtitles[*].style.font_family`` and aggregates by
  (font, org_id).
- ``saved_shorts`` does NOT store composition data (only scene_ids), so
  it cannot drift; skipped intentionally.

Output
------
Prints a single block to stdout. Three sections:

  1. Distribution by font_family value across all jobs.
  2. Sample job ids for each value (capped at 5 per font) — only
     printed when a non-supported value is present.
  3. Per-org breakdown — only printed when a non-supported value is
     present, so single-org / single-tenant deployments stay quiet.

Exits 0 if all values are in {None, "Pretendard", "Noto Sans KR"};
exits 1 if any unsupported value is found, so this script can also be
used as a CI / pre-deploy gate.

Usage
-----
On staging::

    ssh -i ~/.ssh/heimdex-staging.pem ec2-user@3.34.75.63 \
      'cd /opt/heimdex/dev-heimdex-for-livecommerce && \
       docker compose exec -T api python -m scripts.verify_composition_fonts'

On production (uses RDS via the api container's database_url)::

    # EC2 Instance Connect — see CLAUDE.md infrastructure section
    docker compose exec -T api python -m scripts.verify_composition_fonts

Optional flag::

    --org-slug devorg     # restrict to one tenant
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter, defaultdict
from typing import Any, Iterable

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_async_session_factory

SUPPORTED_FONTS: frozenset[str | None] = frozenset({None, "Pretendard", "Noto Sans KR"})


def _walk_fonts(input_spec: dict[str, Any]) -> Iterable[str | None]:
    """Yield every font_family value (including missing → None) found in subtitles."""
    subtitles = input_spec.get("subtitles") or []
    for sub in subtitles:
        style = (sub or {}).get("style") or {}
        # font_family may be absent (default applies) or set explicitly.
        yield style.get("font_family")


async def _fetch_rows(
    session: AsyncSession, org_slug: str | None
) -> list[tuple[str, str, dict[str, Any]]]:
    """Return ``(job_id, org_id, input_spec)`` triples."""
    sql = """
        SELECT
          j.id::text AS job_id,
          j.org_id::text AS org_id,
          j.input_spec
        FROM shorts_render_jobs j
        {join}
        {where}
    """.format(
        join="JOIN orgs o ON o.id = j.org_id" if org_slug else "",
        where="WHERE o.slug = :slug" if org_slug else "",
    )
    params: dict[str, Any] = {"slug": org_slug} if org_slug else {}
    result = await session.execute(text(sql), params)
    return [(row[0], row[1], row[2]) for row in result.all()]


async def main(org_slug: str | None) -> int:
    factory = get_async_session_factory()
    async with factory() as session:
        rows = await _fetch_rows(session, org_slug)

    if not rows:
        print("No shorts_render_jobs rows found.")
        return 0

    font_counter: Counter[str | None] = Counter()
    samples_by_font: dict[str | None, list[str]] = defaultdict(list)
    org_counts_by_font: dict[str | None, Counter[str]] = defaultdict(Counter)

    for job_id, org_id, spec in rows:
        for font in _walk_fonts(spec or {}):
            font_counter[font] += 1
            if len(samples_by_font[font]) < 5:
                samples_by_font[font].append(f"{job_id} (org={org_id})")
            org_counts_by_font[font][org_id] += 1

    unsupported = {f for f in font_counter if f not in SUPPORTED_FONTS}

    print(f"Inspected {len(rows)} render jobs"
          + (f" (org_slug={org_slug})" if org_slug else " (all orgs)"))
    print()
    print("font_family distribution (subtitle entries, not jobs):")
    for font, count in font_counter.most_common():
        marker = " " if font in SUPPORTED_FONTS else "*"
        label = repr(font) if font is not None else "<default / missing>"
        print(f"  {marker} {label:<28} {count}")

    if not unsupported:
        print()
        print("OK — every font_family is in SUPPORTED_FONTS.")
        print("Tightening to Literal['Pretendard', 'Noto Sans KR'] is safe.")
        return 0

    print()
    print(f"FAIL — {len(unsupported)} unsupported font_family value(s) found:")
    for font in sorted(unsupported, key=lambda x: (x is None, str(x))):
        print(f"  font: {font!r}  ({font_counter[font]} subtitle entries)")
        print("    sample jobs:")
        for s in samples_by_font[font]:
            print(f"      - {s}")
        print("    by org:")
        for org_id, n in org_counts_by_font[font].most_common():
            print(f"      - {org_id}: {n}")
    print()
    print("Tightening to Literal would reject these on re-render. Either:")
    print("  - leave font_family as open str (and rely on the resolver to map)")
    print("  - migrate the offending rows (UPDATE input_spec SET ... WHERE ...)")
    print("  - extend SUPPORTED_FONTS to include the discovered value(s)")
    return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org-slug", default=None, help="Restrict to one tenant.")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.org_slug)))
