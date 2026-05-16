// figma: 1713:288121,1713:288122,1713:288123  (cache: .figma-cache/1713-288103_phase2_wizard-indexing.api.json)
// node-name: Frame 1707484873/4/5 · spec: w=31 h=4 bg=heimdex-navy-500 | neutral-h-50
//
// Connector dash between two adjacent indexing stage pills (Figma node
// 1713:288103). One <StageConnectorDots /> instance represents a single
// 31×4 dash drawn between pill[i] and pill[i+1]. Color follows the
// LEFT (preceding) pill's state per the Figma cache:
//
//   completed (heimdex-navy-500 #234c77) — the preceding stage finished
//   otherwise (neutral-h-50 #f5f5f5)     — pending/active/queued
//
// The 31×4 dimensions come directly from the Figma spec, kept on this
// dedicated component rather than introduced as ad-hoc utility tokens.

"use client";

import { cn } from "@/lib/utils";

interface Props {
  /**
   * State of the LEFT pill in the pair this dash connects.
   * - "completed" → navy 500
   * - anything else → neutral-50 (queued look)
   */
  precedingState: "completed" | "active" | "queued";
  className?: string;
}

export function StageConnectorDots({ precedingState, className }: Props) {
  const isCompleted = precedingState === "completed";
  return (
    <span
      aria-hidden="true"
      data-testid="indexing-stage-connector"
      data-state={precedingState}
      className={cn(
        // h-1 = 0.25rem = 4px (Tailwind default utility, no arbitrary value).
        // w-[31px] reuses an existing arbitrary already in codebase (HeimdexSymbol).
        "inline-block h-1 w-[31px] shrink-0 rounded-full",
        isCompleted ? "bg-heimdex-navy-500" : "bg-neutral-h-50",
        className,
      )}
    />
  );
}
