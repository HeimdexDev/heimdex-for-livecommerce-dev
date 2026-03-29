"use client";

import { useState } from "react";
import { ReprocessParams } from "@/lib/types";
import { cn } from "@/lib/utils";

interface ReprocessDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (params: ReprocessParams) => Promise<void>;
}

export function ReprocessDialog({ isOpen, onClose, onSubmit }: ReprocessDialogProps) {
  const [minDuration, setMinDuration] = useState(0.5);
  const [maxDuration, setMaxDuration] = useState(45);
  const [threshold, setThreshold] = useState(0.3);
  const [splitPreset, setSplitPreset] = useState("default");
  const [useSpeech, setUseSpeech] = useState(true);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isOpen) return null;

  const isValid = minDuration < maxDuration;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isValid) return;

    setIsSubmitting(true);
    try {
      await onSubmit({
        min_scene_duration_ms: minDuration * 1000,
        max_scene_duration_ms: maxDuration * 1000,
        threshold,
        split_preset: splitPreset,
        use_speech: useSpeech,
      });
      onClose();
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md rounded-xl bg-white shadow-xl">
        <div className="border-b border-gray-100 px-6 py-4">
          <h2 className="text-lg font-bold text-gray-900">장면 재분석</h2>
        </div>

        <form onSubmit={handleSubmit} className="p-6">
          <p className="mb-6 text-sm text-gray-600">
            비디오의 장면 분할을 다시 실행합니다. 기존 장면 데이터(자막, 캡션, OCR 등)는 삭제되고 새로운 장면이 생성됩니다.
          </p>

          <div className="space-y-6">
            <div>
              <label className="mb-2 block text-sm font-medium text-gray-700">장면 분할 방식</label>
              <select
                value={splitPreset}
                onChange={(e) => setSplitPreset(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              >
                <option value="default">기본 (균형)</option>
                <option value="fine">세밀 (검색 최적화)</option>
                <option value="coarse">넓은 (주제 단위)</option>
                <option value="visual_only">영상 컷 기준</option>
              </select>
            </div>

            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="use-speech"
                checked={useSpeech && splitPreset !== "visual_only"}
                disabled={splitPreset === "visual_only"}
                onChange={(e) => setUseSpeech(e.target.checked)}
                className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
              />
              <label htmlFor="use-speech" className="text-sm text-gray-700">
                음성 데이터 활용 (STT 결과가 있는 경우)
              </label>
            </div>

            <div>
              <div className="mb-2 flex items-center justify-between">
                <label className="text-sm font-medium text-gray-700">최소 장면 길이</label>
                <span className="text-sm text-gray-500">{minDuration.toFixed(1)}초</span>
              </div>
              <input
                type="range"
                min="0.5"
                max="30"
                step="0.5"
                value={minDuration}
                onChange={(e) => setMinDuration(Number(e.target.value))}
                className="w-full accent-indigo-600"
              />
            </div>

            <div>
              <div className="mb-2 flex items-center justify-between">
                <label className="text-sm font-medium text-gray-700">최대 장면 길이</label>
                <span className="text-sm text-gray-500">{maxDuration}초</span>
              </div>
              <input
                type="range"
                min="5"
                max="120"
                step="1"
                value={maxDuration}
                onChange={(e) => setMaxDuration(Number(e.target.value))}
                className="w-full accent-indigo-600"
              />
            </div>

            {!isValid && (
              <p className="text-sm text-red-500">최소 장면 길이는 최대 장면 길이보다 작아야 합니다.</p>
            )}

            <div className="border-t border-gray-100 pt-4">
              <button
                type="button"
                onClick={() => setShowAdvanced(!showAdvanced)}
                className="flex w-full items-center justify-between text-sm font-medium text-gray-700"
              >
                고급 설정
                <svg
                  className={cn("h-4 w-4 transition-transform", showAdvanced ? "rotate-180" : "")}
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {showAdvanced && (
                <div className="mt-4">
                  <div className="mb-2 flex items-center justify-between">
                    <label className="text-sm font-medium text-gray-700">감도</label>
                    <span className="text-sm text-gray-500">{threshold.toFixed(2)}</span>
                  </div>
                  <input
                    type="range"
                    min="0.1"
                    max="0.9"
                    step="0.05"
                    value={threshold}
                    onChange={(e) => setThreshold(Number(e.target.value))}
                    className="w-full accent-indigo-600"
                  />
                  <p className="mt-1 text-xs text-gray-500">낮을수록 더 많은 장면이 감지됩니다</p>
                </div>
              )}
            </div>
          </div>

          <div className="mt-8 flex justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              취소
            </button>
            <button
              type="submit"
              disabled={!isValid || isSubmitting}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {isSubmitting ? "처리 중..." : "재분석 시작"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
