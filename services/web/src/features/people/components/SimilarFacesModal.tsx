"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AvatarThumbnail } from "@/components/people/AvatarThumbnail";
import { cn } from "@/lib/utils";
import { getSimilarPeople } from "@/lib/api/people";
import type {
  MergePersonRequest,
  MergePersonResponse,
  PersonResponse,
  SimilarPersonItem,
} from "@/lib/types";

interface SimilarFacesModalProps {
  targetPerson: PersonResponse;
  people: PersonResponse[];
  onClose: () => void;
  onMerge: (request: MergePersonRequest) => Promise<MergePersonResponse | null>;
  isMerging: boolean;
  getAccessToken: () => Promise<string | null>;
}

type LabelChoice = "target" | "custom";

// Cache similar results across modal opens within the same session
const similarCache = new Map<string, SimilarPersonItem[]>();

export function SimilarFacesModal({
  targetPerson,
  people,
  onClose,
  onMerge,
  isMerging,
  getAccessToken,
}: SimilarFacesModalProps) {
  const [similarItems, setSimilarItems] = useState<SimilarPersonItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [labelChoice, setLabelChoice] = useState<LabelChoice>("target");
  const [customLabel, setCustomLabel] = useState("");
  const fetchedRef = useRef(false);

  const peopleMap = useMemo(
    () => new Map(people.map((p) => [p.person_cluster_id, p])),
    [people],
  );

  useEffect(() => {
    if (fetchedRef.current) return;
    fetchedRef.current = true;

    const cached = similarCache.get(targetPerson.person_cluster_id);
    if (cached) {
      setSimilarItems(cached);
      setIsLoading(false);
      return;
    }

    getSimilarPeople(targetPerson.person_cluster_id, getAccessToken)
      .then((response) => {
        setSimilarItems(response.similarities);
        similarCache.set(targetPerson.person_cluster_id, response.similarities);
      })
      .catch(() => {
        setError("유사한 인물을 불러오지 못했습니다.");
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, [targetPerson.person_cluster_id, getAccessToken]);

  const toggleSelection = useCallback((clusterId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(clusterId)) {
        next.delete(clusterId);
      } else {
        next.add(clusterId);
      }
      return next;
    });
  }, []);

  const toggleAll = useCallback(() => {
    setSelectedIds((prev) => {
      if (prev.size === similarItems.length) {
        return new Set();
      }
      return new Set(similarItems.map((item) => item.person_cluster_id));
    });
  }, [similarItems]);

  const anySourceHasLabel = useMemo(
    () =>
      Array.from(selectedIds).some((id) => {
        const person = peopleMap.get(id);
        return person?.label;
      }),
    [selectedIds, peopleMap],
  );

  const showLabelChoice = anySourceHasLabel || !!targetPerson.label;

  const handleMerge = async () => {
    const sourceIds = Array.from(selectedIds);
    if (sourceIds.length === 0) return;

    let keepLabel: string | null | undefined;
    if (showLabelChoice) {
      keepLabel =
        labelChoice === "custom"
          ? customLabel.trim() || null
          : targetPerson.label;
    }

    const result = await onMerge({
      source_cluster_ids: sourceIds,
      target_cluster_id: targetPerson.person_cluster_id,
      keep_label: keepLabel,
    });

    if (result) {
      // Invalidate cache for the target since centroids changed
      similarCache.delete(targetPerson.person_cluster_id);
      onClose();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape" && !isMerging) onClose();
  };

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center"
      onKeyDown={handleKeyDown}
    >
      <div
        className="absolute inset-0 bg-black/40"
        onClick={isMerging ? undefined : onClose}
        role="button"
        tabIndex={-1}
        aria-label="닫기"
      />

      <div className="relative flex max-h-[80vh] w-[560px] flex-col rounded-xl bg-white shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b px-6 py-4">
          <div>
            <h2 className="text-lg font-bold text-gray-900">
              유사한 인물 찾기
            </h2>
            <p className="mt-0.5 text-sm text-gray-500">
              {targetPerson.label || "이름 없음"}과(와) 비슷한 인물
              {!isLoading && ` ${similarItems.length}명`}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isMerging}
            className="rounded-lg p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 disabled:opacity-50"
            aria-label="닫기"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {isLoading && (
            <div className="grid grid-cols-4 gap-3">
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="flex flex-col items-center gap-2">
                  <div className="h-20 w-20 animate-pulse rounded-2xl bg-gray-200" />
                  <div className="h-3 w-12 animate-pulse rounded bg-gray-200" />
                </div>
              ))}
            </div>
          )}

          {error && (
            <div className="py-8 text-center text-sm text-red-500">{error}</div>
          )}

          {!isLoading && !error && similarItems.length === 0 && (
            <div className="py-8 text-center text-sm text-gray-500">
              유사한 인물이 없습니다
            </div>
          )}

          {!isLoading && !error && similarItems.length > 0 && (
            <>
              <div className="mb-3 flex items-center justify-between">
                <button
                  type="button"
                  onClick={toggleAll}
                  disabled={isMerging}
                  className="text-xs font-medium text-indigo-500 hover:text-indigo-600 disabled:opacity-50"
                >
                  {selectedIds.size === similarItems.length
                    ? "전체 해제"
                    : "전체 선택"}
                </button>
                {selectedIds.size > 0 && (
                  <span className="text-xs text-gray-500">
                    {selectedIds.size}명 선택됨
                  </span>
                )}
              </div>

              <div className="grid grid-cols-4 gap-3">
                {similarItems.map((item) => {
                  const person = peopleMap.get(item.person_cluster_id);
                  const isSelected = selectedIds.has(item.person_cluster_id);
                  const similarityPct = Math.round(item.similarity * 100);

                  return (
                    <button
                      key={item.person_cluster_id}
                      type="button"
                      onClick={() => toggleSelection(item.person_cluster_id)}
                      disabled={isMerging}
                      className={cn(
                        "group relative flex flex-col items-center gap-1.5 rounded-xl p-2 transition-all",
                        isSelected
                          ? "bg-indigo-50 ring-2 ring-indigo-500"
                          : "hover:bg-gray-50",
                        isMerging && "opacity-50",
                      )}
                    >
                      {/* Similarity badge */}
                      <span
                        className={cn(
                          "absolute -right-1 -top-1 z-10 rounded-full px-1.5 py-0.5 text-[10px] font-bold leading-tight",
                          similarityPct >= 80
                            ? "bg-green-100 text-green-700"
                            : similarityPct >= 60
                              ? "bg-yellow-100 text-yellow-700"
                              : "bg-gray-100 text-gray-600",
                        )}
                      >
                        {similarityPct}%
                      </span>

                      {/* Checkbox indicator */}
                      <div
                        className={cn(
                          "absolute left-1 top-1 z-10 flex h-4 w-4 items-center justify-center rounded border",
                          isSelected
                            ? "border-indigo-500 bg-indigo-500"
                            : "border-gray-300 bg-white",
                        )}
                      >
                        {isSelected && (
                          <svg className="h-3 w-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                          </svg>
                        )}
                      </div>

                      {person ? (
                        <AvatarThumbnail
                          person={person}
                          agentAvailable={true}
                          className="h-20 w-20"
                        />
                      ) : (
                        <div className="flex h-20 w-20 items-center justify-center rounded-2xl bg-gray-100">
                          <span className="text-xs text-gray-400">?</span>
                        </div>
                      )}

                      <span className="max-w-[80px] truncate text-xs text-gray-600">
                        {person?.label || "이름 없음"}
                      </span>
                      <span className="text-[10px] text-gray-400">
                        출연 {person?.face_count ?? 0}
                      </span>
                    </button>
                  );
                })}
              </div>
            </>
          )}
        </div>

        {/* Footer with label resolution + merge button */}
        {selectedIds.size > 0 && (
          <div className="border-t px-6 py-4">
            {showLabelChoice && (
              <div className="mb-3">
                <p className="mb-2 text-xs font-medium text-gray-700">
                  병합 후 이름
                </p>
                <div className="flex flex-wrap gap-3">
                  <label className="flex items-center gap-1.5 text-sm">
                    <input
                      type="radio"
                      name="similar-label-choice"
                      checked={labelChoice === "target"}
                      onChange={() => setLabelChoice("target")}
                      disabled={isMerging}
                      className="accent-indigo-500"
                    />
                    <span className="text-gray-700">
                      {targetPerson.label || "이름 없음"}
                    </span>
                  </label>
                  <label className="flex items-center gap-1.5 text-sm">
                    <input
                      type="radio"
                      name="similar-label-choice"
                      checked={labelChoice === "custom"}
                      onChange={() => setLabelChoice("custom")}
                      disabled={isMerging}
                      className="accent-indigo-500"
                    />
                    <span className="text-gray-700">직접 입력</span>
                  </label>
                </div>
                {labelChoice === "custom" && (
                  <input
                    type="text"
                    value={customLabel}
                    onChange={(e) => setCustomLabel(e.target.value)}
                    disabled={isMerging}
                    maxLength={100}
                    placeholder="이름 입력..."
                    className="mt-2 w-full rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                  />
                )}
              </div>
            )}

            <div className="flex items-center justify-between">
              <p className="text-xs text-gray-500">
                {selectedIds.size}명을 {targetPerson.label || "이름 없음"}에 병합
              </p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={onClose}
                  disabled={isMerging}
                  className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                >
                  취소
                </button>
                <button
                  type="button"
                  onClick={handleMerge}
                  disabled={isMerging || selectedIds.size === 0}
                  className="rounded-lg bg-indigo-500 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-600 disabled:opacity-50"
                >
                  {isMerging ? (
                    <span className="flex items-center gap-2">
                      <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                      병합 중...
                    </span>
                  ) : (
                    "병합하기"
                  )}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
