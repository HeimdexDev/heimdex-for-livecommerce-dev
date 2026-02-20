import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { SearchResults } from "@/features/search/components/SearchResults";
import type {
  SearchResponse,
  SceneSearchResponse,
  SegmentResult,
  SceneResult,
  DebugInfo,
} from "@/lib/api";

const baseDebug: DebugInfo = {
  lexical_rank: 1,
  lexical_score: 1,
  vector_rank: 1,
  vector_score: 1,
  lexical_contribution: 0.5,
  vector_contribution: 0.5,
  ocr_contribution: 0,
  fused_score: 1,
  quality_factor: 1,
  adjusted_score: 1,
  diversification_penalty: false,
};

const segmentResult: SegmentResult = {
  segment_id: "seg-1",
  video_id: "video-1",
  video_title: "Quarterly Results Presentation",
  library_id: "lib-1",
  library_name: "Main Library",
  start_ms: 1000,
  end_ms: 4000,
  snippet: "Segment snippet text",
  thumbnail_url: null,
  source_type: "gdrive",
  required_drive_nickname: null,
  capture_time: null,
  people_cluster_ids: [],
  keyframe_timestamp_ms: 0,
  debug: baseDebug,
};

const segmentResponse: SearchResponse = {
  results: [segmentResult],
  total_candidates: 1,
  facets: { libraries: [], source_types: [], people_cluster_ids: [] },
  query: "test",
  alpha: 0.5,
};

const sceneResult: SceneResult = {
  scene_id: "vid1_scene_0",
  video_id: "video-1",
  video_title: "Live Commerce Highlight",
  library_id: "lib-1",
  library_name: "Scene Library",
  start_ms: 0,
  end_ms: 5000,
  snippet: "Scene transcript text",
  thumbnail_url: null,
  source_type: "gdrive",
  required_drive_nickname: null,
  capture_time: null,
  people_cluster_ids: [],
  speech_segment_count: 3,
  keyframe_timestamp_ms: 0,
  debug: baseDebug,
};

const sceneResponse: SceneSearchResponse = {
  results: [sceneResult],
  total_candidates: 1,
  facets: { libraries: [], source_types: [], people_cluster_ids: [] },
  query: "test",
  alpha: 0.5,
  result_type: "scene",
};

const emptyResponse: SearchResponse = {
  results: [],
  total_candidates: 0,
  facets: { libraries: [], source_types: [], people_cluster_ids: [] },
  query: "test",
  alpha: 0.5,
};

describe("SearchResults with segment response", () => {
  it("renders segment snippet and video title", () => {
    render(
      <SearchResults response={segmentResponse} showDebug={false} agentAvailable={false} />
    );

    expect(screen.getByText("Segment snippet text")).toBeInTheDocument();
    expect(screen.getByText("Quarterly Results Presentation")).toBeInTheDocument();
  });

  it("renders disabled playback button for segments", () => {
    render(
      <SearchResults response={segmentResponse} showDebug={false} agentAvailable={false} />
    );

    const playButton = screen.getByRole("button", { name: /play \(not available\)/i });
    expect(playButton).toBeDisabled();
  });

  it("renders empty state message when no results", () => {
    render(
      <SearchResults response={emptyResponse} showDebug={false} agentAvailable={false} />
    );

    expect(
      screen.getByText("No results found. Try a different search query.")
    ).toBeInTheDocument();
  });
});

describe("SearchResults with scene response", () => {
  it("renders scene snippet and video title", () => {
    render(
      <SearchResults response={sceneResponse} showDebug={false} agentAvailable={false} />
    );

    expect(screen.getByText("Scene transcript text")).toBeInTheDocument();
    const titles = screen.getAllByText("Live Commerce Highlight");
    expect(titles.length).toBeGreaterThanOrEqual(1);
  });

  it("renders speech segment count badge", () => {
    render(
      <SearchResults response={sceneResponse} showDebug={false} agentAvailable={false} />
    );

    expect(screen.getByText("3 segments")).toBeInTheDocument();
  });

  it("renders scene results badge", () => {
    render(
      <SearchResults response={sceneResponse} showDebug={false} agentAvailable={false} />
    );

    expect(screen.getByText("Scene results")).toBeInTheDocument();
  });

  it("renders enabled play button when agent is available", () => {
    render(
      <SearchResults response={sceneResponse} showDebug={false} agentAvailable={true} />
    );

    const playButton = screen.getByRole("button", { name: /^play$/i });
    expect(playButton).not.toBeDisabled();
  });

  it("renders disabled play button when agent is offline", () => {
    render(
      <SearchResults response={sceneResponse} showDebug={false} agentAvailable={false} />
    );

    const playButtons = screen.getAllByRole("button", { name: /play/i });
    const mainPlayButton = playButtons.find((btn) => btn.textContent?.trim() === "Play");
    expect(mainPlayButton).toBeDisabled();
  });
});

describe("SceneCard match signal indicator", () => {
  it("renders 'Hybrid match' for equal lexical/vector contributions", () => {
    render(
      <SearchResults response={sceneResponse} showDebug={false} agentAvailable={false} />
    );
    expect(screen.getByText("Hybrid match")).toBeInTheDocument();
  });

   it("renders 'Keyword match' when lexical contribution dominates", () => {
     const keywordScene: SceneResult = {
       ...sceneResult,
       keyframe_timestamp_ms: 0,
       debug: { ...baseDebug, lexical_contribution: 0.9, vector_contribution: 0.1 },
     };
    const resp: SceneSearchResponse = {
      ...sceneResponse,
      results: [keywordScene],
    };
    render(<SearchResults response={resp} showDebug={false} agentAvailable={false} />);
    expect(screen.getByText("Keyword match")).toBeInTheDocument();
  });

   it("renders 'Semantic match' when vector contribution dominates", () => {
     const vectorScene: SceneResult = {
       ...sceneResult,
       keyframe_timestamp_ms: 0,
       debug: { ...baseDebug, lexical_contribution: 0.1, vector_contribution: 0.9 },
     };
    const resp: SceneSearchResponse = {
      ...sceneResponse,
      results: [vectorScene],
    };
    render(<SearchResults response={resp} showDebug={false} agentAvailable={false} />);
    expect(screen.getByText("Semantic match")).toBeInTheDocument();
  });
});

describe("SceneCard quality indicator", () => {
  it("renders quality factor value", () => {
    render(
      <SearchResults response={sceneResponse} showDebug={false} agentAvailable={false} />
    );
    expect(screen.getByText("1.00")).toBeInTheDocument();
    expect(screen.getByText("Quality:")).toBeInTheDocument();
  });

  it("renders quality bar with tooltip containing speech segment count", () => {
    render(
      <SearchResults response={sceneResponse} showDebug={false} agentAvailable={false} />
    );
    const qualityValue = screen.getByTitle(/Quality factor: 1\.00, 3 speech segments/);
    expect(qualityValue).toBeInTheDocument();
  });
});

describe("SceneCard context play buttons", () => {
  it("renders -5s context button", () => {
    render(
      <SearchResults response={sceneResponse} showDebug={false} agentAvailable={true} />
    );
    const contextBtn = screen.getByRole("button", { name: "-5s" });
    expect(contextBtn).not.toBeDisabled();
  });

  it("disables context buttons when agent offline", () => {
    render(
      <SearchResults response={sceneResponse} showDebug={false} agentAvailable={false} />
    );
    const contextBtn = screen.getByRole("button", { name: "-5s" });
    expect(contextBtn).toBeDisabled();
  });
});

describe("Video grouping", () => {
   const multiVideoResponse: SceneSearchResponse = {
     results: [
       { ...sceneResult, scene_id: "s1", video_id: "v1", video_title: "Video Alpha", library_name: "Library A", start_ms: 1000, keyframe_timestamp_ms: 0 },
       { ...sceneResult, scene_id: "s2", video_id: "v1", video_title: "Video Alpha", library_name: "Library A", start_ms: 5000, keyframe_timestamp_ms: 0 },
       { ...sceneResult, scene_id: "s3", video_id: "v2", video_title: "Video Beta", library_name: "Library B", start_ms: 0, keyframe_timestamp_ms: 0 },
     ],
    total_candidates: 3,
    facets: { libraries: [], source_types: [], people_cluster_ids: [] },
    query: "test",
    alpha: 0.5,
    result_type: "scene",
  };

  it("groups scenes by video and shows group headers with video titles", () => {
    render(
      <SearchResults response={multiVideoResponse} showDebug={false} agentAvailable={false} />
    );
    const videoAlphas = screen.getAllByText("Video Alpha");
    expect(videoAlphas.length).toBeGreaterThanOrEqual(1);
    const videoBetas = screen.getAllByText("Video Beta");
    expect(videoBetas.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("2 scenes")).toBeInTheDocument();
    expect(screen.getByText("1 scene")).toBeInTheDocument();
  });

  it("expands first group by default and collapses others", () => {
    render(
      <SearchResults response={multiVideoResponse} showDebug={false} agentAvailable={false} />
    );
    const snippets = screen.getAllByText("Scene transcript text");
    expect(snippets).toHaveLength(2);
  });

  it("toggles group expansion on header click", async () => {
    const user = userEvent.setup();
    render(
      <SearchResults response={multiVideoResponse} showDebug={false} agentAvailable={false} />
    );

    const videoBetaHeader = screen.getByText("Video Beta").closest("button")!;
    await user.click(videoBetaHeader);

    const snippets = screen.getAllByText("Scene transcript text");
    expect(snippets).toHaveLength(3);
  });
});

describe("SceneCard OCR features", () => {
  it("renders 'On-screen match' when OCR contribution is dominant", () => {
    const ocrScene: SceneResult = {
      ...sceneResult,
      debug: {
        ...baseDebug,
        lexical_contribution: 0.2,
        vector_contribution: 0.1,
        ocr_contribution: 0.25,
      },
    };
    const resp: SceneSearchResponse = {
      ...sceneResponse,
      results: [ocrScene],
    };
    render(<SearchResults response={resp} showDebug={false} agentAvailable={false} />);
    expect(screen.getByText("On-screen match")).toBeInTheDocument();
  });

  it("does not render 'On-screen match' when OCR contribution is low", () => {
    const lowOcrScene: SceneResult = {
      ...sceneResult,
      debug: {
        ...baseDebug,
        lexical_contribution: 0.5,
        vector_contribution: 0.4,
        ocr_contribution: 0.1,
      },
    };
    const resp: SceneSearchResponse = {
      ...sceneResponse,
      results: [lowOcrScene],
    };
    render(<SearchResults response={resp} showDebug={false} agentAvailable={false} />);
    expect(screen.queryByText("On-screen match")).not.toBeInTheDocument();
  });

  it("renders OCR snippet with prefix when ocr_snippet is present", () => {
    const ocrScene: SceneResult = {
      ...sceneResult,
      ocr_snippet: "\u20A939,900 PRODUCT X",
    };
    const resp: SceneSearchResponse = {
      ...sceneResponse,
      results: [ocrScene],
    };
    render(<SearchResults response={resp} showDebug={false} agentAvailable={false} />);
    expect(screen.getByText(/\u20A939,900 PRODUCT X/)).toBeInTheDocument();
  });

  it("does not render OCR snippet when ocr_snippet is empty", () => {
    const noOcrScene: SceneResult = {
      ...sceneResult,
      ocr_snippet: "",
    };
    const resp: SceneSearchResponse = {
      ...sceneResponse,
      results: [noOcrScene],
    };
    render(<SearchResults response={resp} showDebug={false} agentAvailable={false} />);
    expect(screen.queryByText(/\uD83D\uDCFA/)).not.toBeInTheDocument();
  });

  it("does not render OCR snippet when ocr_snippet is undefined", () => {
    render(<SearchResults response={sceneResponse} showDebug={false} agentAvailable={false} />);
    expect(screen.queryByText(/\uD83D\uDCFA/)).not.toBeInTheDocument();
  });

  it("renders OCR contribution in debug panel when > 0", async () => {
    const user = userEvent.setup();
    const ocrScene: SceneResult = {
      ...sceneResult,
      debug: {
        ...baseDebug,
        ocr_contribution: 0.27,
      },
    };
    const resp: SceneSearchResponse = {
      ...sceneResponse,
      results: [ocrScene],
    };
    render(<SearchResults response={resp} showDebug={true} agentAvailable={false} />);

    const debugToggle = screen.getByText("Debug Info");
    await user.click(debugToggle);

    expect(screen.getByText("OCR Contribution:")).toBeInTheDocument();
    expect(screen.getByText("0.2700")).toBeInTheDocument();
  });

   it("does not render OCR contribution in debug panel when 0", async () => {
     const user = userEvent.setup();
     render(<SearchResults response={sceneResponse} showDebug={true} agentAvailable={false} />);

     const debugToggle = screen.getByText("Debug Info");
     await user.click(debugToggle);

     expect(screen.queryByText("OCR Contribution:")).not.toBeInTheDocument();
   });
});

describe("SceneCard scene_caption features", () => {
  it("renders scene_caption when present", () => {
    const captionScene: SceneResult = {
      ...sceneResult,
      scene_caption: "테스트 캡션",
    };
    const resp: SceneSearchResponse = {
      ...sceneResponse,
      results: [captionScene],
    };
    render(<SearchResults response={resp} showDebug={false} agentAvailable={false} />);
    expect(screen.getByText("테스트 캡션")).toBeInTheDocument();
  });

  it("does not render scene_caption section when empty", () => {
    const noCaptionScene: SceneResult = {
      ...sceneResult,
      scene_caption: "",
    };
    const resp: SceneSearchResponse = {
      ...sceneResponse,
      results: [noCaptionScene],
    };
    render(<SearchResults response={resp} showDebug={false} agentAvailable={false} />);
    expect(screen.queryByText("AI 캡션")).not.toBeInTheDocument();
  });
});
