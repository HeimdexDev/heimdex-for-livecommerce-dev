"use client";

import { useMemo } from "react";

import { SpeakerTranscriptDisplay } from "@/lib/speaker-transcript-display";
import type { AutoClipResponse, ClipMemberResponse, VideoScene } from "@/lib/types";

interface ScriptPanelProps {
  clip: AutoClipResponse | null;
  /**
   * Pre-fetched scenes for this video. Used as a fallback transcript
   * source when ``ClipMemberResponse.transcript`` is undefined (older
   * backend without PR 1's transcript field).
   */
  scenes?: VideoScene[];
}

interface ResolvedTurnSource {
  text: string | null;
  caption: string | null;
}

/**
 * Pick the best display text for one clip member.
 *
 * Priority:
 *   1. ``member.transcript`` (PR 1 — speaker_transcript / transcript_norm
 *       / transcript_raw resolved server-side).
 *   2. The matching scene's ``speaker_transcript`` from
 *      ``getVideoScenes`` (only if member.transcript is undefined and we
 *      have the scene loaded).
 *   3. ``member.scene_caption`` as a last resort.
 *
 * Whitespace-only text collapses to ``null`` so the panel doesn't
 * render empty boxes.
 */
function resolveMemberSource(
  member: ClipMemberResponse,
  sceneById: Map<string, VideoScene>,
): ResolvedTurnSource {
  let text: string | null = null;

  const direct = member.transcript;
  if (direct && direct.trim()) {
    text = direct;
  } else {
    const scene = sceneById.get(member.scene_id);
    const fallback =
      scene?.speaker_transcript ||
      scene?.transcript_raw ||
      null;
    if (fallback && fallback.trim()) {
      text = fallback;
    }
  }

  const captionRaw = member.scene_caption ?? null;
  const caption =
    captionRaw && captionRaw.trim() ? captionRaw : null;

  return { text, caption };
}

/**
 * Render the script for one auto-shorts clip in the right-rail
 * inspector. Concatenates speaker-diarized turns from each member
 * top-to-bottom in clip order. Falls back to scene captions for
 * members with no transcript so the user always sees *something*
 * descriptive about the picked scene.
 */
export function ScriptPanel({ clip, scenes = [] }: ScriptPanelProps) {
  const sceneById = useMemo(() => {
    const m = new Map<string, VideoScene>();
    for (const s of scenes) m.set(s.scene_id, s);
    return m;
  }, [scenes]);

  if (!clip || clip.members.length === 0) {
    return (
      <p className="text-xs text-gray-400">선택된 클립이 없습니다.</p>
    );
  }

  return (
    <div className="space-y-3">
      {clip.members.map((member, idx) => {
        const { text, caption } = resolveMemberSource(member, sceneById);
        return (
          <div key={`${member.scene_id}-${idx}`} className="space-y-1">
            <div className="flex items-center justify-between text-[10px] uppercase tracking-wide text-gray-400">
              <span>장면 {idx + 1}</span>
              <span className="font-mono text-gray-300">
                {formatRange(member.start_ms, member.end_ms)}
              </span>
            </div>
            {text ? (
              <SpeakerTranscriptDisplay
                transcript={text}
                maxVisibleTurns={6}
              />
            ) : caption ? (
              <p className="text-[11px] italic leading-relaxed text-gray-500">
                {caption}
              </p>
            ) : (
              <p className="text-[11px] text-gray-300">
                자막이 감지되지 않았습니다.
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}

function formatRange(startMs: number, endMs: number): string {
  return `${formatMmSs(startMs)} – ${formatMmSs(endMs)}`;
}

function formatMmSs(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}
