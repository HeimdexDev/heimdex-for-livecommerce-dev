import { describe, it, expect } from "vitest";
import type {
  SceneResult,
  SegmentResult,
  SearchResponse,
  SceneSearchResponse,
  AnySearchResponse,
} from "@/lib/types";

describe("Scene search types", () => {
  it("SceneResult has required scene-specific fields", () => {
    const scene: SceneResult = {
      scene_id: "vid123_scene_0",
      video_id: "vid123",
      video_title: "Test Video",
      library_id: "lib1",
      library_name: "Test Library",
      start_ms: 0,
      end_ms: 5000,
      snippet: "test transcript",
      thumbnail_url: null,
      source_type: "gdrive",
      required_drive_nickname: null,
      capture_time: null,
      people_cluster_ids: [],
      speech_segment_count: 3,
      keyframe_timestamp_ms: 0,
      debug: {
        lexical_rank: 1,
        lexical_score: 10.5,
        vector_rank: 2,
        vector_score: 0.95,
        lexical_contribution: 0.45,
        vector_contribution: 0.25,
        fused_score: 0.7,
        quality_factor: 1,
        adjusted_score: 0.7,
        diversification_penalty: false,
      },
    };
    expect(scene.speech_segment_count).toBe(3);
    expect(scene.scene_id).toBe("vid123_scene_0");
  });

  it("SegmentResult retains backward-compatible shape", () => {
    const segment: SegmentResult = {
      segment_id: "seg1",
      video_id: "vid1",
      video_title: null,
      library_id: "lib1",
      library_name: "Test",
      start_ms: 0,
      end_ms: 1000,
      snippet: "text",
      thumbnail_url: null,
      source_type: "gdrive",
      required_drive_nickname: null,
      capture_time: null,
      people_cluster_ids: [],
      keyframe_timestamp_ms: 0,
      debug: {
        lexical_rank: null,
        lexical_score: null,
        vector_rank: 1,
        vector_score: 0.9,
        lexical_contribution: 0,
        vector_contribution: 0.5,
        fused_score: 0.5,
        quality_factor: 1,
        adjusted_score: 0.5,
        diversification_penalty: false,
      },
    };
    expect(segment.segment_id).toBe("seg1");
  });

  it("AnySearchResponse discriminates on result_type", () => {
    const sceneResp: SceneSearchResponse = {
      results: [],
      total_candidates: 0,
      facets: { libraries: [], source_types: [], people_cluster_ids: [] },
      query: "test",
      alpha: 0.5,
      result_type: "scene",
    };

    const segResp: SearchResponse = {
      results: [],
      total_candidates: 0,
      facets: { libraries: [], source_types: [], people_cluster_ids: [] },
      query: "test",
      alpha: 0.5,
    };

    const responses: AnySearchResponse[] = [sceneResp, segResp];
    for (const r of responses) {
      if (r.result_type === "scene") {
        expect(r.result_type).toBe("scene");
      } else {
        expect(r.result_type).toBeUndefined();
      }
    }
  });

  it("SearchResponse result_type is optional for backward compat", () => {
    const resp: SearchResponse = {
      results: [],
      total_candidates: 0,
      facets: { libraries: [], source_types: [], people_cluster_ids: [] },
      query: "test",
      alpha: 0.5,
    };
    expect(resp.result_type).toBeUndefined();
  });
});
