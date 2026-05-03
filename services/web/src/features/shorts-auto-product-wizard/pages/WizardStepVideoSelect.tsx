// ============================================================================
// Step 1 — 동영상 선택
//
// **Skeleton scope (PR #7):** a minimal text input for the user to paste
// or type a video ID, then advance to step 2. The full video-library
// search/list UI is a follow-up — wraps the existing video search
// pattern via lib/api/search, but threading that through is its own
// PR's worth of UX.
// ============================================================================

"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { WizardLayout } from "../components/WizardLayout";

export function WizardStepVideoSelect() {
  const router = useRouter();
  const [videoId, setVideoId] = useState("");

  const trimmed = videoId.trim();
  const canProceed = trimmed.length > 0;

  const handleNext = () => {
    if (!canProceed) return;
    router.push(
      `/export/shorts/auto/wizard/${encodeURIComponent(trimmed)}/criteria`,
    );
  };

  return (
    <WizardLayout
      currentStep={1}
      heading="동영상을 선택하고 '다음'버튼을 클릭하세요"
      next={{ label: "다음 >", onClick: handleNext, disabled: !canProceed }}
      backHref="/export/shorts/auto"
    >
      <div className="space-y-3 rounded-lg border border-gray-200 bg-white p-6">
        <p className="text-sm text-gray-600">
          쇼츠를 만들 동영상의 ID를 입력하세요. 예: <code>gd_abc123</code>
        </p>
        <input
          type="text"
          value={videoId}
          onChange={(e) => setVideoId(e.target.value)}
          placeholder="gd_..."
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
          data-testid="video-id-input"
        />
        <p className="text-xs text-gray-500">
          향후 PR에서 동영상 라이브러리 검색 UI로 대체됩니다.
        </p>
      </div>
    </WizardLayout>
  );
}
