import { useReducer, useCallback } from "react";
import type { EditorState, EditorAction, EditorClip, EditorSubtitle } from "../lib/types";
import type { EditorOverlay } from "../lib/overlay-types";
import {
  createDefaultBackgroundOverlay,
  createDefaultTextOverlay,
  DEFAULT_OVERLAY_DURATION_MS,
} from "../lib/overlay-defaults";
import { recomputeTimeline, getTotalDuration } from "../lib/timeline-math";
import { DEFAULT_ZOOM, DEFAULT_SUBTITLE_STYLE, DEFAULT_SUBTITLE_DURATION_MS } from "../constants";
import { parseSpeakerTranscript } from "@/lib/speaker-transcript";

const INITIAL_STATE: EditorState = {
  videoId: "",
  sourceType: "gdrive",
  clips: [],
  subtitles: [],
  overlays: [],
  selectedClipIndex: null,
  selectedSubtitleIndex: null,
  selectedOverlayId: null,
  playheadMs: 0,
  isPlaying: false,
  totalDurationMs: 0,
  zoom: DEFAULT_ZOOM,
  isDirty: false,
};

function clampVolume(v: number): number {
  return Math.max(0, Math.min(3, v));
}

function editorReducer(state: EditorState, action: EditorAction): EditorState {
  switch (action.type) {
    case "INIT_FROM_SCENES": {
      const clips = recomputeTimeline(action.clips);
      return {
        ...INITIAL_STATE,
        videoId: action.videoId,
        sourceType: action.sourceType,
        clips,
        totalDurationMs: getTotalDuration(clips),
      };
    }

    case "INIT_FROM_COMPOSITION": {
      const merged = { ...INITIAL_STATE, ...action.state };
      const clips = recomputeTimeline(merged.clips);
      return {
        ...merged,
        clips,
        totalDurationMs: getTotalDuration(clips),
        isDirty: false,
      };
    }

    case "ADD_CLIP": {
      const clips = recomputeTimeline([...state.clips, action.clip]);
      return {
        ...state,
        clips,
        totalDurationMs: getTotalDuration(clips),
        isDirty: true,
      };
    }

    case "REMOVE_CLIP": {
      if (action.index < 0 || action.index >= state.clips.length) return state;
      const next = state.clips.filter((_, i) => i !== action.index);
      const clips = recomputeTimeline(next);
      let newSelected = state.selectedClipIndex;
      if (newSelected != null) {
        if (newSelected === action.index) newSelected = null;
        else if (newSelected > action.index) newSelected -= 1;
      }
      return {
        ...state,
        clips,
        totalDurationMs: getTotalDuration(clips),
        selectedClipIndex: newSelected,
        isDirty: true,
      };
    }

    case "REORDER_CLIPS": {
      const { fromIndex, toIndex } = action;
      if (
        fromIndex < 0 ||
        toIndex < 0 ||
        fromIndex >= state.clips.length ||
        toIndex >= state.clips.length ||
        fromIndex === toIndex
      ) {
        return state;
      }
      const next = [...state.clips];
      const [moved] = next.splice(fromIndex, 1);
      next.splice(toIndex, 0, moved);
      const clips = recomputeTimeline(next);
      return {
        ...state,
        clips,
        totalDurationMs: getTotalDuration(clips),
        selectedClipIndex: toIndex,
        isDirty: true,
      };
    }

    case "TRIM_CLIP": {
      const { index, trimStartMs, trimEndMs } = action;
      if (index < 0 || index >= state.clips.length) return state;
      const clip = state.clips[index];
      const newStart = trimStartMs != null
        ? Math.max(clip.originalStartMs, Math.min(trimStartMs, clip.trimEndMs - 1))
        : clip.trimStartMs;
      const newEnd = trimEndMs != null
        ? Math.min(clip.originalEndMs, Math.max(trimEndMs, newStart + 1))
        : clip.trimEndMs;
      const next = state.clips.map((c, i) =>
        i === index ? { ...c, trimStartMs: newStart, trimEndMs: newEnd } : c,
      );
      const clips = recomputeTimeline(next);
      return {
        ...state,
        clips,
        totalDurationMs: getTotalDuration(clips),
        isDirty: true,
      };
    }

    case "SET_CLIP_VOLUME": {
      if (action.index < 0 || action.index >= state.clips.length) return state;
      const clips = state.clips.map((c, i) =>
        i === action.index ? { ...c, volume: clampVolume(action.volume) } : c,
      );
      return { ...state, clips, isDirty: true };
    }

    case "SELECT_CLIP":
      return {
        ...state,
        selectedClipIndex: action.index,
        selectedSubtitleIndex: action.index != null ? null : state.selectedSubtitleIndex,
      };

    case "ADD_SUBTITLE": {
      return {
        ...state,
        subtitles: [...state.subtitles, action.subtitle],
        isDirty: true,
      };
    }

    case "UPDATE_SUBTITLE": {
      if (action.index < 0 || action.index >= state.subtitles.length) return state;
      const subtitles = state.subtitles.map((s, i) =>
        i === action.index ? { ...s, ...action.updates } : s,
      );
      return { ...state, subtitles, isDirty: true };
    }

    case "REMOVE_SUBTITLE": {
      if (action.index < 0 || action.index >= state.subtitles.length) return state;
      let newSelected = state.selectedSubtitleIndex;
      if (newSelected != null) {
        if (newSelected === action.index) newSelected = null;
        else if (newSelected > action.index) newSelected -= 1;
      }
      return {
        ...state,
        subtitles: state.subtitles.filter((_, i) => i !== action.index),
        selectedSubtitleIndex: newSelected,
        isDirty: true,
      };
    }

    case "SELECT_SUBTITLE":
      return {
        ...state,
        selectedSubtitleIndex: action.index,
        selectedClipIndex: action.index != null ? null : state.selectedClipIndex,
      };

    case "ADD_OVERLAY": {
      // New overlay lands at the front (highest layer_index) so the user sees
      // it on top of existing overlays. Caller can REORDER_OVERLAY afterward.
      const maxLayer = state.overlays.reduce(
        (m, o) => Math.max(m, o.layerIndex),
        -1,
      );
      const positioned: EditorOverlay = {
        ...action.overlay,
        layerIndex: maxLayer + 1,
      };
      return {
        ...state,
        overlays: [...state.overlays, positioned],
        selectedOverlayId: positioned.id,
        // Selecting a new overlay clears clip + subtitle selection so the
        // panel switches to overlay-edit mode.
        selectedClipIndex: null,
        selectedSubtitleIndex: null,
        isDirty: true,
      };
    }

    case "UPDATE_OVERLAY": {
      const overlays = state.overlays.map((o) =>
        o.id === action.id
          // Spread is type-safe because each overlay variant's discriminator
          // (`kind`) can't be changed via UPDATE_OVERLAY — the schema rules
          // it out by validation, but TS sees it as Partial<EditorOverlay>
          // so we cast the merge result to the original variant.
          ? ({ ...o, ...action.updates } as EditorOverlay)
          : o,
      );
      return { ...state, overlays, isDirty: true };
    }

    case "REMOVE_OVERLAY": {
      const overlays = state.overlays.filter((o) => o.id !== action.id);
      return {
        ...state,
        overlays,
        selectedOverlayId:
          state.selectedOverlayId === action.id ? null : state.selectedOverlayId,
        isDirty: true,
      };
    }

    case "SELECT_OVERLAY":
      return {
        ...state,
        selectedOverlayId: action.id,
        selectedClipIndex: action.id != null ? null : state.selectedClipIndex,
        selectedSubtitleIndex: action.id != null ? null : state.selectedSubtitleIndex,
      };

    case "REORDER_OVERLAY": {
      const idx = state.overlays.findIndex((o) => o.id === action.id);
      if (idx < 0) return state;
      const sorted = [...state.overlays].sort(
        (a, b) => a.layerIndex - b.layerIndex,
      );
      const sortedIdx = sorted.findIndex((o) => o.id === action.id);
      let targetSortedIdx = sortedIdx;
      switch (action.direction) {
        case "back":
          targetSortedIdx = 0;
          break;
        case "front":
          targetSortedIdx = sorted.length - 1;
          break;
        case "backward":
          targetSortedIdx = Math.max(0, sortedIdx - 1);
          break;
        case "forward":
          targetSortedIdx = Math.min(sorted.length - 1, sortedIdx + 1);
          break;
      }
      if (targetSortedIdx === sortedIdx) return state;
      const [moved] = sorted.splice(sortedIdx, 1);
      sorted.splice(targetSortedIdx, 0, moved);
      // Re-pack layer indices densely from 0 to keep the dropdown labels
      // legible ("프리셋1" stays "프리셋1") and avoids unbounded growth.
      const overlays = sorted.map((o, i) => ({ ...o, layerIndex: i }));
      return { ...state, overlays, isDirty: true };
    }

    case "SET_PLAYHEAD":
      return { ...state, playheadMs: Math.max(0, action.ms) };

    case "SET_PLAYING":
      return { ...state, isPlaying: action.playing };

    case "SET_ZOOM":
      return { ...state, zoom: Math.max(25, Math.min(300, action.zoom)) };

    case "MARK_CLEAN":
      return { ...state, isDirty: false };

    default:
      return state;
  }
}

let _clipCounter = 0;
export function generateClipId(): string {
  return `clip_${Date.now()}_${++_clipCounter}`;
}

let _subtitleCounter = 0;
export function generateSubtitleId(): string {
  return `sub_${Date.now()}_${++_subtitleCounter}`;
}

export function createClipFromScene(
  scene: { scene_id: string; start_ms: number; end_ms: number; scene_caption?: string; ai_tags?: string[] },
  videoId: string,
  sourceType: string,
): EditorClip {
  const label = scene.scene_caption?.slice(0, 30) || scene.ai_tags?.[0] || undefined;
  return {
    id: generateClipId(),
    sceneId: scene.scene_id,
    videoId,
    sourceType,
    originalStartMs: scene.start_ms,
    originalEndMs: scene.end_ms,
    trimStartMs: scene.start_ms,
    trimEndMs: scene.end_ms,
    timelineStartMs: 0,
    volume: 1.0,
    label,
  };
}

/**
 * Parse a timestamp string like "1:23" or "0:05" into milliseconds.
 */
function parseTimestampMs(ts: string): number | null {
  const parts = ts.split(":").map(Number);
  if (parts.some(isNaN)) return null;
  if (parts.length === 3) return (parts[0] * 3600 + parts[1] * 60 + parts[2]) * 1000;
  if (parts.length === 2) return (parts[0] * 60 + parts[1]) * 1000;
  return null;
}

// Sentence-ending patterns (Korean + Latin) — primary split.
const SENTENCE_SPLIT_RE = /(?<=[.!?。])\s+|(?<=[요다죠음네까게세지]\.?\s)/g;

// Korean clause-boundary patterns — secondary split for finer chunks.
// Conjunctive endings ("는데", "면서요", "이기 때문에", etc.) and
// connective particles mark natural pause points where Korean speakers
// breathe. Matching these gives subtitles that flow with speech rather
// than dumping a whole turn into one block.
//
// Each pattern uses a positive lookbehind so the boundary stays attached
// to the LEFT chunk (e.g., "...이벤트이기 | 때문에" → "이벤트이기"
// stays as one chunk's tail, "때문에" starts the next).
const CLAUSE_SPLIT_RE = /(?<=,)\s+|(?<=[는면서고지만니까데서야면])\s+(?=[가-힣])/g;

// 25 chars is roughly 5-7 Korean eojeol — short enough to read in 1-2s
// at typical livecommerce pacing, long enough to avoid choppy 2-word
// fragments. Calibrated against the operator-target screenshot where
// rows ranged 3-16 chars.
const MAX_SUBTITLE_CHARS = 25;
const SUBTITLE_FONT_SIZE = 24;

/**
 * Split text into subtitle-friendly chunks that flow naturally with
 * speech. Two-pass split: sentence boundaries first, then Korean
 * clause boundaries within each sentence; falls back to greedy
 * eojeol-by-eojeol packing for runaway sentences with no commas or
 * conjunctive endings.
 *
 * Goal: each chunk reads in ~1-2s at livecommerce pace, matching the
 * operator-target inline-editor UX (Clip 1-N "자동 자막" panel).
 */
function chunkSubtitleText(text: string): string[] {
  const trimmed = text.trim();
  if (!trimmed) return [];
  if (trimmed.length <= MAX_SUBTITLE_CHARS) return [trimmed];

  // Pass 1: sentence-level split.
  const sentences = trimmed.split(SENTENCE_SPLIT_RE).filter((s) => s.trim());
  const chunks: string[] = [];

  for (const sentence of sentences) {
    if (sentence.length <= MAX_SUBTITLE_CHARS) {
      chunks.push(sentence.trim());
      continue;
    }
    // Pass 2: clause-level split inside an oversize sentence.
    const clauses = sentence
      .split(CLAUSE_SPLIT_RE)
      .map((c) => c.trim())
      .filter(Boolean);

    let current = "";
    for (const clause of clauses) {
      if (clause.length > MAX_SUBTITLE_CHARS) {
        // Pass 3: eojeol greedy pack — fall through when a single
        // clause is still too long (no clause boundary inside).
        if (current) {
          chunks.push(current);
          current = "";
        }
        const eojeols = clause.split(/\s+/);
        let buf = "";
        for (const e of eojeols) {
          const next = buf ? `${buf} ${e}` : e;
          if (next.length > MAX_SUBTITLE_CHARS) {
            if (buf) chunks.push(buf);
            buf = e;
          } else {
            buf = next;
          }
        }
        if (buf) {
          // Hold the tail in `current` so the next clause can
          // potentially co-pack with it (don't push prematurely).
          current = buf;
        }
        continue;
      }
      const candidate = current ? `${current} ${clause}` : clause;
      if (candidate.length <= MAX_SUBTITLE_CHARS) {
        current = candidate;
      } else {
        if (current) chunks.push(current);
        current = clause;
      }
    }
    if (current) chunks.push(current);
  }

  return chunks.length > 0 ? chunks : [trimmed.slice(0, MAX_SUBTITLE_CHARS)];
}

/**
 * Generate subtitle blocks from a scene's speaker transcript.
 * Long turns are chunked into ~60-char segments for readable display.
 */
export function generateSubtitlesFromTranscript(
  speakerTranscript: string | undefined | null,
  clip: EditorClip,
): EditorSubtitle[] {
  let turns = parseSpeakerTranscript(speakerTranscript);
  // Fallback: scenes without the ``SPEAKER_XX [m:ss]: text`` envelope
  // (e.g., raw transcripts piped in from older indexing runs) parse to
  // zero turns even when they carry usable text. When that happens we
  // synthesize a single untimed turn from the original string so the
  // even-distribution branch below still produces subtitles. Without
  // this, /videos → editor entries with non-speaker-tagged transcripts
  // landed in the editor with an empty subtitle list.
  if (turns.length === 0) {
    const raw = (speakerTranscript ?? "").trim();
    if (!raw) return [];
    turns = [
      {
        rawId: "UNTAGGED",
        label: "A",
        color: { bg: "", text: "", border: "" },
        text: raw,
        timestamp: null,
      },
    ];
  }

  const clipDuration = clip.trimEndMs - clip.trimStartMs;
  const style = { ...DEFAULT_SUBTITLE_STYLE, fontSizePx: SUBTITLE_FONT_SIZE };

  // Flatten all turns into text chunks for even timing
  const allChunks: string[] = [];
  for (const turn of turns) {
    allChunks.push(...chunkSubtitleText(turn.text));
  }

  if (allChunks.length === 0) return [];

  // Check if turns have usable timestamps
  const turnsWithTs = turns
    .map((turn) => ({ turn, ms: turn.timestamp ? parseTimestampMs(turn.timestamp) : null }))
    .filter((t) => t.ms != null) as Array<{ turn: typeof turns[0]; ms: number }>;

  const subtitles: EditorSubtitle[] = [];

  // Transcripts can store timestamps two ways: absolute video time
  // (offset from video start, so offsetMs ≥ clip.trimStartMs) or
  // scene-relative (offset from scene start, so offsetMs ≥ 0 and
  // < clipDuration). Sample EVERY turn against both interpretations and
  // commit to whichever fits more turns inside the scene window — a
  // single-turn sample (the previous heuristic) flipped to interpretRel
  // on stray near-zero timestamps and crammed unrelated text into the
  // scene. Ties break toward interpretAbs (the more conservative read).
  // The timed loop below filters per-turn out-of-range entries so a
  // mismatched transcript naturally produces few/no subtitles via the
  // same gate, rather than via a brittle confidence threshold that
  // dropped legitimate single-turn scenes (regression surfaced 2026-05-18).
  const interpretAbs = (offsetMs: number) => offsetMs - clip.trimStartMs;
  const interpretRel = (offsetMs: number) => offsetMs;
  let interpretMs: (offsetMs: number) => number = interpretAbs;
  if (turnsWithTs.length > 0) {
    let absHits = 0;
    let relHits = 0;
    for (const { ms } of turnsWithTs) {
      const a = interpretAbs(ms);
      if (a >= 0 && a < clipDuration) absHits++;
      const r = interpretRel(ms);
      if (r >= 0 && r < clipDuration) relHits++;
    }
    interpretMs = absHits >= relHits ? interpretAbs : interpretRel;
  }

  if (turnsWithTs.length > 0) {
    // Timestamp-based: chunk each turn, distribute chunks within the turn's time slot
    for (let i = 0; i < turnsWithTs.length; i++) {
      const { turn, ms: offsetMs } = turnsWithTs[i];
      const relativeMs = interpretMs(offsetMs);
      if (relativeMs < 0 || relativeMs >= clipDuration) continue;

      const nextRelative = i + 1 < turnsWithTs.length
        ? interpretMs(turnsWithTs[i + 1].ms)
        : clipDuration;
      const slotDuration = Math.min(nextRelative - relativeMs, DEFAULT_SUBTITLE_DURATION_MS * 3);

      const chunks = chunkSubtitleText(turn.text);
      const chunkDuration = Math.max(800, Math.floor(slotDuration / chunks.length));

      for (let j = 0; j < chunks.length; j++) {
        const startMs = relativeMs + j * chunkDuration;
        if (startMs >= clipDuration) break;
        const endMs = Math.min(startMs + chunkDuration, clipDuration);

        subtitles.push({
          id: generateSubtitleId(),
          text: chunks[j],
          startMs: clip.timelineStartMs + startMs,
          endMs: clip.timelineStartMs + endMs,
          style: { ...style },
        });
      }
    }
  }

  // Fall through to even-distribution whenever the timestamp branch
  // produced nothing — happens both when the transcript has no
  // timestamps at all and when every timestamp fell outside the scene
  // window. The earlier turnsWithTs-only gate stopped subtitles from
  // showing for scenes whose stamps were slightly out of range, which
  // surfaced as "subtitles aren't loading anymore" on 2026-05-18. The
  // cross-runtime symptom this gate guarded against is rarer than
  // legitimate off-by-a-bit stamps, so we accept the trade and let
  // operators delete unwanted lines manually.
  if (subtitles.length === 0) {
    // No timestamps: distribute all chunks evenly across clip
    const chunkDuration = Math.max(800, Math.floor(clipDuration / allChunks.length));
    if (chunkDuration < 500) return [];

    for (let i = 0; i < allChunks.length; i++) {
      const startMs = clip.timelineStartMs + i * chunkDuration;
      if (startMs >= clip.timelineStartMs + clipDuration) break;
      const endMs = Math.min(startMs + chunkDuration, clip.timelineStartMs + clipDuration);

      subtitles.push({
        id: generateSubtitleId(),
        text: allChunks[i],
        startMs,
        endMs,
        style: { ...style },
      });
    }
  }

  return subtitles;
}

export function useEditorState() {
  const [state, dispatch] = useReducer(editorReducer, INITIAL_STATE);

  const initFromScenes = useCallback(
    (videoId: string, sourceType: string, clips: EditorClip[]) => {
      dispatch({ type: "INIT_FROM_SCENES", videoId, sourceType, clips });
    },
    [],
  );

  const initFromComposition = useCallback((partial: Partial<EditorState>) => {
    dispatch({ type: "INIT_FROM_COMPOSITION", state: partial });
  }, []);

  const addClip = useCallback((clip: EditorClip) => {
    dispatch({ type: "ADD_CLIP", clip });
  }, []);

  const removeClip = useCallback((index: number) => {
    dispatch({ type: "REMOVE_CLIP", index });
  }, []);

  const reorderClips = useCallback((fromIndex: number, toIndex: number) => {
    dispatch({ type: "REORDER_CLIPS", fromIndex, toIndex });
  }, []);

  const trimClip = useCallback(
    (index: number, trimStartMs?: number, trimEndMs?: number) => {
      dispatch({ type: "TRIM_CLIP", index, trimStartMs, trimEndMs });
    },
    [],
  );

  const setClipVolume = useCallback((index: number, volume: number) => {
    dispatch({ type: "SET_CLIP_VOLUME", index, volume });
  }, []);

  const selectClip = useCallback((index: number | null) => {
    dispatch({ type: "SELECT_CLIP", index });
  }, []);

  const addSubtitle = useCallback((subtitle: EditorSubtitle) => {
    dispatch({ type: "ADD_SUBTITLE", subtitle });
  }, []);

  const addOverlayAtPlayhead = useCallback(() => {
    const totalMs = state.totalDurationMs;
    const startMs = Math.max(0, Math.min(state.playheadMs, Math.max(0, totalMs - 500)));
    const endMs = totalMs > 0
      ? Math.min(startMs + DEFAULT_SUBTITLE_DURATION_MS, totalMs)
      : startMs + DEFAULT_SUBTITLE_DURATION_MS;
    const subtitle: EditorSubtitle = {
      id: generateSubtitleId(),
      text: "",
      startMs,
      endMs,
      style: { ...DEFAULT_SUBTITLE_STYLE },
    };
    const newIndex = state.subtitles.length;
    dispatch({ type: "ADD_SUBTITLE", subtitle });
    dispatch({ type: "SELECT_SUBTITLE", index: newIndex });
  }, [state.playheadMs, state.totalDurationMs, state.subtitles.length]);

  const updateSubtitle = useCallback(
    (index: number, updates: Partial<Omit<EditorSubtitle, "id">>) => {
      dispatch({ type: "UPDATE_SUBTITLE", index, updates });
    },
    [],
  );

  const removeSubtitle = useCallback((index: number) => {
    dispatch({ type: "REMOVE_SUBTITLE", index });
  }, []);

  const selectSubtitle = useCallback((index: number | null) => {
    dispatch({ type: "SELECT_SUBTITLE", index });
  }, []);

  // ----- V2 overlay actions ------------------------------------------------

  const _clampOverlayWindow = (playheadMs: number, totalMs: number) => {
    const startMs = Math.max(0, Math.min(playheadMs, Math.max(0, totalMs - 500)));
    const endMs = totalMs > 0
      ? Math.min(startMs + DEFAULT_OVERLAY_DURATION_MS, totalMs)
      : startMs + DEFAULT_OVERLAY_DURATION_MS;
    return { startMs, endMs };
  };

  const addTextOverlayAtPlayhead = useCallback(() => {
    const { startMs, endMs } = _clampOverlayWindow(
      state.playheadMs,
      state.totalDurationMs,
    );
    dispatch({
      type: "ADD_OVERLAY",
      overlay: createDefaultTextOverlay({ startMs, endMs }),
    });
  }, [state.playheadMs, state.totalDurationMs]);

  // Auto-subtitle path needs explicit timing + pre-filled text. The
  // playhead-based helper above can't fill text, and the V2 timeline only
  // renders text overlays — V1 subtitles in state.subtitles never make it
  // onto the timeline when isShortsEditorV2Enabled() is true. This helper
  // lets the page-level effect insert a fully-formed overlay (timing+text)
  // so generated subtitles light up the V2 timeline immediately.
  const addTextOverlay = useCallback(
    (params: { text: string; startMs: number; endMs: number }) => {
      const overlay = createDefaultTextOverlay({
        startMs: params.startMs,
        endMs: params.endMs,
      });
      dispatch({
        type: "ADD_OVERLAY",
        overlay: { ...overlay, text: params.text },
      });
    },
    [],
  );

  const addBackgroundOverlayAtPlayhead = useCallback(
    (fillColor?: string) => {
      const { startMs, endMs } = _clampOverlayWindow(
        state.playheadMs,
        state.totalDurationMs,
      );
      dispatch({
        type: "ADD_OVERLAY",
        overlay: createDefaultBackgroundOverlay({ startMs, endMs, fillColor }),
      });
    },
    [state.playheadMs, state.totalDurationMs],
  );

  // "Insert image" path — seeds a new background overlay with the
  // data URL the file picker returned. Kept separate from the solid-
  // background factory so the call sites don't have to juggle a
  // discriminated argument shape.
  const addImageBackgroundOverlayAtPlayhead = useCallback(
    (imageUrl: string) => {
      const { startMs, endMs } = _clampOverlayWindow(
        state.playheadMs,
        state.totalDurationMs,
      );
      dispatch({
        type: "ADD_OVERLAY",
        overlay: createDefaultBackgroundOverlay({ startMs, endMs, imageUrl }),
      });
    },
    [state.playheadMs, state.totalDurationMs],
  );

  const updateOverlay = useCallback(
    (id: string, updates: Partial<EditorOverlay>) => {
      dispatch({ type: "UPDATE_OVERLAY", id, updates });
    },
    [],
  );

  const removeOverlay = useCallback((id: string) => {
    dispatch({ type: "REMOVE_OVERLAY", id });
  }, []);

  const selectOverlay = useCallback((id: string | null) => {
    dispatch({ type: "SELECT_OVERLAY", id });
  }, []);

  const reorderOverlay = useCallback(
    (id: string, direction: "front" | "back" | "forward" | "backward") => {
      dispatch({ type: "REORDER_OVERLAY", id, direction });
    },
    [],
  );

  const setPlayhead = useCallback((ms: number) => {
    dispatch({ type: "SET_PLAYHEAD", ms });
  }, []);

  const setPlaying = useCallback((playing: boolean) => {
    dispatch({ type: "SET_PLAYING", playing });
  }, []);

  const setZoom = useCallback((zoom: number) => {
    dispatch({ type: "SET_ZOOM", zoom });
  }, []);

  const markClean = useCallback(() => {
    dispatch({ type: "MARK_CLEAN" });
  }, []);

  return {
    state,
    dispatch,
    initFromScenes,
    initFromComposition,
    addClip,
    removeClip,
    reorderClips,
    trimClip,
    setClipVolume,
    selectClip,
    addSubtitle,
    addOverlayAtPlayhead,
    updateSubtitle,
    removeSubtitle,
    selectSubtitle,
    // V2 overlay actions
    addTextOverlay,
    addTextOverlayAtPlayhead,
    addBackgroundOverlayAtPlayhead,
    addImageBackgroundOverlayAtPlayhead,
    updateOverlay,
    removeOverlay,
    selectOverlay,
    reorderOverlay,
    setPlayhead,
    setPlaying,
    setZoom,
    markClean,
  };
}
