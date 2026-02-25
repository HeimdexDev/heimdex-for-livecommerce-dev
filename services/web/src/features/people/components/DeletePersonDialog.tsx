"use client";

interface DeletePersonDialogProps {
  isOpen: boolean;
  personLabel: string | null;
  isDeleting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export function DeletePersonDialog({
  isOpen,
  personLabel,
  isDeleting,
  onCancel,
  onConfirm,
}: DeletePersonDialogProps) {
  if (!isOpen) return null;

  const displayName = personLabel || "이 인물";

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/40"
        onClick={isDeleting ? undefined : onCancel}
        onKeyDown={(e) => {
          if (e.key === "Escape" && !isDeleting) onCancel();
        }}
        role="button"
        tabIndex={-1}
        aria-label="닫기"
      />

      <div className="relative w-[360px] rounded-xl bg-white p-6 shadow-xl">
        <h2 className="text-lg font-bold text-gray-900">
          인물을 삭제할까요?
        </h2>
        <p className="mt-2 text-sm text-gray-600">
          <span className="font-medium text-gray-900">{displayName}</span>의
          모든 데이터가 영구적으로 삭제됩니다. 이 작업은 되돌릴 수 없습니다.
        </p>

        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={isDeleting}
            className="rounded-lg border border-gray-300 px-6 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-50"
          >
            취소
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isDeleting}
            className="rounded-lg bg-red-500 px-6 py-2 text-sm font-medium text-white transition-colors hover:bg-red-600 disabled:opacity-50"
          >
            {isDeleting ? (
              <span className="flex items-center gap-2">
                <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                삭제 중...
              </span>
            ) : (
              "삭제"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
