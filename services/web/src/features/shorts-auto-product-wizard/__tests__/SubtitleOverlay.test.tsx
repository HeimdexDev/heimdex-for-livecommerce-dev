/**
 * Vitest coverage for SubtitleOverlay.
 *
 * Plan: .claude/plans/auto-shorts-overlay-mode-2026-05-07.md
 *
 * The overlay is the source of truth for the operator's preview in
 * overlay mode (parent MP4 has no burned-in caption). Tests guard:
 *   - the active cue is the one whose [start_ms, end_ms) covers
 *     `currentTimeMs`, exclusive of end_ms (matches the python /
 *     ffmpeg drawtext semantics — drawtext stops drawing at end_ms).
 *   - returns null when no cue is active.
 *   - applies the matching style (white pill, black bold text, sized
 *     proportionally to the rendered video height).
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { SubtitleOverlay } from "@/features/shorts-auto-product-wizard/components/SubtitleOverlay";

const SAMPLE_CUES = [
  { text: "안녕하세요", start_ms: 0, end_ms: 1000 },
  { text: "강원도 영월보다 더", start_ms: 2000, end_ms: 4000 },
  { text: "들려드릴까요", start_ms: 5000, end_ms: 6000 },
];

describe("SubtitleOverlay", () => {
  it("renders nothing before the first cue", () => {
    render(
      <SubtitleOverlay
        cues={SAMPLE_CUES}
        currentTimeMs={-1}
        videoWidth={406}
        videoHeight={720}
      />,
    );
    expect(screen.queryByTestId("subtitle-overlay")).toBeNull();
  });

  it("renders the active cue at currentTimeMs inside [start, end)", () => {
    render(
      <SubtitleOverlay
        cues={SAMPLE_CUES}
        currentTimeMs={500}
        videoWidth={406}
        videoHeight={720}
      />,
    );
    expect(screen.getByTestId("subtitle-overlay")).toBeTruthy();
    expect(screen.getByText("안녕하세요")).toBeTruthy();
  });

  it("treats end_ms as exclusive (no cue at exactly end_ms)", () => {
    // At 1000ms the first cue [0, 1000) is no longer active and the
    // second [2000, 4000) hasn't started — gap, no overlay.
    render(
      <SubtitleOverlay
        cues={SAMPLE_CUES}
        currentTimeMs={1000}
        videoWidth={406}
        videoHeight={720}
      />,
    );
    expect(screen.queryByTestId("subtitle-overlay")).toBeNull();
  });

  it("returns null between cues (gap)", () => {
    render(
      <SubtitleOverlay
        cues={SAMPLE_CUES}
        currentTimeMs={1500}
        videoWidth={406}
        videoHeight={720}
      />,
    );
    expect(screen.queryByTestId("subtitle-overlay")).toBeNull();
  });

  it("applies the WYSIWYG pill style (white bg, black bold text)", () => {
    render(
      <SubtitleOverlay
        cues={SAMPLE_CUES}
        currentTimeMs={500}
        videoWidth={406}
        videoHeight={720}
      />,
    );
    const pill = screen.getByTestId("subtitle-overlay-pill") as HTMLElement;
    // Background color renders as `rgba(255, 255, 255, 0.95)`. Browser
    // normalizes inline styles; check via getAttribute("style") to
    // avoid jsdom's per-property parsing differences.
    const styleAttr = pill.getAttribute("style") || "";
    expect(styleAttr).toContain("rgba(255, 255, 255, 0.95)");
    expect(styleAttr).toContain("color: rgb(0, 0, 0)");
    // 720px height → font_size_px=32 per the python ratio.
    expect(styleAttr).toContain("font-size: 32px");
    expect(styleAttr).toContain("font-weight: 700");
  });

  it("falls back to default canvas dims when video size is null", () => {
    // First-paint case: ResizeObserver hasn't fired yet, props are
    // null. Should still render with default-derived font size (32px
    // at default canvas height 720).
    render(
      <SubtitleOverlay
        cues={SAMPLE_CUES}
        currentTimeMs={500}
        videoWidth={null}
        videoHeight={null}
      />,
    );
    const pill = screen.getByTestId("subtitle-overlay-pill");
    expect((pill.getAttribute("style") || "")).toContain("font-size: 32px");
  });

  it("scales font size with rendered video height", () => {
    render(
      <SubtitleOverlay
        cues={SAMPLE_CUES}
        currentTimeMs={500}
        videoWidth={609}
        videoHeight={1080}
      />,
    );
    const pill = screen.getByTestId("subtitle-overlay-pill");
    // 1080 * 0.045 = 48.6 → 49.
    expect((pill.getAttribute("style") || "")).toContain("font-size: 49px");
  });

  it("renders newline-separated lines as separate spans (matches drawtext stack)", () => {
    render(
      <SubtitleOverlay
        cues={[{ text: "강원도 영월보다 더\n슬퍼할 거야 네놈", start_ms: 0, end_ms: 1000 }]}
        currentTimeMs={500}
        videoWidth={406}
        videoHeight={720}
      />,
    );
    const pill = screen.getByTestId("subtitle-overlay-pill");
    // Each line is its own block-level span so the pill grows
    // vertically — matches the per-line `box=1` chains in
    // heimdex_media_contracts/composition/filters.py:160.
    const spans = pill.querySelectorAll("span");
    expect(spans.length).toBeGreaterThanOrEqual(2);
  });
});

// ============================================================================
// Per-cue style — Phase 2 of the WYSIWYG plan
// .claude/plans/wysiwyg-subtitle-overlay-2026-05-11.md
//
// The overlay now consumes ``cue.style`` (Partial<SubtitleCueStyle>) and
// translates it through `resolveOverlayStyle`. Tests below lock the
// observable CSS effect of each StyleTab axis.
// ============================================================================

describe("SubtitleOverlay — per-cue style", () => {
  it("honors per-cue font_color override", () => {
    render(
      <SubtitleOverlay
        cues={[
          {
            text: "hi",
            start_ms: 0,
            end_ms: 1000,
            style: { font_color: "#FF0000" },
          },
        ]}
        currentTimeMs={500}
        videoWidth={406}
        videoHeight={720}
      />,
    );
    const pill = screen.getByTestId("subtitle-overlay-pill") as HTMLElement;
    // jsdom normalises hex to rgb in inline style serialisation.
    expect((pill.getAttribute("style") || "")).toContain(
      "color: rgb(255, 0, 0)",
    );
  });

  it("honors per-cue background_color + opacity (rgba)", () => {
    render(
      <SubtitleOverlay
        cues={[
          {
            text: "hi",
            start_ms: 0,
            end_ms: 1000,
            style: { background_color: "#000000", background_opacity: 0.5 },
          },
        ]}
        currentTimeMs={500}
        videoWidth={406}
        videoHeight={720}
      />,
    );
    const pill = screen.getByTestId("subtitle-overlay-pill") as HTMLElement;
    expect((pill.getAttribute("style") || "")).toContain(
      "rgba(0, 0, 0, 0.5)",
    );
  });

  it("drops background + padding when background_color is null", () => {
    render(
      <SubtitleOverlay
        cues={[
          {
            text: "hi",
            start_ms: 0,
            end_ms: 1000,
            style: { background_color: null },
          },
        ]}
        currentTimeMs={500}
        videoWidth={406}
        videoHeight={720}
      />,
    );
    const pill = screen.getByTestId("subtitle-overlay-pill") as HTMLElement;
    const styleAttr = pill.getAttribute("style") || "";
    // No rgba(...) backgrounds when explicitly disabled.
    expect(styleAttr).not.toMatch(/background-color: rgba/);
  });

  it("renders -webkit-text-stroke when stroke_color + stroke_width set", () => {
    render(
      <SubtitleOverlay
        cues={[
          {
            text: "hi",
            start_ms: 0,
            end_ms: 1000,
            style: { stroke_color: "#FF0000", stroke_width: 2 },
          },
        ]}
        currentTimeMs={500}
        videoWidth={406}
        videoHeight={720}
      />,
    );
    const pill = screen.getByTestId("subtitle-overlay-pill") as HTMLElement;
    const styleAttr = pill.getAttribute("style") || "";
    expect(styleAttr).toMatch(/-webkit-text-stroke:\s*2px/);
  });

  it("omits -webkit-text-stroke when stroke_width is zero", () => {
    render(
      <SubtitleOverlay
        cues={[
          {
            text: "hi",
            start_ms: 0,
            end_ms: 1000,
            style: { stroke_color: "#FF0000", stroke_width: 0 },
          },
        ]}
        currentTimeMs={500}
        videoWidth={406}
        videoHeight={720}
      />,
    );
    const pill = screen.getByTestId("subtitle-overlay-pill") as HTMLElement;
    expect((pill.getAttribute("style") || "")).not.toMatch(
      /-webkit-text-stroke/,
    );
  });

  it("renders text-shadow when shadow_enabled and shadow_color set", () => {
    render(
      <SubtitleOverlay
        cues={[
          {
            text: "hi",
            start_ms: 0,
            end_ms: 1000,
            style: {
              shadow_enabled: true,
              shadow_color: "#000000",
              shadow_offset_x: 3,
              shadow_offset_y: 4,
            },
          },
        ]}
        currentTimeMs={500}
        videoWidth={406}
        videoHeight={720}
      />,
    );
    const pill = screen.getByTestId("subtitle-overlay-pill") as HTMLElement;
    const styleAttr = pill.getAttribute("style") || "";
    expect(styleAttr).toMatch(/text-shadow:\s*3px 4px/);
  });

  it("omits text-shadow when shadow_enabled is false", () => {
    render(
      <SubtitleOverlay
        cues={[
          {
            text: "hi",
            start_ms: 0,
            end_ms: 1000,
            style: {
              shadow_enabled: false,
              shadow_color: "#000000",
              shadow_offset_y: 4,
            },
          },
        ]}
        currentTimeMs={500}
        videoWidth={406}
        videoHeight={720}
      />,
    );
    const pill = screen.getByTestId("subtitle-overlay-pill") as HTMLElement;
    expect((pill.getAttribute("style") || "")).not.toMatch(/text-shadow/);
  });

  it("scales canvas-pixel font_size_px when canvas dims supplied", () => {
    // canvas=720, rendered=1440 → 2× scale. cue.font_size_px=40 canvas
    // → 80 rendered.
    render(
      <SubtitleOverlay
        cues={[
          {
            text: "hi",
            start_ms: 0,
            end_ms: 1000,
            style: { font_size_px: 40 },
          },
        ]}
        currentTimeMs={500}
        videoWidth={812}
        videoHeight={1440}
        canvasWidth={406}
        canvasHeight={720}
      />,
    );
    const pill = screen.getByTestId("subtitle-overlay-pill") as HTMLElement;
    expect((pill.getAttribute("style") || "")).toContain("font-size: 80px");
  });

  it("anchors at custom position_x with right alignment", () => {
    render(
      <SubtitleOverlay
        cues={[
          {
            text: "hi",
            start_ms: 0,
            end_ms: 1000,
            style: { position_x: 0.95, text_align: "right" },
          },
        ]}
        currentTimeMs={500}
        videoWidth={406}
        videoHeight={720}
      />,
    );
    const pill = screen.getByTestId("subtitle-overlay-pill") as HTMLElement;
    const styleAttr = pill.getAttribute("style") || "";
    expect(styleAttr).toContain("left: 95%");
    // jsdom may normalise "translate(-100%, -50%)" with or without
    // intra-space; loosen the regex.
    expect(styleAttr).toMatch(/translate\(\s*-100%/);
  });

  it("anchors at custom position_x with left alignment", () => {
    render(
      <SubtitleOverlay
        cues={[
          {
            text: "hi",
            start_ms: 0,
            end_ms: 1000,
            style: { position_x: 0.05, text_align: "left" },
          },
        ]}
        currentTimeMs={500}
        videoWidth={406}
        videoHeight={720}
      />,
    );
    const pill = screen.getByTestId("subtitle-overlay-pill") as HTMLElement;
    const styleAttr = pill.getAttribute("style") || "";
    expect(styleAttr).toContain("left: 5%");
    // Left alignment anchor: pill's left edge sits at position_x → 0 X
    // translate. jsdom may serialise as "translate(0" or "translate(0px".
    expect(styleAttr).toMatch(/translate\(\s*0/);
  });

  it("uses Noto Sans KR when cue style sets font_family", () => {
    render(
      <SubtitleOverlay
        cues={[
          {
            text: "hi",
            start_ms: 0,
            end_ms: 1000,
            style: { font_family: "Noto Sans KR" },
          },
        ]}
        currentTimeMs={500}
        videoWidth={406}
        videoHeight={720}
      />,
    );
    const pill = screen.getByTestId("subtitle-overlay-pill") as HTMLElement;
    expect((pill.getAttribute("style") || "")).toContain("Noto Sans KR");
  });
});
