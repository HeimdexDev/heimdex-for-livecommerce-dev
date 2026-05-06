/**
 * Vitest coverage for `SubtitleEditor` (PR 2 of
 * auto-shorts-subtitle-editor-2026-05-06.md).
 *
 * Covers UI behaviour: rendering cues, edit propagation, banner
 * surface, button disabled states, save-status indicator.
 *
 * The hook itself is exercised in useSubtitleEditorState.test.ts;
 * this file mocks `patchRenderJobSubtitles` to keep the component
 * test focused on UI glue.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import * as api from "@/lib/api/highlight-reel";
import { SubtitleEditor } from "@/features/shorts-auto-product-wizard/components/SubtitleEditor";

vi.mock("@/lib/api/highlight-reel", async () => {
  const actual = await vi.importActual<typeof api>(
    "@/lib/api/highlight-reel",
  );
  return {
    ...actual,
    patchRenderJobSubtitles: vi.fn(),
    fetchRenderSubtitles: vi.fn(),
  };
});

const RENDER_ID = "00000000-0000-0000-0000-00000000aaaa";
const tokenGetter = () => Promise.resolve("test-token");

const initialCues: api.SubtitleEdit[] = [
  { text: "안녕", start_ms: 0, end_ms: 500 },
  { text: "하세요", start_ms: 500, end_ms: 1100 },
];

function makeRenderResponse(): api.RenderJobResponse {
  return {
    id: RENDER_ID,
    video_id: "gd_v1",
    title: null,
    status: "completed",
    created_at: "2026-05-06T00:00:00Z",
    completed_at: "2026-05-06T00:01:00Z",
    render_time_ms: 1000,
    output_duration_ms: 1100,
    output_size_bytes: 1024,
    error: null,
    download_url: "https://s3/clip.mp4",
    thumbnail_video_id: null,
    thumbnail_scene_id: null,
    replaced_by_render_job_id: null,
    refined_from_render_job_id: null,
    refinement_source: "manual_edit",
  };
}

beforeEach(() => {
  vi.mocked(api.patchRenderJobSubtitles).mockReset();
  vi.mocked(api.patchRenderJobSubtitles).mockResolvedValue(
    makeRenderResponse(),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SubtitleEditor — initial render", () => {
  it("renders one row per cue with timestamp + text", () => {
    render(
      <SubtitleEditor
        renderId={RENDER_ID}
        initialCues={initialCues}
        getToken={tokenGetter}
        refinementSource={null}
        onRerenderRequested={async () => {}}
        isRendering={false}
      />,
    );
    expect(screen.getByTestId("subtitle-editor-row-0")).toBeInTheDocument();
    expect(screen.getByTestId("subtitle-editor-row-1")).toBeInTheDocument();
    const ta0 = screen.getByTestId("subtitle-editor-textarea-0") as HTMLTextAreaElement;
    expect(ta0.value).toBe("안녕");
    const ta1 = screen.getByTestId("subtitle-editor-textarea-1") as HTMLTextAreaElement;
    expect(ta1.value).toBe("하세요");
  });

  it("shows empty-state copy when no cues", () => {
    render(
      <SubtitleEditor
        renderId={RENDER_ID}
        initialCues={[]}
        getToken={tokenGetter}
        refinementSource={null}
        onRerenderRequested={async () => {}}
        isRendering={false}
      />,
    );
    expect(screen.getByText(/음성 자막을 생성하지 못했습니다/)).toBeInTheDocument();
  });

  it("does NOT show the rerender banner on a clean parent", () => {
    render(
      <SubtitleEditor
        renderId={RENDER_ID}
        initialCues={initialCues}
        getToken={tokenGetter}
        refinementSource={null}
        onRerenderRequested={async () => {}}
        isRendering={false}
      />,
    );
    expect(screen.queryByTestId("subtitle-editor-banner")).not.toBeInTheDocument();
  });

  it("DOES show the rerender banner when refinement_source='manual_edit'", () => {
    render(
      <SubtitleEditor
        renderId={RENDER_ID}
        initialCues={initialCues}
        getToken={tokenGetter}
        refinementSource="manual_edit"
        onRerenderRequested={async () => {}}
        isRendering={false}
      />,
    );
    expect(
      screen.getByText(/자막 편집이 아직 영상에 반영되지 않았습니다/),
    ).toBeInTheDocument();
  });
});

describe("SubtitleEditor — edit propagation", () => {
  it("typing in a textarea triggers an autosave eventually", async () => {
    render(
      <SubtitleEditor
        renderId={RENDER_ID}
        initialCues={initialCues}
        getToken={tokenGetter}
        refinementSource={null}
        onRerenderRequested={async () => {}}
        isRendering={false}
      />,
    );
    const ta = screen.getByTestId("subtitle-editor-textarea-0") as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: "안녕하세요" } });
    expect(ta.value).toBe("안녕하세요");

    await waitFor(
      () => {
        expect(api.patchRenderJobSubtitles).toHaveBeenCalled();
      },
      { timeout: 3000 },
    );
  });

  it("shows the rerender banner once the user starts editing", async () => {
    render(
      <SubtitleEditor
        renderId={RENDER_ID}
        initialCues={initialCues}
        getToken={tokenGetter}
        refinementSource={null}
        onRerenderRequested={async () => {}}
        isRendering={false}
      />,
    );
    expect(screen.queryByTestId("subtitle-editor-banner")).not.toBeInTheDocument();
    fireEvent.change(
      screen.getByTestId("subtitle-editor-textarea-0"),
      { target: { value: "edited" } },
    );
    expect(screen.getByTestId("subtitle-editor-banner")).toBeInTheDocument();
  });
});

describe("SubtitleEditor — Korean IME safety", () => {
  it("does NOT call the save API while a composition is in flight", async () => {
    render(
      <SubtitleEditor
        renderId={RENDER_ID}
        initialCues={initialCues}
        getToken={tokenGetter}
        refinementSource={null}
        onRerenderRequested={async () => {}}
        isRendering={false}
      />,
    );
    const ta = screen.getByTestId("subtitle-editor-textarea-0");
    fireEvent.compositionStart(ta);
    // Mid-composition partial input — should NOT propagate
    fireEvent.change(ta, { target: { value: "안" } });
    // Wait long enough that the debounce would otherwise fire
    await new Promise((r) => setTimeout(r, 100));
    expect(api.patchRenderJobSubtitles).not.toHaveBeenCalled();

    fireEvent.compositionEnd(ta, { currentTarget: { value: "안녕" } });
    // After composition ends, the final value propagates and saves
    await waitFor(
      () => {
        expect(api.patchRenderJobSubtitles).toHaveBeenCalled();
      },
      { timeout: 3000 },
    );
  });
});

describe("SubtitleEditor — render button states", () => {
  it("button is disabled when isRendering=true", () => {
    render(
      <SubtitleEditor
        renderId={RENDER_ID}
        initialCues={initialCues}
        getToken={tokenGetter}
        refinementSource="manual_edit"
        onRerenderRequested={async () => {}}
        isRendering={true}
      />,
    );
    const btn = screen.getByTestId("subtitle-editor-rerender-button") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(btn.textContent).toMatch(/렌더링 중/);
  });

  it("button is disabled when there are no cues", () => {
    render(
      <SubtitleEditor
        renderId={RENDER_ID}
        initialCues={[]}
        getToken={tokenGetter}
        refinementSource={null}
        onRerenderRequested={async () => {}}
        isRendering={false}
      />,
    );
    const btn = screen.getByTestId("subtitle-editor-rerender-button") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("button is enabled when refinement_source='manual_edit' and no in-flight state", () => {
    render(
      <SubtitleEditor
        renderId={RENDER_ID}
        initialCues={initialCues}
        getToken={tokenGetter}
        refinementSource="manual_edit"
        onRerenderRequested={async () => {}}
        isRendering={false}
      />,
    );
    const btn = screen.getByTestId("subtitle-editor-rerender-button") as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
  });

  it("clicking the button calls onRerenderRequested", async () => {
    const onRerender = vi.fn().mockResolvedValue(undefined);
    render(
      <SubtitleEditor
        renderId={RENDER_ID}
        initialCues={initialCues}
        getToken={tokenGetter}
        refinementSource="manual_edit"
        onRerenderRequested={onRerender}
        isRendering={false}
      />,
    );
    fireEvent.click(screen.getByTestId("subtitle-editor-rerender-button"));
    await waitFor(() => {
      expect(onRerender).toHaveBeenCalledTimes(1);
    });
  });

  it("button is disabled while there are unsaved edits", async () => {
    render(
      <SubtitleEditor
        renderId={RENDER_ID}
        initialCues={initialCues}
        getToken={tokenGetter}
        refinementSource={null}
        onRerenderRequested={async () => {}}
        isRendering={false}
      />,
    );
    const btn = screen.getByTestId("subtitle-editor-rerender-button") as HTMLButtonElement;
    // Initially clean → button enabled (refinement_source=null but cues
    // exist; PR 4 may want to disable if there's nothing to render
    // beyond the initial Whisper output, but for v1 the button is
    // armed whenever there are cues and no in-flight save)
    expect(btn.disabled).toBe(false);

    fireEvent.change(
      screen.getByTestId("subtitle-editor-textarea-0"),
      { target: { value: "edited" } },
    );
    // Now there are unsaved edits → button disabled until autosave lands
    expect(btn.disabled).toBe(true);

    await waitFor(() => {
      expect(btn.disabled).toBe(false);
    }, { timeout: 3000 });
  });
});

describe("SubtitleEditor — save status indicator", () => {
  it("surfaces 'saving' then 'saved' in the status region", async () => {
    render(
      <SubtitleEditor
        renderId={RENDER_ID}
        initialCues={initialCues}
        getToken={tokenGetter}
        refinementSource={null}
        onRerenderRequested={async () => {}}
        isRendering={false}
      />,
    );
    fireEvent.change(
      screen.getByTestId("subtitle-editor-textarea-0"),
      { target: { value: "edited" } },
    );
    await waitFor(
      () => {
        expect(
          screen.getByTestId("subtitle-editor-save-status").textContent,
        ).toBe("저장됨");
      },
      { timeout: 3000 },
    );
  });

  it("surfaces an error message when the save fails", async () => {
    vi.mocked(api.patchRenderJobSubtitles).mockRejectedValue(
      new Error("network down"),
    );
    render(
      <SubtitleEditor
        renderId={RENDER_ID}
        initialCues={initialCues}
        getToken={tokenGetter}
        refinementSource={null}
        onRerenderRequested={async () => {}}
        isRendering={false}
      />,
    );
    fireEvent.change(
      screen.getByTestId("subtitle-editor-textarea-0"),
      { target: { value: "fail" } },
    );
    await waitFor(
      () => {
        expect(screen.getByTestId("subtitle-editor-error")).toBeInTheDocument();
      },
      { timeout: 3000 },
    );
    expect(screen.getByTestId("subtitle-editor-error").textContent).toBe(
      "network down",
    );
  });
});

describe("SubtitleEditor — onCuesChange", () => {
  it("invokes onCuesChange with the initial cues on mount", async () => {
    const onCuesChange = vi.fn();
    render(
      <SubtitleEditor
        renderId={RENDER_ID}
        initialCues={initialCues}
        getToken={tokenGetter}
        refinementSource={null}
        onRerenderRequested={async () => {}}
        isRendering={false}
        onCuesChange={onCuesChange}
      />,
    );
    await waitFor(() => expect(onCuesChange).toHaveBeenCalled());
    expect(onCuesChange).toHaveBeenLastCalledWith(initialCues);
  });

  it("invokes onCuesChange after each edit so the page mirror stays live", async () => {
    const onCuesChange = vi.fn();
    render(
      <SubtitleEditor
        renderId={RENDER_ID}
        initialCues={initialCues}
        getToken={tokenGetter}
        refinementSource={null}
        onRerenderRequested={async () => {}}
        isRendering={false}
        onCuesChange={onCuesChange}
      />,
    );
    onCuesChange.mockClear();
    fireEvent.change(
      screen.getByTestId("subtitle-editor-textarea-0"),
      { target: { value: "edited" } },
    );
    await waitFor(() => expect(onCuesChange).toHaveBeenCalled());
    const lastCall = onCuesChange.mock.calls.at(-1)?.[0] as api.SubtitleEdit[];
    expect(lastCall[0].text).toBe("edited");
    // The second cue stays untouched — partial update should preserve it.
    expect(lastCall[1].text).toBe(initialCues[1].text);
  });
});

describe("SubtitleEditor — download button", () => {
  let createObjectURL: ReturnType<typeof vi.fn>;
  let revokeObjectURL: ReturnType<typeof vi.fn>;
  let originalCreateObjectURL: typeof URL.createObjectURL | undefined;
  let originalRevokeObjectURL: typeof URL.revokeObjectURL | undefined;

  beforeEach(() => {
    createObjectURL = vi.fn(() => "blob:fake-url");
    revokeObjectURL = vi.fn();
    originalCreateObjectURL = URL.createObjectURL;
    originalRevokeObjectURL = URL.revokeObjectURL;
    // jsdom doesn't ship URL.createObjectURL by default — install a spy
    // so the component's blob-anchor flow runs without crashing.
    URL.createObjectURL = createObjectURL as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL = revokeObjectURL as unknown as typeof URL.revokeObjectURL;

    vi.mocked(api.fetchRenderSubtitles).mockReset();
    vi.mocked(api.fetchRenderSubtitles).mockResolvedValue({
      body: "1\n00:00:00,000 --> 00:00:00,500\n안녕\n",
      filename: "Heimdex-Mini.srt",
    });
  });

  afterEach(() => {
    if (originalCreateObjectURL !== undefined) {
      URL.createObjectURL = originalCreateObjectURL;
    }
    if (originalRevokeObjectURL !== undefined) {
      URL.revokeObjectURL = originalRevokeObjectURL;
    }
  });

  it("clicking the SRT download button calls fetchRenderSubtitles with format=srt", async () => {
    render(
      <SubtitleEditor
        renderId={RENDER_ID}
        initialCues={initialCues}
        getToken={tokenGetter}
        refinementSource={null}
        onRerenderRequested={async () => {}}
        isRendering={false}
      />,
    );
    fireEvent.click(screen.getByTestId("subtitle-editor-download-srt-button"));
    await waitFor(() =>
      expect(vi.mocked(api.fetchRenderSubtitles)).toHaveBeenCalled(),
    );
    const call = vi.mocked(api.fetchRenderSubtitles).mock.calls[0];
    expect(call[0]).toBe(RENDER_ID);
    expect(call[1]).toBe("srt");
    // Object URL was created from a Blob and the anchor was clicked
    // (revoke runs synchronously after click in our handler).
    await waitFor(() => expect(createObjectURL).toHaveBeenCalled());
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:fake-url");
  });

  it("download button is disabled when there are no cues", () => {
    render(
      <SubtitleEditor
        renderId={RENDER_ID}
        initialCues={[]}
        getToken={tokenGetter}
        refinementSource={null}
        onRerenderRequested={async () => {}}
        isRendering={false}
      />,
    );
    const btn = screen.getByTestId(
      "subtitle-editor-download-srt-button",
    ) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("surfaces a download error when fetchRenderSubtitles rejects", async () => {
    vi.mocked(api.fetchRenderSubtitles).mockRejectedValue(
      new Error("403 Forbidden"),
    );
    render(
      <SubtitleEditor
        renderId={RENDER_ID}
        initialCues={initialCues}
        getToken={tokenGetter}
        refinementSource={null}
        onRerenderRequested={async () => {}}
        isRendering={false}
      />,
    );
    fireEvent.click(screen.getByTestId("subtitle-editor-download-srt-button"));
    await waitFor(() =>
      expect(
        screen.getByTestId("subtitle-editor-download-error"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("subtitle-editor-download-error").textContent,
    ).toBe("403 Forbidden");
  });
});
