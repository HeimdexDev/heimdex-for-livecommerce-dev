"use client";

/**
 * Inline subtitle editor for the auto-shorts product wizard.
 *
 * Lands here from WizardStepResult's "스크립트 편집" button. Lets the
 * operator switch between Clip 1-N, edit subtitles inline, and click
 * "내보내기" to re-render the selected clip with the edits.
 *
 * Reuses primitives from the manual shorts-editor:
 *   - generateSubtitlesFromTranscript / createClipFromScene
 *   - submitRender (POST /api/shorts/render)
 *   - getShortComposition / getRenderJob (per-clip data)
 *
 * MVP cut from the screenshot mockup:
 *   - Top tabs (쇼츠 제목 / 상품 정보 / 원본 영상 제목) — not on the
 *     critical path to "edit subtitles."
 *   - Sub-tabs (레이아웃 / 요소 및 배경) — same.
 *   - Per-subtitle font/color/position controls — leverage the
 *     EditorSubtitle defaults; deferred to Phase 2.5+.
 */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { forwardRef, useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  getRenderJob,
  getShortComposition,
} from "@/lib/api/shorts-render";
import type { SubtitleEdit } from "@/lib/api/highlight-reel";
import type { SubtitleCueStyle } from "@/lib/subtitle-layout";
import { getVideoScenes } from "@/lib/api/videos";
import type { VideoScene, VideoScenesResponse } from "@/lib/types";
import { useAuth } from "@/lib/auth";

import { DEFAULT_SUBTITLE_STYLE } from "@/features/shorts-editor/constants";
import {
  createClipFromScene,
  generateSubtitlesFromTranscript,
} from "@/features/shorts-editor/hooks/useEditorState";
import type {
  EditorClip,
  EditorSubtitle,
  SubtitleStyle,
} from "@/features/shorts-editor/lib/types";

import { ExportShortsButton } from "../components/ExportShortsButton";
import { InlineWizardBreadcrumb } from "../components/InlineWizardBreadcrumb";
import {
  RightPanelTabs,
  type RightPanelTab,
} from "../components/RightPanelTabs";
import { StyleTab } from "../components/StyleTab";
import type { SubtitleEditorHandle } from "../components/SubtitleEditor";
import { SubtitlesTab } from "../components/SubtitlesTab";
import {
  SubtitleOverlay,
  type SubtitleOverlayCue,
} from "../components/SubtitleOverlay";
import { useExportBatch } from "../hooks/useExportBatch";
import { useScanOrder } from "../hooks/useScanOrder";
import { useSyntheticScanOrder } from "../hooks/useSyntheticScanOrder";
import {
  applyGlobalStyleToCues,
  deriveGlobalStyle,
  makeDefaultStyle,
  mergeStyle,
  type SubtitleStyleDraft,
} from "../lib/global-style";

// Wizard mode: the original auto-shorts wizard flow. The page drives a
// scan-order parent and renders 1-N clips as tabs. ``parentJobId``
// is the ``scan_order`` UUID; ``useScanOrder`` polls it.
interface WizardModeProps {
  mode: "wizard";
  videoId: string;
  parentJobId: string;
}

// Single mode: a saved-shorts row in ``/export/shorts`` was clicked
// to edit one specific render. No parent scan-order exists; we
// synthesize a one-child ``ScanOrderStatusResponse`` from the
// render via ``useSyntheticScanOrder`` so the rest of the page
// renders unchanged.
interface SingleModeProps {
  mode: "single";
  videoId: string;
  renderJobId: string;
}

// ``mode`` is REQUIRED on both branches so TypeScript can narrow
// ``props.parentJobId`` vs. ``props.renderJobId`` at the use sites.
// The existing wizard route mounting this page must pass
// ``mode="wizard"`` explicitly — that's a one-line touch.
type Props = WizardModeProps | SingleModeProps;

interface ClipState {
  /** Render job id for this clip (Clip 1, Clip 2, ...). */
  renderJobId: string;
  /** 0-based index — drives Clip 1, Clip 2, ... display. */
  index: number;
  /** Title from the render job (the wizard sets these to product names). */
  title: string;
  /** Per-scene EditorClip metadata (timeline positions). One clip per scene. */
  clips: EditorClip[];
  /** Subtitles, edited locally. Initially generated from speaker_transcript. */
  subtitles: EditorSubtitle[];
  /** The render job's existing composition (used as the base for re-render). */
  composition: Record<string, unknown> | null;
  /** Presigned MP4 URL. May be null until the render finishes. */
  downloadUrl: string | null;
  /** Total duration in ms — sum of clip trim ranges. */
  totalDurationMs: number;
  /** Loading state for first-fetch. */
  loading: boolean;
  /** Per-clip error message. */
  error: string | null;
  /**
   * Backend's ``refinement_source`` flag — drives the SubtitleEditor's
   * "edits not yet rendered" banner. Set to ``'manual_edit'`` once
   * the operator has saved edits via PATCH /subtitles.
   */
  refinementSource: string | null;
}

export function EditClipsPage(props: Props) {
  const { videoId, mode } = props;
  const { getAccessToken } = useAuth();
  const searchParams = useSearchParams();

  // Both hooks are called unconditionally to satisfy the rules of
  // hooks; the inactive one short-circuits on a ``null`` id (both
  // ``useScanOrder`` and ``useSyntheticScanOrder`` handle null
  // explicitly — see their bodies). Narrow via ``props.mode`` so
  // the type checker can resolve ``parentJobId`` vs ``renderJobId``.
  const wizardScanOrder = useScanOrder(
    props.mode === "wizard" ? props.parentJobId : null,
    getAccessToken,
  );
  const singleScanOrder = useSyntheticScanOrder(
    props.mode === "single" ? props.renderJobId : null,
    getAccessToken,
  );
  const scanOrder = mode === "wizard" ? wizardScanOrder : singleScanOrder;

  const children = useMemo(
    () => scanOrder.status?.children ?? [],
    [scanOrder.status?.children],
  );

  const sortedChildren = useMemo(() => {
    return [...children]
      .filter((c) => Boolean(c.render_job_id))
      .sort((a, b) => (a.shorts_index ?? 0) - (b.shorts_index ?? 0));
  }, [children]);

  // Initial clip selection from ``?clipIdx=N`` query param. The wizard's
  // per-child "스크립트 편집" button passes shorts_index-1 so the editor
  // opens on the clip the user clicked. Defaults to 0 (Clip 1).
  const initialClipIdx = useMemo(() => {
    const raw = searchParams?.get("clipIdx");
    const parsed = raw != null ? parseInt(raw, 10) : NaN;
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
  }, [searchParams]);
  const [selectedClipIdx, setSelectedClipIdx] = useState(initialClipIdx);
  const [scenesByVideo, setScenesByVideo] = useState<VideoScenesResponse | null>(null);
  const [scenesError, setScenesError] = useState<string | null>(null);
  const [clipStates, setClipStates] = useState<Record<string, ClipState>>({});
  // Mirrors the SubtitleEditor's internal cue list per render id so the
  // in-player DOM overlay can preview operator edits before a re-render.
  // Keyed by renderId — switching clips does NOT reset entries here, so a
  // user can edit Clip 1, jump to Clip 2, jump back, and still see their
  // unrendered draft. Reset happens implicitly when the operator triggers
  // a re-render (page pivots to the new child render id).
  const [liveCuesByRender, setLiveCuesByRender] = useState<
    Record<string, SubtitleEdit[]>
  >({});
  const [activeTab, setActiveTab] = useState<RightPanelTab>("subtitles");
  // Page-owned controlled search query for the 자막 tab. Reset on clip
  // switch so a query that filtered Clip 1's cues to zero matches doesn't
  // greet the operator with an empty Clip 2.
  const [subtitleSearchQuery, setSubtitleSearchQuery] = useState("");
  // Page-owned global subtitle style draft (Phase C). ``null`` means the
  // current clip's cues have mixed styles — StyleTab surfaces a
  // "혼합됨" banner with an Apply-to-all affordance.
  const [styleDraft, setStyleDraft] = useState<SubtitleStyleDraft | null>(
    null,
  );
  // Imperative bridge to SubtitleEditor so style writes flow through the
  // SAME debounced PATCH the text editor uses. Avoids racing writers on
  // the same endpoint.
  const subtitleEditorRef = useRef<SubtitleEditorHandle | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [playheadMs, setPlayheadMs] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const exportBatch = useExportBatch(getAccessToken);

  // Fetch scenes once for the page.
  useEffect(() => {
    if (!videoId) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await getVideoScenes(videoId, 200, 0, getAccessToken);
        if (!cancelled) setScenesByVideo(res);
      } catch (err) {
        if (!cancelled) {
          setScenesError(err instanceof Error ? err.message : "장면을 불러올 수 없습니다.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [videoId, getAccessToken]);

  const selectedChild = sortedChildren[selectedClipIdx];
  const selectedRenderJobId = selectedChild?.render_job_id ?? null;

  // Overlay-mode (.claude/plans/auto-shorts-overlay-mode-2026-05-07.md):
  // the parent IS the canonical render. Whisper post-render writes
  // cues into parent.input_spec.subtitles (no child render created),
  // and the FE renders cues via <SubtitleOverlay> on top of the
  // parent's sub-less MP4. No chain to walk — load the parent
  // directly. The page polls via the loadClip useEffect for cue
  // updates as Whisper completes.
  //
  // The legacy `useRefinedRenderChain` hook is intentionally NOT
  // imported here; if the BE flag flips OFF, the parent stays
  // canonical from the FE's perspective and the operator sees
  // empty subs (degraded but not broken — staging-only fallback per
  // the plan's risk register).
  const effectiveRenderJobId = selectedRenderJobId;

  // Lazy-load per-clip data when the user switches to a clip we
  // haven't loaded yet. Note ``clipStates`` is intentionally NOT in
  // the dep array — including it caused a React race: the moment
  // this effect's first setClipStates({loading: true}) fired, the
  // effect re-ran (clipStates changed), the previous run's cleanup
  // set cancelled=true, and the async fetch's setClipStates was
  // silently dropped. State stayed stuck at {loading: true} forever.
  // Instead, the "already loaded" guard lives inside the functional
  // setState updater, which sees the freshest state without making
  // the effect react to its own writes.
  useEffect(() => {
    if (!effectiveRenderJobId || !scenesByVideo) return;

    let cancelled = false;
    let alreadyLoaded = false;
    setClipStates((prev) => {
      const existing = prev[effectiveRenderJobId];
      if (existing && !existing.error && !existing.loading) {
        alreadyLoaded = true;
        return prev;
      }
      return {
        ...prev,
        [effectiveRenderJobId]: {
          renderJobId: effectiveRenderJobId,
          index: selectedClipIdx,
          title: "",
          clips: [],
          subtitles: [],
          composition: null,
          downloadUrl: null,
          totalDurationMs: 0,
          loading: true,
          error: null,
          refinementSource: null,
        },
      };
    });
    if (alreadyLoaded) {
      return;
    }

    (async () => {
      try {
        const [comp, job] = await Promise.all([
          getShortComposition(effectiveRenderJobId, getAccessToken),
          getRenderJob(effectiveRenderJobId, getAccessToken),
        ]);
        if (cancelled) return;

        const compositionSpec = comp.composition;
        const sceneClips = extractSceneClips(compositionSpec);
        const compTitle = extractTitle(compositionSpec) ?? job.title ?? "";
        const sourceType = scenesByVideo.source_type ?? "gdrive";

        const editorClips: EditorClip[] = [];
        const subtitles: EditorSubtitle[] = [];
        const sceneById = new Map(scenesByVideo.scenes.map((s) => [s.scene_id, s]));

        for (const sc of sceneClips) {
          const scene = sceneById.get(sc.scene_id);
          if (!scene) continue;
          const clip = createClipFromScene(scene as VideoScene, videoId, sourceType);
          // The composition's ``scene_clips[]`` carries the actual cut
          // window the renderer used (sub-window of the source scene) and
          // its timeline placement. ``createClipFromScene`` defaults
          // trim* to the full scene span, which over-counts whenever the
          // STT / storyboard picker trimmed the scene. Override here so
          // ``totalDurationMs`` (and any downstream readers of trim*)
          // match the rendered MP4's duration.
          if (sc.start_ms !== null && sc.end_ms !== null) {
            clip.trimStartMs = sc.start_ms;
            clip.trimEndMs = sc.end_ms;
          }
          if (sc.timeline_start_ms !== null) {
            clip.timelineStartMs = sc.timeline_start_ms;
          }
          editorClips.push(clip);
        }

        // Prefer the composition's actual ``subtitles[]`` — those are
        // what the renderer used to burn the captions into the MP4,
        // so the editor's panel mirrors what the operator sees in the
        // video preview. Falls back to per-scene
        // ``generateSubtitlesFromTranscript`` only when the
        // composition shipped without subtitles (legacy renders or
        // scenes that lack ``speaker_transcript``).
        const compSubtitles = extractCompositionSubtitles(compositionSpec);
        if (compSubtitles.length > 0) {
          for (const cs of compSubtitles) {
            subtitles.push({
              id: makeSubtitleId(),
              text: cs.text,
              startMs: cs.start_ms,
              endMs: cs.end_ms,
              style: cs.style ?? DEFAULT_SUBTITLE_STYLE,
            });
          }
        } else {
          for (let i = 0; i < sceneClips.length; i++) {
            const scene = sceneById.get(sceneClips[i].scene_id);
            const clip = editorClips[i];
            if (!scene || !clip) continue;
            const subs = generateSubtitlesFromTranscript(
              (scene as VideoScene).speaker_transcript,
              clip,
            );
            subtitles.push(...subs);
          }
        }

        // Mirror ``CompositionSpec.total_duration_ms`` from
        // heimdex-media-contracts: the rendered MP4 holds frames to
        // cover whichever ends latest among scene_clips, subtitles, and
        // overlays. Summing ``(trim_end - trim_start)`` only works when
        // clips are contiguous AND no captions/overlays extend past the
        // last clip — Whisper post-render captions routinely run a few
        // seconds past, which is what made the footer disagree with the
        // <video controls> readout even after start_ms/end_ms were
        // wired through.
        const totalDurationMs = extractTotalDurationMs(compositionSpec);

        setClipStates((prev) => ({
          ...prev,
          [effectiveRenderJobId]: {
            renderJobId: effectiveRenderJobId,
            index: selectedClipIdx,
            title: compTitle,
            clips: editorClips,
            subtitles,
            composition: compositionSpec,
            downloadUrl: job.download_url,
            totalDurationMs,
            loading: false,
            error: null,
            refinementSource: job.refinement_source ?? null,
          },
        }));
      } catch (err) {
        if (cancelled) return;
        setClipStates((prev) => ({
          ...prev,
          [effectiveRenderJobId]: {
            ...(prev[effectiveRenderJobId] ?? ({} as ClipState)),
            renderJobId: effectiveRenderJobId,
            index: selectedClipIdx,
            loading: false,
            error: err instanceof Error ? err.message : "클립을 불러올 수 없습니다.",
          },
        }));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [
    effectiveRenderJobId, scenesByVideo, selectedClipIdx, getAccessToken, videoId,
  ]);

  // Reset playback state when switching clips.
  useEffect(() => {
    setPlayheadMs(0);
    setIsPlaying(false);
    if (videoRef.current) {
      videoRef.current.currentTime = 0;
      videoRef.current.pause();
    }
  }, [selectedClipIdx]);

  // Overlay-mode (.claude/plans/auto-shorts-overlay-mode-2026-05-07.md):
  // when the parent renders before Whisper post-render lands, the
  // composition's ``subtitles[]`` is empty. Poll every 3s up to 60s
  // for cues to arrive — the BE writes them in-place to
  // parent.input_spec.subtitles + flips refinement_source='whisper'.
  // Stops as soon as cues appear OR refinement_source flips.
  // Doesn't run when refinement_source is 'manual_edit' (operator
  // intentionally cleared cues; do not auto-replace) or already
  // populated. Doesn't run on switching clips before the first
  // composition fetch (currentClip null).
  useEffect(() => {
    if (!effectiveRenderJobId) return;
    const clip = clipStates[effectiveRenderJobId];
    if (!clip || clip.loading || clip.error) return;
    if (clip.refinementSource === "manual_edit") return;
    const compSubs = (clip.composition as { subtitles?: unknown[] } | null)
      ?.subtitles;
    if (Array.isArray(compSubs) && compSubs.length > 0) return;

    let cancelled = false;
    const startedAt = Date.now();
    const POLL_MS = 3000;
    const TIMEOUT_MS = 60_000;

    const tick = async () => {
      if (cancelled) return;
      try {
        const [comp, job] = await Promise.all([
          getShortComposition(effectiveRenderJobId, getAccessToken),
          getRenderJob(effectiveRenderJobId, getAccessToken),
        ]);
        if (cancelled) return;
        const subsRaw = (comp.composition as { subtitles?: unknown[] } | null)
          ?.subtitles;
        const arrived = Array.isArray(subsRaw) && subsRaw.length > 0;
        const sourceChanged =
          (job.refinement_source ?? null) !== clip.refinementSource;
        if (arrived || sourceChanged) {
          // Re-derive editor cues + clip state. Mirrors the loadClip
          // effect's mapping from composition → ClipState. We don't
          // re-compute editorClips (timeline) because they don't
          // change on a Whisper write.
          const compositionSpec = comp.composition;
          setClipStates((prev) => {
            const existing = prev[effectiveRenderJobId];
            if (!existing) return prev;
            const newSubs: typeof existing.subtitles = [];
            const compSubtitlesAll = extractCompositionSubtitles(compositionSpec);
            for (const cs of compSubtitlesAll) {
              newSubs.push({
                id: makeSubtitleId(),
                text: cs.text,
                startMs: cs.start_ms,
                endMs: cs.end_ms,
                style: cs.style ?? DEFAULT_SUBTITLE_STYLE,
              });
            }
            return {
              ...prev,
              [effectiveRenderJobId]: {
                ...existing,
                composition: compositionSpec,
                subtitles: newSubs,
                downloadUrl: job.download_url,
                refinementSource: job.refinement_source ?? null,
              },
            };
          });
          return; // stop polling
        }
      } catch {
        // Swallow — operator-visible error here is noise; the next
        // tick will retry. The TIMEOUT_MS cap bounds total badness.
      }
      if (Date.now() - startedAt < TIMEOUT_MS && !cancelled) {
        window.setTimeout(tick, POLL_MS);
      }
    };
    const handle = window.setTimeout(tick, POLL_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(handle);
    };
  }, [effectiveRenderJobId, clipStates, getAccessToken]);

  const currentClip = effectiveRenderJobId ? clipStates[effectiveRenderJobId] : undefined;

  // Adapt the parent's composition.subtitles[] (snake_case JSONB) into
  // the SubtitleEditor's SubtitleEdit shape. The editor owns its own
  // state via useSubtitleEditorState — these are only the *initial*
  // cues at mount + on render-id pivot. Subsequent edits flow through
  // the editor's debounced auto-save (PATCH /subtitles), not back into
  // currentClip.subtitles. The ClipPreview overlay continues to read
  // the snapshot for orientation; that's intentional v1 — the operator
  // sees their edits authoritatively in the editor panel and on the
  // post-rerender MP4.
  const editorCues: SubtitleEdit[] = useMemo(() => {
    const comp = currentClip?.composition;
    if (!comp || typeof comp !== "object") return [];
    const subs = (comp as { subtitles?: unknown }).subtitles;
    if (!Array.isArray(subs)) return [];
    return subs.flatMap((s) => {
      if (typeof s !== "object" || s === null) return [];
      const r = s as Record<string, unknown>;
      const text = typeof r.text === "string" ? r.text : null;
      const startMs = typeof r.start_ms === "number" ? r.start_ms : null;
      const endMs = typeof r.end_ms === "number" ? r.end_ms : null;
      if (text === null || startMs === null || endMs === null) return [];
      const tid = typeof r.template_id === "string" ? r.template_id : null;
      const styleRaw = (typeof r.style === "object" && r.style !== null)
        ? (r.style as Record<string, unknown>)
        : undefined;
      return [{
        text,
        start_ms: startMs,
        end_ms: endMs,
        template_id: tid,
        style: styleRaw,
      }];
    });
  }, [currentClip?.composition]);

  // Live cues for the active clip, populated by SubtitleEditor's
  // ``onCuesChange`` callback. Defaults to ``editorCues`` (which
  // mirrors the parent's input_spec.subtitles at last load time)
  // until the editor reports its first state — keeps the overlay in
  // sync if the operator never touches the editor.
  //
  // In overlay mode the overlay ALWAYS renders these cues — there's
  // no burned-in caption to compete with on the parent MP4 (parent
  // composition_builder emits subtitles=[]). The previous
  // "divergence-gating" logic was needed when the MP4 had captions
  // burned in; it's deleted because the source of truth is now the
  // overlay itself.
  const liveCues: SubtitleEdit[] = effectiveRenderJobId
    ? liveCuesByRender[effectiveRenderJobId] ?? editorCues
    : editorCues;

  const handleCuesChange = useCallback((cues: SubtitleEdit[]) => {
    if (!effectiveRenderJobId) return;
    setLiveCuesByRender((prev) => ({ ...prev, [effectiveRenderJobId]: cues }));
  }, [effectiveRenderJobId]);

  // Cue payload handed to <SubtitleOverlay>. Carries per-cue style
  // through so the preview is WYSIWYG — operator StyleTab edits
  // (font/color/bg/stroke/shadow/position) reflect live. Source-side
  // JSONB was validated against contracts ``SubtitleSpec.style`` on
  // the server (PATCH /api/shorts/render/{id}/subtitles), so the
  // runtime shape is trusted; the cast widens the opaque
  // ``Record<string, unknown>`` SubtitleEdit holds into the typed
  // ``Partial<SubtitleCueStyle>`` the overlay expects. Memoised by
  // reference to keep the overlay's useMemo cheap.
  const overlayCues: SubtitleOverlayCue[] = useMemo(
    () => liveCues.map((c) => ({
      text: c.text,
      start_ms: c.start_ms,
      end_ms: c.end_ms,
      style: c.style as Partial<SubtitleCueStyle> | undefined,
    })),
    [liveCues],
  );

  // Composition canvas dims drive the canvas→rendered pixel scale in
  // <SubtitleOverlay>. Style fields (font_size_px, padding, stroke,
  // shadow offsets) are in canvas pixels and need scaling by
  // (renderedHeight / canvasHeight) so a 40px canvas font shows up at
  // the right size in the smaller preview <video>. When the
  // composition hasn't loaded (or lacks output dims), passes null and
  // the overlay falls back to "rendered is canvas" behavior.
  const canvasDims = useMemo(
    () => extractCanvasDims(currentClip?.composition),
    [currentClip?.composition],
  );

  const onTogglePlay = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) {
      void v.play();
    } else {
      v.pause();
    }
  }, []);

  // Phase A note: when the operator hits "쇼츠 내보내기" the SubtitleEditor's
  // debounced PATCH may be in flight. Server-side /rerender reads the
  // parent's current input_spec, so a half-saved edit may be missed by the
  // immediate /rerender. The race is small (debounce ~500ms; the dropdown
  // submit takes longer than that in practice) and surfaces as "the
  // rendered clip is missing my last sentence" — operator retries. Phase E
  // proposes wiring SubtitleEditor's flushNow up through a ref bridge so
  // export awaits a guaranteed save first.
  const handleExportBatch = useCallback(
    (jobIds: string[]) => {
      void exportBatch.start(jobIds);
    },
    [exportBatch],
  );

  // Reset to the subtitles tab when the operator switches clips so a clip
  // change doesn't leave the user staring at a style draft they applied to
  // a different clip (Q9 in the plan). Also clears the search query — a
  // filter that hid all cues on Clip 1 shouldn't blank-out Clip 2.
  useEffect(() => {
    setActiveTab("subtitles");
    setSubtitleSearchQuery("");
    setStyleDraft(null);
  }, [effectiveRenderJobId]);

  // Whenever the current clip's cues land (or refresh after a PATCH),
  // re-derive the global style from the wire-shape ``editorCues`` (which
  // already mirrors ``composition.subtitles`` 1:1 in snake_case). Editor's
  // internal ``EditorSubtitle`` uses camelCase and would need conversion
  // — using editorCues keeps a single source of truth.
  useEffect(() => {
    if (!currentClip || currentClip.loading) return;
    setStyleDraft(deriveGlobalStyle(editorCues));
  }, [currentClip?.composition, currentClip?.loading, currentClip, editorCues]);

  const handleStyleChange = useCallback(
    (next: SubtitleStyleDraft) => {
      setStyleDraft(next);
      // Push the new style through SubtitleEditor's hook so the same
      // debounced PATCH /subtitles owns the write. The hook's debounce
      // coalesces multiple rapid field tweaks into one PATCH.
      const handle = subtitleEditorRef.current;
      if (!handle) return;
      const currentCues = handle.getCues();
      handle.replaceCuesAndSave(applyGlobalStyleToCues(currentCues, next));
    },
    [],
  );

  const handleApplyStyleToAll = useCallback(() => {
    // From the mixed state — promote whatever the operator was visualising
    // (or the layout default if nothing edited yet) to every cue.
    const handle = subtitleEditorRef.current;
    if (!handle) return;
    const promote = styleDraft ?? makeDefaultStyle();
    const currentCues = handle.getCues();
    handle.replaceCuesAndSave(applyGlobalStyleToCues(currentCues, promote));
    setStyleDraft(promote);
  }, [styleDraft]);

  // Derive the scene-clip list for the current composition so SubtitlesTab
  // can group cues by scene. The composition's ``scene_clips`` is opaque
  // (Record<string, unknown>) — extract just the fields the grouper needs.
  const subtitleSceneClips = useMemo(() => {
    const comp = currentClip?.composition;
    if (!comp || typeof comp !== "object") return undefined;
    const raw = (comp as { scene_clips?: unknown }).scene_clips;
    if (!Array.isArray(raw)) return undefined;
    const out: Array<{
      scene_id: string;
      start_ms: number;
      end_ms: number;
      timeline_start_ms?: number;
    }> = [];
    for (const sc of raw) {
      if (typeof sc !== "object" || sc === null) continue;
      const r = sc as Record<string, unknown>;
      const sceneId = typeof r.scene_id === "string" ? r.scene_id : null;
      const startMs = typeof r.start_ms === "number" ? r.start_ms : null;
      const endMs = typeof r.end_ms === "number" ? r.end_ms : null;
      if (sceneId === null || startMs === null || endMs === null) continue;
      const timelineStart =
        typeof r.timeline_start_ms === "number" ? r.timeline_start_ms : undefined;
      out.push({
        scene_id: sceneId,
        start_ms: startMs,
        end_ms: endMs,
        timeline_start_ms: timelineStart,
      });
    }
    return out;
  }, [currentClip?.composition]);

  if (scanOrder.error) {
    return <ErrorState message={`클립 정보를 불러올 수 없습니다: ${scanOrder.error.message}`} />;
  }
  if (scenesError) {
    return <ErrorState message={`장면 정보를 불러올 수 없습니다: ${scenesError}`} />;
  }
  if (!scanOrder.status || sortedChildren.length === 0) {
    return <LoadingState />;
  }

  return (
    <div className="flex h-screen flex-col bg-gray-50">
      <div className="flex items-center justify-between border-b bg-white px-6 py-3">
        <Link
          href={`/videos/${encodeURIComponent(videoId)}?view=auto-shorts`}
          className="text-sm text-gray-700 hover:text-indigo-600"
          data-testid="edit-clips-back-link"
        >
          ← 뒤로가기
        </Link>
        <InlineWizardBreadcrumb variant="two-step" currentStep={2} />
        <div className="flex items-center gap-2">
          <Link
            href={`/export/shorts/auto/wizard/${videoId}/select-product?length=60&count=5&distribution=single&language=ko&intent=commit`}
            className="rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
          >
            새 쇼츠
          </Link>
          {/*
           * Header export button removed in PR 3 of
           * auto-shorts-subtitle-editor-2026-05-06.md. The render
           * action now lives inside ``<SubtitleEditor>`` as
           * "내 편집으로 다시 렌더링" — placing it next to the cue list
           * makes the cause-and-effect (edit → render) visible.
           */}
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        <div className="flex flex-1 items-center justify-center p-8">
          {currentClip?.loading ? (
            <div className="text-sm text-gray-500">로딩 중...</div>
          ) : currentClip?.error ? (
            <div className="text-sm text-red-700">{currentClip.error}</div>
          ) : currentClip?.downloadUrl ? (
            <ClipPreview
              ref={videoRef}
              src={currentClip.downloadUrl}
              cues={overlayCues}
              playheadMs={playheadMs}
              onPlayheadChange={setPlayheadMs}
              onPlayingChange={setIsPlaying}
              canvasWidth={canvasDims?.width ?? null}
              canvasHeight={canvasDims?.height ?? null}
            />
          ) : (
            <div className="text-sm text-gray-500">렌더 결과가 아직 준비되지 않았습니다.</div>
          )}
        </div>

        <div className="flex w-[420px] flex-col overflow-hidden border-l bg-white">
          <div className="flex items-center justify-between gap-3 border-b border-gray-100 px-4 pt-2">
            <RightPanelTabs activeTab={activeTab} onTabChange={setActiveTab} />
            <ExportShortsButton
              children={sortedChildren}
              activeJobId={effectiveRenderJobId}
              exportState={exportBatch.state}
              onExport={handleExportBatch}
              isRunning={exportBatch.isRunning}
              progressLabel={exportBatch.progressLabel}
              className="shrink-0 pb-2"
            />
          </div>
          <div className="flex-1 overflow-y-auto p-4">
            {/*
              Mount SubtitlesTab as long as we have a clip — but visually
              hide it when on the style tab. Unmounting would lose the
              editor's auto-save state and (worse) drop the
              ``subtitleEditorRef`` the style tab depends on to write
              style updates through the same hook.
             */}
            {effectiveRenderJobId && currentClip && !currentClip.loading ? (
              <div
                className={activeTab === "subtitles" ? "" : "hidden"}
                data-testid="subtitles-tab-shell"
              >
                <SubtitlesTab
                  // Force remount when cues land: useSubtitleEditorState
                  // re-keys on `renderId` only, so a 0 → N transition
                  // (Whisper-driven cue arrival on the parent) wouldn't
                  // otherwise propagate into the editor's internal state.
                  // ``editorCues.length > 0`` partitions the lifecycle
                  // cleanly: empty parent → editor mounted with []; once
                  // cues arrive, editor remounts with full cue list.
                  key={`${effectiveRenderJobId}:${editorCues.length > 0 ? "has" : "empty"}`}
                  ref={subtitleEditorRef}
                  renderId={effectiveRenderJobId}
                  initialCues={editorCues}
                  getToken={getAccessToken}
                  refinementSource={currentClip.refinementSource}
                  onCuesChange={handleCuesChange}
                  searchQuery={subtitleSearchQuery}
                  onSearchQueryChange={setSubtitleSearchQuery}
                  sceneClips={subtitleSceneClips}
                />
              </div>
            ) : (
              <p className="text-xs text-gray-500">로딩 중...</p>
            )}
            {activeTab === "style" ? (
              <StyleTab
                currentStyle={styleDraft}
                onStyleChange={handleStyleChange}
                onApplyToAll={handleApplyStyleToAll}
              />
            ) : null}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-3 border-t bg-white px-6 py-3">
        <button
          type="button"
          onClick={onTogglePlay}
          disabled={!currentClip?.downloadUrl}
          className="rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:bg-gray-400"
        >
          {isPlaying ? "일시정지" : "재생"}
        </button>
        <div className="text-xs text-gray-600">
          {fmtMs(playheadMs)} / {fmtMs(currentClip?.totalDurationMs ?? 0)}
        </div>
        <div className="ml-4 flex gap-2">
          {sortedChildren.map((child, idx) => (
            <button
              type="button"
              key={child.job_id}
              onClick={() => setSelectedClipIdx(idx)}
              className={`rounded px-3 py-1 text-sm ${
                idx === selectedClipIdx
                  ? "bg-indigo-600 text-white"
                  : "border border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
              }`}
            >
              Clip {idx + 1}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ────────────── helpers ──────────────

function fmtMs(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

interface ExtractedSceneClip {
  scene_id: string;
  /** Source-video cut start (sub-window inside the scene). ``null`` only
   * when the composition omitted it — fall back to the full scene span. */
  start_ms: number | null;
  /** Source-video cut end. ``null`` → fall back to the full scene span. */
  end_ms: number | null;
  /** Placement on the composition timeline. ``null`` → keep
   * ``createClipFromScene``'s default of 0. */
  timeline_start_ms: number | null;
}

function extractSceneClips(comp: unknown): ExtractedSceneClip[] {
  if (typeof comp !== "object" || comp === null) return [];
  const sc = (comp as { scene_clips?: unknown }).scene_clips;
  if (!Array.isArray(sc)) return [];
  return sc.flatMap((c) => {
    if (typeof c !== "object" || c === null) return [];
    const r = c as Record<string, unknown>;
    const sceneId = typeof r.scene_id === "string" ? r.scene_id : null;
    if (sceneId === null) return [];
    return [
      {
        scene_id: sceneId,
        start_ms: typeof r.start_ms === "number" ? r.start_ms : null,
        end_ms: typeof r.end_ms === "number" ? r.end_ms : null,
        timeline_start_ms:
          typeof r.timeline_start_ms === "number" ? r.timeline_start_ms : null,
      },
    ];
  });
}

/**
 * Mirror of ``CompositionSpec.total_duration_ms`` from
 * heimdex-media-contracts (``composition/schemas.py``). The rendered
 * MP4 length is the max of:
 *   - last ``scene_clip.timeline_end_ms`` (= timeline_start_ms + (end_ms - start_ms))
 *   - last ``subtitle.end_ms``
 *   - last ``overlay.end_ms``
 * Keep this in lockstep with the contracts property. ``EditorClip``
 * trim fields aren't enough on their own: Whisper post-render captions
 * (and any future overlay that extends past the last cut) push the
 * actual rendered length out.
 */
function extractTotalDurationMs(comp: unknown): number {
  if (typeof comp !== "object" || comp === null) return 0;
  const r = comp as Record<string, unknown>;

  let clipEnd = 0;
  if (Array.isArray(r.scene_clips)) {
    for (const c of r.scene_clips) {
      if (typeof c !== "object" || c === null) continue;
      const cc = c as Record<string, unknown>;
      const tStart = typeof cc.timeline_start_ms === "number" ? cc.timeline_start_ms : 0;
      const sStart = typeof cc.start_ms === "number" ? cc.start_ms : null;
      const sEnd = typeof cc.end_ms === "number" ? cc.end_ms : null;
      if (sStart === null || sEnd === null) continue;
      const tEnd = tStart + (sEnd - sStart);
      if (tEnd > clipEnd) clipEnd = tEnd;
    }
  }

  let subEnd = 0;
  if (Array.isArray(r.subtitles)) {
    for (const s of r.subtitles) {
      if (typeof s !== "object" || s === null) continue;
      const ss = s as Record<string, unknown>;
      const e = typeof ss.end_ms === "number" ? ss.end_ms : 0;
      if (e > subEnd) subEnd = e;
    }
  }

  let ovlEnd = 0;
  if (Array.isArray(r.overlays)) {
    for (const o of r.overlays) {
      if (typeof o !== "object" || o === null) continue;
      const oo = o as Record<string, unknown>;
      const e = typeof oo.end_ms === "number" ? oo.end_ms : 0;
      if (e > ovlEnd) ovlEnd = e;
    }
  }

  return Math.max(clipEnd, subEnd, ovlEnd);
}

function extractTitle(comp: unknown): string | null {
  if (typeof comp !== "object" || comp === null) return null;
  const t = (comp as { title?: unknown }).title;
  return typeof t === "string" ? t : null;
}

interface CompSubtitleShape {
  text: string;
  start_ms: number;
  end_ms: number;
  style?: SubtitleStyle;
}

function extractCompositionSubtitles(comp: unknown): CompSubtitleShape[] {
  if (typeof comp !== "object" || comp === null) return [];
  const subs = (comp as { subtitles?: unknown }).subtitles;
  if (!Array.isArray(subs)) return [];
  const out: CompSubtitleShape[] = [];
  for (const s of subs) {
    if (typeof s !== "object" || s === null) continue;
    const r = s as Record<string, unknown>;
    const text = typeof r.text === "string" ? r.text : null;
    const startMs = typeof r.start_ms === "number" ? r.start_ms : null;
    const endMs = typeof r.end_ms === "number" ? r.end_ms : null;
    if (text === null || startMs === null || endMs === null) continue;
    out.push({
      text,
      start_ms: startMs,
      end_ms: endMs,
      style: undefined,
    });
  }
  return out;
}

/**
 * Pull canvas dims off the composition's ``output`` block. Defaults
 * to null (no dims known) so <SubtitleOverlay> can fall back to its
 * "rendered is canvas" legacy behavior — important for the first
 * paint before the composition has loaded.
 */
function extractCanvasDims(
  comp: unknown,
): { width: number; height: number } | null {
  if (!comp || typeof comp !== "object") return null;
  const output = (comp as { output?: unknown }).output;
  if (!output || typeof output !== "object") return null;
  const w = (output as { width?: unknown }).width;
  const h = (output as { height?: unknown }).height;
  if (typeof w !== "number" || typeof h !== "number") return null;
  if (w <= 0 || h <= 0) return null;
  return { width: w, height: h };
}

function makeSubtitleId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `sub_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

// ────────────── tiny components ──────────────

interface ClipPreviewProps {
  src: string;
  cues: SubtitleOverlayCue[];
  playheadMs: number;
  onPlayheadChange: (ms: number) => void;
  onPlayingChange: (playing: boolean) => void;
  /** Composition canvas dims (output.width/height) — drives the
   * canvas→rendered scale in <SubtitleOverlay>. ``null`` falls the
   * overlay back to "rendered is canvas" (scale=1) for backward
   * compatibility. */
  canvasWidth: number | null;
  canvasHeight: number | null;
}

const ClipPreview = forwardRef<HTMLVideoElement, ClipPreviewProps>(
  function ClipPreview(
    {
      src,
      cues,
      playheadMs,
      onPlayheadChange,
      onPlayingChange,
      canvasWidth,
      canvasHeight,
    },
    ref,
  ) {
    // Capture the rendered video dims so the overlay sizes itself
    // proportionally. ResizeObserver keeps it in sync if the player
    // is resized (window, fullscreen, sidebar collapse).
    const [videoSize, setVideoSize] = useState<{ w: number; h: number }>({
      w: 0, h: 0,
    });
    const localRef = useRef<HTMLVideoElement | null>(null);

    useEffect(() => {
      const el = localRef.current;
      if (!el) return;
      const update = () => setVideoSize({ w: el.clientWidth, h: el.clientHeight });
      update();
      const ro = new ResizeObserver(update);
      ro.observe(el);
      return () => ro.disconnect();
    }, []);

    return (
      <div className="relative aspect-[9/16] h-full max-h-[80vh] overflow-hidden rounded-lg bg-black">
        <video
          ref={(el) => {
            localRef.current = el;
            if (typeof ref === "function") ref(el);
            else if (ref) (ref as React.MutableRefObject<HTMLVideoElement | null>).current = el;
          }}
          src={src}
          className="h-full w-full object-contain"
          controls
          onTimeUpdate={(e) =>
            onPlayheadChange(Math.floor((e.currentTarget.currentTime || 0) * 1000))
          }
          onPlay={() => onPlayingChange(true)}
          onPause={() => onPlayingChange(false)}
        />
        <SubtitleOverlay
          cues={cues}
          currentTimeMs={playheadMs}
          videoWidth={videoSize.w || null}
          videoHeight={videoSize.h || null}
          canvasWidth={canvasWidth}
          canvasHeight={canvasHeight}
        />
      </div>
    );
  },
);

function LoadingState() {
  return (
    <div className="flex h-screen items-center justify-center">
      <div className="h-10 w-10 animate-spin rounded-full border-b-2 border-indigo-500" />
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-2 p-6 text-center">
      <p className="text-sm text-red-700">{message}</p>
    </div>
  );
}
