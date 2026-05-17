"use client";

interface StopConfirmDialogProps {
  isOpen: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export function StopConfirmDialog({
  isOpen,
  onCancel,
  onConfirm,
}: StopConfirmDialogProps) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/40"
        onClick={onCancel}
        onKeyDown={(e) => {
          if (e.key === "Escape") onCancel();
        }}
        role="button"
        tabIndex={-1}
        aria-label="닫기"
      />

      <div className="relative w-[360px] rounded-xl bg-white p-6 shadow-xl">
        <h2 className="text-lg font-bold text-gray-900">
          업로드를 중단할까요?
        </h2>
        <p className="mt-2 text-sm text-gray-600">
          업로드를 중단하면 진행 중인 업로드가 취소됩니다.
        </p>

        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-gray-300 px-6 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
          >
            취소
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="rounded-lg bg-red-500 px-6 py-2 text-sm font-medium text-white transition-colors hover:bg-red-600"
          >
            중단
          </button>
        </div>
      </div>
    </div>
  );
}
