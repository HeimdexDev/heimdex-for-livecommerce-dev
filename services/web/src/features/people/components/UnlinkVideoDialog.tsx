"use client";

interface UnlinkVideoDialogProps {
  isOpen: boolean;
  personLabel: string | null;
  videoTitle: string | null;
  isUnlinking: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export function UnlinkVideoDialog({
  isOpen,
  personLabel,
  videoTitle,
  isUnlinking,
  onCancel,
  onConfirm,
}: UnlinkVideoDialogProps) {
  if (!isOpen) return null;

  const displayPerson = personLabel || "이 인물";
  const displayVideo = videoTitle || "이 동영상";

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/40"
        onClick={isUnlinking ? undefined : onCancel}
        onKeyDown={(e) => {
          if (e.key === "Escape" && !isUnlinking) onCancel();
        }}
        role="button"
        tabIndex={-1}
        aria-label="닫기"
      />

      <div className="relative w-[400px] rounded-xl bg-white p-6 shadow-xl">
        <h2 className="text-lg font-bold text-gray-900">
          동영상에서 연결 해제
        </h2>
        <p className="mt-2 text-sm text-gray-600">
          <span className="font-medium text-gray-900">{displayVideo}</span>의
          모든 장면에서{" "}
          <span className="font-medium text-gray-900">{displayPerson}</span>
          을(를) 제거하시겠습니까?
        </p>
        <p className="mt-1 text-xs text-gray-400">
          이 작업은 되돌릴 수 있습니다. (다시 연결 가능)
        </p>

        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={isUnlinking}
            className="rounded-lg border border-gray-300 px-6 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-50"
          >
            취소
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isUnlinking}
            className="rounded-lg bg-red-500 px-6 py-2 text-sm font-medium text-white transition-colors hover:bg-red-600 disabled:opacity-50"
          >
            {isUnlinking ? (
              <span className="flex items-center gap-2">
                <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                해제 중...
              </span>
            ) : (
              "연결 해제"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
