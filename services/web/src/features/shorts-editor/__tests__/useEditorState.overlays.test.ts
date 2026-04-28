/**
 * Tests for the V2 overlay branches of the editor reducer.
 * Covers addTextOverlayAtPlayhead, addBackgroundOverlayAtPlayhead,
 * updateOverlay, removeOverlay, selectOverlay, reorderOverlay.
 */

import { renderHook, act } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useEditorState } from "../hooks/useEditorState";

function setupWithDuration(totalMs: number) {
  return renderHook(() => useEditorState());
}

describe("useEditorState — V2 overlays", () => {
  it("addTextOverlayAtPlayhead inserts a text overlay and selects it", () => {
    const { result } = setupWithDuration(10_000);
    act(() => {
      result.current.addTextOverlayAtPlayhead();
    });

    expect(result.current.state.overlays).toHaveLength(1);
    expect(result.current.state.overlays[0].kind).toBe("text");
    expect(result.current.state.selectedOverlayId).toBe(
      result.current.state.overlays[0].id,
    );
    expect(result.current.state.isDirty).toBe(true);
  });

  it("addBackgroundOverlayAtPlayhead inserts a background overlay with W/H", () => {
    const { result } = setupWithDuration(10_000);
    act(() => {
      result.current.addBackgroundOverlayAtPlayhead();
    });

    const ov = result.current.state.overlays[0];
    expect(ov.kind).toBe("background");
    expect(ov.transform.widthPx).toBeGreaterThan(0);
    expect(ov.transform.heightPx).toBeGreaterThan(0);
  });

  it("updateOverlay merges fields and preserves identity", () => {
    const { result } = setupWithDuration(10_000);
    act(() => {
      result.current.addTextOverlayAtPlayhead();
    });
    const id = result.current.state.overlays[0].id;

    act(() => {
      result.current.updateOverlay(id, { italic: true, underline: true });
    });

    const overlay = result.current.state.overlays[0];
    expect(overlay.id).toBe(id);
    expect(overlay.kind).toBe("text");
    if (overlay.kind === "text") {
      expect(overlay.italic).toBe(true);
      expect(overlay.underline).toBe(true);
    }
  });

  it("removeOverlay clears selection if it was selected", () => {
    const { result } = setupWithDuration(10_000);
    act(() => {
      result.current.addTextOverlayAtPlayhead();
    });
    const id = result.current.state.overlays[0].id;

    act(() => {
      result.current.removeOverlay(id);
    });

    expect(result.current.state.overlays).toHaveLength(0);
    expect(result.current.state.selectedOverlayId).toBeNull();
  });

  it("selectOverlay clears clip + subtitle selection", () => {
    const { result } = setupWithDuration(10_000);
    act(() => {
      result.current.addTextOverlayAtPlayhead();
    });
    const id = result.current.state.overlays[0].id;

    act(() => {
      result.current.selectOverlay(id);
    });

    expect(result.current.state.selectedOverlayId).toBe(id);
    expect(result.current.state.selectedClipIndex).toBeNull();
    expect(result.current.state.selectedSubtitleIndex).toBeNull();
  });

  it("reorderOverlay 'front' moves the overlay to the highest layer index", () => {
    const { result } = setupWithDuration(10_000);
    act(() => {
      result.current.addTextOverlayAtPlayhead();
    });
    act(() => {
      result.current.addBackgroundOverlayAtPlayhead();
    });
    act(() => {
      result.current.addTextOverlayAtPlayhead();
    });

    const firstId = result.current.state.overlays[0].id;
    expect(result.current.state.overlays[0].layerIndex).toBe(0);

    act(() => {
      result.current.reorderOverlay(firstId, "front");
    });

    const moved = result.current.state.overlays.find((o) => o.id === firstId)!;
    // After densely repacking: front means highest index (length - 1)
    expect(moved.layerIndex).toBe(result.current.state.overlays.length - 1);
  });

  it("reorderOverlay 'forward' is a single-step swap", () => {
    const { result } = setupWithDuration(10_000);
    act(() => {
      result.current.addTextOverlayAtPlayhead();
    });
    act(() => {
      result.current.addBackgroundOverlayAtPlayhead();
    });
    const firstId = result.current.state.overlays[0].id;

    act(() => {
      result.current.reorderOverlay(firstId, "forward");
    });
    expect(
      result.current.state.overlays.find((o) => o.id === firstId)!.layerIndex,
    ).toBe(1);
  });
});
