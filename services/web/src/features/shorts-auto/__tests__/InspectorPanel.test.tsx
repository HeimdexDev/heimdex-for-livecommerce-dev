import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { InspectorPanel } from "../components/InspectorPanel";
import type { AutoClipResponse } from "@/lib/types";

vi.mock("@/lib/speaker-transcript-display", () => ({
  SpeakerTranscriptDisplay: () => <div data-testid="speaker-display" />,
}));

const baseClip: AutoClipResponse = {
  scene_ids: ["vid_scene_000", "vid_scene_001"],
  members: [
    { scene_id: "vid_scene_000", start_ms: 16_000, end_ms: 31_000, score: 0.8 },
    { scene_id: "vid_scene_001", start_ms: 35_000, end_ms: 43_000, score: 0.7 },
  ],
  start_ms: 16_000,
  end_ms: 43_000,
  duration_ms: 23_000,
  score: 0.75,
  reasons: [],
  is_continuous: false,
};

describe("InspectorPanel — title editing", () => {
  it("disables the input with a tooltip when no render-job exists", () => {
    render(
      <InspectorPanel
        clip={baseClip}
        scenes={[]}
        editorHref="/edit"
        renderJobTitle={null}
        // onTitleSave intentionally omitted — disables the input
      />,
    );
    // 제목 H3 is just a section heading, not a <label>, so we
    // identify the input by its readonly attribute + tooltip copy.
    const inputs = document.querySelectorAll("input[readonly]");
    expect(inputs.length).toBe(1);
    const title = inputs[0] as HTMLInputElement;
    expect(title).toHaveAttribute("aria-readonly", "true");
    expect(title).toHaveAttribute(
      "title",
      "쇼츠를 먼저 렌더링하면 제목을 변경할 수 있어요",
    );
    // Section heading is rendered as plain text alongside the input.
    expect(screen.getByText("제목")).toBeInTheDocument();
  });

  it("renders an editable input pre-populated with the server title when a render-job exists", () => {
    render(
      <InspectorPanel
        clip={baseClip}
        scenes={[]}
        editorHref="/edit"
        renderJobTitle="기존 제목"
        onTitleSave={async () => {}}
      />,
    );
    const input = screen.getByLabelText("쇼츠 제목") as HTMLInputElement;
    expect(input).toBeInTheDocument();
    expect(input.value).toBe("기존 제목");
    expect(input).not.toHaveAttribute("readonly");
  });

  it("shows 'auto-save on blur' helper text when the user types a change", () => {
    render(
      <InspectorPanel
        clip={baseClip}
        scenes={[]}
        editorHref="/edit"
        renderJobTitle="A"
        onTitleSave={async () => {}}
      />,
    );
    const input = screen.getByLabelText("쇼츠 제목") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Different" } });
    expect(
      screen.getByText("포커스 해제 시 자동 저장됩니다"),
    ).toBeInTheDocument();
  });

  it("calls onTitleSave with the trimmed value on blur", async () => {
    const onTitleSave = vi.fn().mockResolvedValue(undefined);
    render(
      <InspectorPanel
        clip={baseClip}
        scenes={[]}
        editorHref="/edit"
        renderJobTitle=""
        onTitleSave={onTitleSave}
      />,
    );
    const input = screen.getByLabelText("쇼츠 제목") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "  새 제목  " } });
    fireEvent.blur(input);
    await waitFor(() => expect(onTitleSave).toHaveBeenCalledTimes(1));
    expect(onTitleSave).toHaveBeenCalledWith("새 제목");
  });

  it("passes null on blur when the user clears the title to whitespace-only", async () => {
    const onTitleSave = vi.fn().mockResolvedValue(undefined);
    render(
      <InspectorPanel
        clip={baseClip}
        scenes={[]}
        editorHref="/edit"
        renderJobTitle="이전 제목"
        onTitleSave={onTitleSave}
      />,
    );
    const input = screen.getByLabelText("쇼츠 제목") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.blur(input);
    await waitFor(() => expect(onTitleSave).toHaveBeenCalledTimes(1));
    expect(onTitleSave).toHaveBeenCalledWith(null);
  });

  it("does NOT fire onTitleSave on blur when value is unchanged", () => {
    const onTitleSave = vi.fn().mockResolvedValue(undefined);
    render(
      <InspectorPanel
        clip={baseClip}
        scenes={[]}
        editorHref="/edit"
        renderJobTitle="고정"
        onTitleSave={onTitleSave}
      />,
    );
    const input = screen.getByLabelText("쇼츠 제목") as HTMLInputElement;
    fireEvent.blur(input);
    expect(onTitleSave).not.toHaveBeenCalled();
  });

  it("blurs (and saves) when the user presses Enter", async () => {
    const onTitleSave = vi.fn().mockResolvedValue(undefined);
    render(
      <InspectorPanel
        clip={baseClip}
        scenes={[]}
        editorHref="/edit"
        renderJobTitle=""
        onTitleSave={onTitleSave}
      />,
    );
    const input = screen.getByLabelText("쇼츠 제목") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Enter to save" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(onTitleSave).toHaveBeenCalledWith("Enter to save"));
  });

  it("resets the controlled value when the underlying renderJobTitle prop changes", () => {
    const { rerender } = render(
      <InspectorPanel
        clip={baseClip}
        scenes={[]}
        editorHref="/edit"
        renderJobTitle="첫번째"
        onTitleSave={async () => {}}
      />,
    );
    let input = screen.getByLabelText("쇼츠 제목") as HTMLInputElement;
    expect(input.value).toBe("첫번째");

    rerender(
      <InspectorPanel
        clip={baseClip}
        scenes={[]}
        editorHref="/edit"
        renderJobTitle="두번째"
        onTitleSave={async () => {}}
      />,
    );
    input = screen.getByLabelText("쇼츠 제목") as HTMLInputElement;
    expect(input.value).toBe("두번째");
  });
});
