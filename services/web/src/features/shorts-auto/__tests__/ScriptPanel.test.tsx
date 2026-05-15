import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { ScriptPanel } from "../components/ScriptPanel";
import type { AutoClipResponse, VideoScene } from "@/lib/types";

function makeMember(scene_id: string, overrides: Partial<{ transcript: string | null; scene_caption: string | null; start_ms: number; end_ms: number }> = {}) {
  return {
    scene_id,
    start_ms: overrides.start_ms ?? 0,
    end_ms: overrides.end_ms ?? 30_000,
    score: 0.8,
    transcript: overrides.transcript ?? null,
    scene_caption: overrides.scene_caption ?? null,
  };
}

function makeClip(members: ReturnType<typeof makeMember>[]): AutoClipResponse {
  return {
    scene_ids: members.map((m) => m.scene_id),
    members,
    start_ms: members[0]?.start_ms ?? 0,
    end_ms: members[members.length - 1]?.end_ms ?? 0,
    duration_ms: members.reduce((s, m) => s + (m.end_ms - m.start_ms), 0),
    score: 0.8,
    reasons: [],
    is_continuous: false,
  };
}

function makeScene(scene_id: string, fields: Partial<VideoScene> = {}): VideoScene {
  return {
    scene_id,
    video_id: "vid",
    start_ms: 0,
    end_ms: 30_000,
    speaker_transcript: null,
    transcript_raw: null,
    scene_caption: null,
    ...fields,
  } as VideoScene;
}

describe("ScriptPanel", () => {
  it("renders empty-state copy when no clip is selected", () => {
    render(<ScriptPanel clip={null} />);
    expect(screen.getByText("선택된 클립이 없습니다.")).toBeInTheDocument();
  });

  it("uses member.transcript directly when present (PR 1 enrichment)", () => {
    const clip = makeClip([
      makeMember("vid_scene_000", { transcript: "SPEAKER_00: 안녕하세요" }),
    ]);
    render(<ScriptPanel clip={clip} />);
    expect(screen.getByText("안녕하세요")).toBeInTheDocument();
  });

  it("falls back to scenes[].speaker_transcript when member.transcript missing", () => {
    const clip = makeClip([makeMember("vid_scene_000", { transcript: null })]);
    const scenes = [
      makeScene("vid_scene_000", { speaker_transcript: "SPEAKER_00: 폴백 텍스트" }),
    ];
    render(<ScriptPanel clip={clip} scenes={scenes} />);
    expect(screen.getByText("폴백 텍스트")).toBeInTheDocument();
  });

  it("falls back to scene_caption when no transcript at all", () => {
    const clip = makeClip([
      makeMember("vid_scene_000", { transcript: null, scene_caption: "호스트가 제품을 들고 있다" }),
    ]);
    render(<ScriptPanel clip={clip} />);
    expect(screen.getByText("호스트가 제품을 들고 있다")).toBeInTheDocument();
  });

  it("shows the no-subtitle hint when nothing is available", () => {
    const clip = makeClip([
      makeMember("vid_scene_000", { transcript: null, scene_caption: null }),
    ]);
    render(<ScriptPanel clip={clip} />);
    expect(screen.getByText("자막이 감지되지 않았습니다.")).toBeInTheDocument();
  });

  it("ignores whitespace-only member.transcript and falls through to caption", () => {
    const clip = makeClip([
      makeMember("vid_scene_000", { transcript: "   \n  ", scene_caption: "캡션" }),
    ]);
    render(<ScriptPanel clip={clip} />);
    expect(screen.getByText("캡션")).toBeInTheDocument();
  });

  it("renders one section per member in clip order", () => {
    const clip = makeClip([
      makeMember("vid_scene_000", { transcript: "SPEAKER_00: A" }),
      makeMember("vid_scene_001", { transcript: "SPEAKER_00: B" }),
      makeMember("vid_scene_002", { transcript: "SPEAKER_00: C" }),
    ]);
    render(<ScriptPanel clip={clip} />);
    expect(screen.getByText("장면 1")).toBeInTheDocument();
    expect(screen.getByText("장면 2")).toBeInTheDocument();
    expect(screen.getByText("장면 3")).toBeInTheDocument();
  });
});
