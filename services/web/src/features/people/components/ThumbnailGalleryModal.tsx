"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getExemplars, selectThumbnailFromExemplar, uploadCustomThumbnail, resetThumbnail } from "@/lib/api/people";
import type { ExemplarResponse } from "@/lib/types";

interface ThumbnailGalleryModalProps {
  isOpen: boolean;
  personClusterId: string;
  personLabel: string | null;
  thumbnailSource: string;
  getToken?: () => Promise<string | null>;
  onClose: () => void;
  onThumbnailChanged: () => void;
}

export function ThumbnailGalleryModal({
  isOpen,
  personClusterId,
  personLabel,
  thumbnailSource,
  getToken,
  onClose,
  onThumbnailChanged,
}: ThumbnailGalleryModalProps) {
  const [availableExemplars, setAvailableExemplars] = useState<ExemplarResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    setLoading(true);
    setError(null);
    getExemplars(personClusterId, getToken)
      .then(async (res) => {
        // With S3-primary storage, exemplars returned by the API are
        // guaranteed to exist — no need for a HEAD availability check
        // (the old HEAD check returned 405 on the exemplar GET-only route).
        setAvailableExemplars(res.exemplars);
      })
      .catch(() => setError("갤러리를 불러올 수 없습니다"))
      .finally(() => setLoading(false));
  }, [isOpen, personClusterId, getToken]);

  const handleSelectExemplar = useCallback(async (exemplarId: string) => {
    setSubmitting(true);
    setError(null);
    try {
      await selectThumbnailFromExemplar(personClusterId, exemplarId, getToken);
      onThumbnailChanged();
      onClose();
    } catch {
      setError("썸네일 선택에 실패했습니다");
    } finally {
      setSubmitting(false);
    }
  }, [personClusterId, getToken, onThumbnailChanged, onClose]);

  const handleUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setSubmitting(true);
    setError(null);
    try {
      await uploadCustomThumbnail(personClusterId, file, getToken);
      onThumbnailChanged();
      onClose();
    } catch {
      setError("이미지 업로드에 실패했습니다. 5MB 이하의 JPEG/PNG/WebP 파일만 가능합니다.");
    } finally {
      setSubmitting(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }, [personClusterId, getToken, onThumbnailChanged, onClose]);

  const handleReset = useCallback(async () => {
    setSubmitting(true);
    setError(null);
    try {
      await resetThumbnail(personClusterId, getToken);
      onThumbnailChanged();
      onClose();
    } catch {
      setError("초기화에 실패했습니다");
    } finally {
      setSubmitting(false);
    }
  }, [personClusterId, getToken, onThumbnailChanged, onClose]);

  if (!isOpen) return null;

  const displayName = personLabel || "인물";

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/40"
        onClick={submitting ? undefined : onClose}
        onKeyDown={(e) => { if (e.key === "Escape" && !submitting) onClose(); }}
        role="button"
        tabIndex={-1}
        aria-label="닫기"
      />

      <div className="relative w-[480px] max-h-[80vh] overflow-y-auto rounded-xl bg-white p-6 shadow-xl">
        <h2 className="text-lg font-bold text-gray-900">
          {displayName} 프로필 사진
        </h2>
        <p className="mt-1 text-sm text-gray-500">
          갤러리에서 선택하거나 직접 업로드하세요
        </p>

        {error && (
          <div className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-600">{error}</div>
        )}

        {loading ? (
          <div className="mt-6 flex items-center justify-center py-12">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-indigo-500 border-t-transparent" />
          </div>
        ) : availableExemplars.length > 0 ? (
          <div className="mt-4 grid grid-cols-4 gap-2">
            {availableExemplars.map((e) => (
              <button
                key={e.exemplar_id}
                type="button"
                disabled={submitting}
                onClick={() => handleSelectExemplar(e.exemplar_id)}
                className="group relative overflow-hidden rounded-xl border-2 border-transparent transition-all hover:border-indigo-400 disabled:opacity-50 aspect-square"
              >
                <img
                  src={e.thumbnail_url}
                  alt={`${displayName} 얼굴`}
                  className="h-full w-full object-cover"
                />
                <div className="absolute inset-0 bg-black/0 transition-all group-hover:bg-black/10" />
              </button>
            ))}
          </div>
        ) : (
          <div className="mt-6 py-8 text-center text-sm text-gray-400">
            갤러리에 사용 가능한 얼굴이 없습니다. 새 영상을 처리하면 갤러리가 채워집니다.
          </div>
        )}

        <div className="mt-4 border-t border-gray-100 pt-4">
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            onChange={handleUpload}
            className="hidden"
          />
          <div className="flex items-center gap-3">
            <button
              type="button"
              disabled={submitting}
              onClick={() => fileInputRef.current?.click()}
              className="flex-1 rounded-lg border border-gray-300 px-4 py-2.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-50"
            >
              이미지 업로드
            </button>
            {thumbnailSource !== "auto" && (
              <button
                type="button"
                disabled={submitting}
                onClick={handleReset}
                className="rounded-lg border border-gray-300 px-4 py-2.5 text-sm font-medium text-gray-500 transition-colors hover:bg-gray-50 disabled:opacity-50"
              >
                자동 선택으로 되돌리기
              </button>
            )}
          </div>
        </div>

        <div className="mt-4 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded-lg border border-gray-300 px-6 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-50"
          >
            닫기
          </button>
        </div>
      </div>
    </div>
  );
}
