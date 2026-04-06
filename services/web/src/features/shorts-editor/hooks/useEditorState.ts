import { useReducer, useCallback } from "react";
import type { EditorState, EditorAction, EditorClip, EditorSubtitle } from "../lib/types";
import { recomputeTimeline, getTotalDuration } from "../lib/timeline-math";
import { DEFAULT_ZOOM, DEFAULT_SUBTITLE_STYLE, DEFAULT_SUBTITLE_DURATION_MS } from "../constants";
import { parseSpeakerTranscript } from "@/lib/speaker-transcript";

const INITIAL_STATE: EditorState = {
  videoId: "",
  sourceType: "gdrive",
  clips: [],
  subtitles: [],
  selectedClipIndex: null,
  selectedSubtitleIndex: null,
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

// Korean sentence-ending patterns + common punctuation
const SENTENCE_SPLIT_RE = /(?<=[.!?。])\s+|(?<=[요다죠음네까게세지]\.?\s)/g;
const MAX_SUBTITLE_CHARS = 60;
const SUBTITLE_FONT_SIZE = 24;

/**
 * Split long text into subtitle-friendly chunks (~60 chars max).
 * Prefers splitting on Korean sentence endings (요, 다, 죠, etc.) and punctuation.
 */
function chunkSubtitleText(text: string): string[] {
  if (text.length <= MAX_SUBTITLE_CHARS) return [text];

  // First try splitting on sentence boundaries
  const sentences = text.split(SENTENCE_SPLIT_RE).filter((s) => s.trim());
  const chunks: string[] = [];
  let current = "";

  for (const sentence of sentences) {
    const candidate = current ? `${current} ${sentence}` : sentence;
    if (candidate.length <= MAX_SUBTITLE_CHARS) {
      current = candidate;
    } else {
      if (current) chunks.push(current.trim());
      // If a single sentence is too long, split by character limit
      if (sentence.length > MAX_SUBTITLE_CHARS) {
        const words = sentence.split(/\s+/);
        current = "";
        for (const word of words) {
          const next = current ? `${current} ${word}` : word;
          if (next.length > MAX_SUBTITLE_CHARS) {
            if (current) chunks.push(current.trim());
            current = word;
          } else {
            current = next;
          }
        }
      } else {
        current = sentence;
      }
    }
  }
  if (current.trim()) chunks.push(current.trim());

  return chunks.length > 0 ? chunks : [text.slice(0, MAX_SUBTITLE_CHARS)];
}

/**
 * Generate subtitle blocks from a scene's speaker transcript.
 * Long turns are chunked into ~60-char segments for readable display.
 */
export function generateSubtitlesFromTranscript(
  speakerTranscript: string | undefined | null,
  clip: EditorClip,
): EditorSubtitle[] {
  const turns = parseSpeakerTranscript(speakerTranscript);
  if (turns.length === 0) return [];

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

  if (turnsWithTs.length > 0) {
    // Timestamp-based: chunk each turn, distribute chunks within the turn's time slot
    for (let i = 0; i < turnsWithTs.length; i++) {
      const { turn, ms: offsetMs } = turnsWithTs[i];
      const relativeMs = offsetMs - clip.trimStartMs;
      if (relativeMs < 0 || relativeMs >= clipDuration) continue;

      const nextRelative = i + 1 < turnsWithTs.length
        ? turnsWithTs[i + 1].ms - clip.trimStartMs
        : clipDuration;
      const slotDuration = Math.min(nextRelative - relativeMs, DEFAULT_SUBTITLE_DURATION_MS * 3);

      const chunks = chunkSubtitleText(turn.text);
      const chunkDuration = Math.max(1500, Math.floor(slotDuration / chunks.length));

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
  } else {
    // No timestamps: distribute all chunks evenly across clip
    const chunkDuration = Math.max(1500, Math.floor(clipDuration / allChunks.length));
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
    updateSubtitle,
    removeSubtitle,
    selectSubtitle,
    setPlayhead,
    setPlaying,
    setZoom,
    markClean,
  };
}
