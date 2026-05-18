// ============================================================================
// Inline-wizard container — orchestrates the criteria ↔ select-product step
// transition on the video detail page. Owns:
//   * step state ("criteria" | "select-product")
//   * criteria draft state (preserved across back-nav, unlike the legacy
//     route-based wizard which loses it)
//
// Routes the user to the existing result page once the scan order is
// created — Step 3 is intentionally OUT of scope for this container per
// Decision #6.
//
// The parent (VideoDetailPage) is told about step transitions via
// ``onStepChange`` so it can hide the left video panel on step 2 per
// Decision #5.
// ============================================================================

"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import {
  DEFAULT_CRITERIA,
  InlineWizardCriteriaPanel,
  type WizardCriteriaDraft,
} from "./InlineWizardCriteriaPanel";
import { InlineWizardProductPanel } from "./InlineWizardProductPanel";

export type InlineWizardStep = "criteria" | "select-product";

interface Props {
  videoId: string;
  videoDurationMs: number;
  /**
   * Optional scene boundaries (ms) the range slider snaps to. Pass the
   * union of scene start_ms + end_ms from the detail page. Empty /
   * undefined disables snap (free dragging).
   */
  snapTargetsMs?: number[];
  /**
   * Fires every time the inner step changes. Parent uses this to decide
   * whether to render the left-side video panel (criteria step) or
   * collapse to full-width (select-product step).
   */
  onStepChange?: (step: InlineWizardStep) => void;
}

export function InlineWizardContainer({
  videoId,
  videoDurationMs,
  snapTargetsMs,
  onStepChange,
}: Props) {
  const router = useRouter();
  const [step, setStep] = useState<InlineWizardStep>("criteria");
  const [criteria, setCriteria] =
    useState<WizardCriteriaDraft>(DEFAULT_CRITERIA);

  const advanceTo = (next: InlineWizardStep) => {
    setStep(next);
    onStepChange?.(next);
  };

  if (step === "criteria") {
    return (
      <InlineWizardCriteriaPanel
        videoId={videoId}
        videoDurationMs={videoDurationMs}
        snapTargetsMs={snapTargetsMs}
        criteria={criteria}
        onCriteriaChange={setCriteria}
        onNext={() => advanceTo("select-product")}
      />
    );
  }

  return (
    <InlineWizardProductPanel
      videoId={videoId}
      videoDurationMs={videoDurationMs}
      criteria={criteria}
      onSubmitOrder={(parentJobId) => {
        // Result step stays at the legacy route per Decision #6 — once
        // it gets the inline treatment in a follow-up PR, this push
        // becomes a setStep("result") instead.
        router.push(
          `/export/shorts/auto/wizard/${encodeURIComponent(videoId)}/result/${encodeURIComponent(parentJobId)}`,
        );
      }}
      onBack={() => advanceTo("criteria")}
    />
  );
}
