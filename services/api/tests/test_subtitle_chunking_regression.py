"""Drift-prevention test: subtitle_generator must keep importing from app/lib.

Originally (PR 1) this file asserted byte-identical output between two
co-existing copies of ``chunk_subtitle_text`` (the lib version and the
subtitle_generator local version). PR 3 removed the local copy and
made subtitle_generator re-export the lib symbols.

The test now guards against **drift** — if a future contributor
re-defines the chunker locally inside ``subtitle_generator.py`` (e.g.
copy-pasting it back to "tweak just one regex"), this test fails
because the function objects no longer match. That's the bug we want
to surface — divergent chunking heuristics between modules would
silently make auto-shorts subtitles inconsistent with any other
caller of the lib (premiere export, blur, etc.).

A behavioural-output test would also catch some divergences, but only
ones that change the parametrized inputs we picked. Identity-checking
is stronger: any reimplementation, even one that happens to match on
our inputs, fails here.
"""

from __future__ import annotations

from app.lib.subtitle_chunking import (
    MAX_SUBTITLE_CHARS as LIB_MAX,
)
from app.lib.subtitle_chunking import (
    chunk_subtitle_text as lib_chunk,
)
from app.lib.subtitle_chunking import (
    merge_chunks_to_count as lib_merge,
)
from app.modules.shorts_auto_product.track_stt.subtitle_generator import (
    MAX_SUBTITLE_CHARS as GEN_MAX,
)
from app.modules.shorts_auto_product.track_stt.subtitle_generator import (
    chunk_subtitle_text as gen_chunk,
)
from app.modules.shorts_auto_product.track_stt.subtitle_generator import (
    merge_chunks_to_count as gen_merge,
)


def test_chunker_function_is_lib_canonical() -> None:
    """``subtitle_generator.chunk_subtitle_text`` must BE the lib function.

    Identity (``is``) check, not equality. If someone re-defines a
    local function with the same name, this fails — which is the bug.
    """
    assert gen_chunk is lib_chunk, (
        "subtitle_generator.chunk_subtitle_text has been re-defined "
        "locally. Drop the local definition and re-export from "
        "app.lib.subtitle_chunking — divergent chunking would make "
        "auto-shorts subtitles inconsistent with other lib consumers."
    )


def test_merge_function_is_lib_canonical() -> None:
    assert gen_merge is lib_merge, (
        "subtitle_generator.merge_chunks_to_count has been re-defined "
        "locally. Use the lib export."
    )


def test_max_chars_constant_matches() -> None:
    """Loose check (constant equality, not identity, since ints intern)."""
    assert GEN_MAX == LIB_MAX == 25


def test_subtitle_generator_does_not_redefine_chunker_constants() -> None:
    """The private regex constants from PR 0 must NOT be present anymore.

    If they reappear, the chunker has likely been copy-pasted back in
    — this test is the canary.
    """
    from app.modules.shorts_auto_product.track_stt import subtitle_generator

    forbidden = ["_SENTENCE_SPLIT_RE", "_CLAUSE_SPLIT_RE", "_MAX_SUBTITLE_CHARS"]
    leaked = [name for name in forbidden if hasattr(subtitle_generator, name)]
    assert not leaked, (
        f"subtitle_generator has re-acquired private chunker constants: "
        f"{leaked}. The chunker lives in app.lib.subtitle_chunking — "
        f"don't re-declare these here."
    )


def test_subtitle_generator_keeps_module_specific_internals() -> None:
    """Sanity: the auto-shorts-specific code that should NOT have moved."""
    from app.modules.shorts_auto_product.track_stt import subtitle_generator

    expected = [
        "_MIN_CHUNK_DURATION_MS",
        "_SPEAKER_LINE_RE",
        "_TIMESTAMP_RE",
        "parse_timestamp_ms",
        "parse_speaker_transcript",
        "distribute_subtitles_for_clip",
        "distribute_subtitles_with_speaker_timing",
    ]
    missing = [name for name in expected if not hasattr(subtitle_generator, name)]
    assert not missing, (
        f"subtitle_generator lost auto-shorts-specific code: {missing}. "
        f"PR 3 should have kept these in this module."
    )
