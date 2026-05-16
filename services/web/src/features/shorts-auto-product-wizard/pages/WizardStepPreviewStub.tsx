// ============================================================================
// Step 3 — 쇼츠 가편집본 (preview stub)
//
// **Phase 6 deliverable.** The preview step runs a SigLIP2-only retrieval
// pass (no SAM2) so the user can iterate on criteria without burning GPU.
// Phase 4 ships the wizard with a stub here — the criteria step submits
// with ``intent='commit'`` and skips this screen entirely. This page is
// a placeholder so the route shape is locked even though the surface
// isn't functional yet.
//
// Backend has the matching shape: ``POST /scan-orders/{id}/commit``
// returns 501 today (plan §11.1).
// ============================================================================

"use client";

import { WizardLayout } from "../components/WizardLayout";

interface Props {
  videoId: string;
}

export function WizardStepPreviewStub({ videoId }: Props) {
  return (
    <WizardLayout
      currentStep={3}
      heading="쇼츠 가편집본 미리보기 (Phase 6에서 구현)"
      next={null}
      backHref={`/export/shorts/auto/wizard/${encodeURIComponent(videoId)}/criteria`}
    >
      <div className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-6">
        <h2 className="text-lg font-semibold text-amber-900">
          가편집본 미리보기는 곧 출시됩니다
        </h2>
        <p className="text-sm text-amber-800">
          Phase 6에서 SigLIP2 기반 가편집 미리보기를 추가할 예정입니다.
          그 전까지는 2단계의 '다음 &gt;' 버튼을 누르면 4단계로 바로
          이동합니다.
        </p>
      </div>
    </WizardLayout>
  );
}
