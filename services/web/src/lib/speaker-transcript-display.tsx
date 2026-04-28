"use client";

import { useMemo, useState } from "react";

import { parseSpeakerTranscript } from "./speaker-transcript";
import { cn } from "./utils";

/**
 * Shared rendering primitives for speaker-diarized transcripts.
 *
 * Lives in lib/ (not under any feature/) so multiple surfaces can
 * render the same speaker-turn UI without cross-feature imports:
 *  - shorts-editor SceneListPanel (existing consumer)
 *  - shorts-auto inspector script panel (new in PR 3)
 *
 * The parser ``parseSpeakerTranscript`` already lives in
 * ``./speaker-transcript`` and emits ``SpeakerTurn`` objects with
 * full ``SpeakerColor`` triples. This module adds:
 *
 *  - ``dotColorForLabel(label)``: a SOLID-color palette (bg only) for
 *    the small leading dot the editor uses. Distinct from the
 *    ``SpeakerColor`` triple in the parser because the editor wants a
 *    single contrasting dot, not a chip background.
 *  - ``SpeakerTranscriptDisplay``: the visual component that renders
 *    a turn list with dots, timestamps, and an expand/collapse
 *    affordance when the list runs long.
 */

const SPEAKER_DOT_PALETTE: readonly string[] = [
  "bg-red-500",
  "bg-emerald-500",
  "bg-blue-500",
  "bg-amber-500",
  "bg-violet-500",
  "bg-cyan-500",
];

/**
 * Map a single-letter speaker label (A, B, C, ...) to a tailwind dot
 * background class. Wraps with modulo so >6 speakers reuse colors
 * without crashing. Non-letter input falls back to the first slot.
 */
export function dotColorForLabel(label: string): string {
  const idx = label.charCodeAt(0) - "A".charCodeAt(0);
  if (Number.isFinite(idx) && idx >= 0) {
    return SPEAKER_DOT_PALETTE[idx % SPEAKER_DOT_PALETTE.length];
  }
  return SPEAKER_DOT_PALETTE[0];
}

interface SpeakerTranscriptDisplayProps {
  transcript: string;
  /** How many turns to show before "+N개 더보기" appears. Default 3. */
  maxVisibleTurns?: number;
  /**
   * Outer wrapper className. Lets the consumer control vertical
   * rhythm without the component leaking layout opinions.
   */
  className?: string;
}

/**
 * Render a speaker-diarized transcript as a stack of (dot · timestamp ·
 * text) rows. Collapses past ``maxVisibleTurns`` turns until the user
 * clicks the expand button. Returns ``null`` when the transcript
 * contains no parseable turns so callers can chain `||` fallbacks.
 */
export function SpeakerTranscriptDisplay({
  transcript,
  maxVisibleTurns = 3,
  className,
}: SpeakerTranscriptDisplayProps) {
  const [expanded, setExpanded] = useState(false);
  const turns = useMemo(() => parseSpeakerTranscript(transcript), [transcript]);

  if (turns.length === 0) return null;

  const visible = expanded ? turns : turns.slice(0, maxVisibleTurns);
  const hasMore = turns.length > maxVisibleTurns;

  return (
    <div className={cn("space-y-1", className)}>
      {visible.map((turn, i) => (
        <div key={i} className="flex items-start gap-1.5">
          <span
            aria-label={`speaker ${turn.label}`}
            className={cn(
              "mt-1 inline-block h-2 w-2 shrink-0 rounded-full",
              dotColorForLabel(turn.label),
            )}
          />
          {turn.timestamp && (
            <span className="shrink-0 pt-0.5 font-mono text-[9px] leading-tight text-gray-400">
              {turn.timestamp}
            </span>
          )}
          <p className="line-clamp-2 text-[11px] leading-tight text-gray-600">
            {turn.text}
          </p>
        </div>
      ))}
      {hasMore && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setExpanded(!expanded);
          }}
          className="text-[10px] font-medium text-indigo-500 hover:text-indigo-700"
        >
          {expanded ? "접기" : `+${turns.length - maxVisibleTurns}개 더보기`}
        </button>
      )}
    </div>
  );
}
