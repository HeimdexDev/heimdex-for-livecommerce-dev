"use client";

interface DisableFolderConfirmDialogProps {
  isOpen: boolean;
  folderName: string | null;
  videoCount: number;
  imageCount: number;
  isLoading: boolean;
  isDisabling: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export function DisableFolderConfirmDialog({
  isOpen,
  folderName,
  videoCount,
  imageCount,
  isLoading,
  isDisabling,
  onCancel,
  onConfirm,
}: DisableFolderConfirmDialogProps) {
  if (!isOpen) return null;

  const displayName = folderName || "이 폴더";

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/40"
        onClick={isDisabling ? undefined : onCancel}
        onKeyDown={(e) => {
          if (e.key === "Escape" && !isDisabling) onCancel();
        }}
        role="button"
        tabIndex={-1}
        aria-label="닫기"
      />
      <div className="relative w-[400px] rounded-xl bg-white p-6 shadow-xl">
        <h2 className="text-lg font-bold text-gray-900">
          동기화를 해제할까요?
        </h2>
        <p className="mt-2 text-sm text-gray-600">
          <span className="font-medium text-gray-900">&quot;{displayName}&quot;</span> 폴더의
          동기화를 해제하면 다음 파일이 삭제됩니다:
        </p>
        {isLoading ? (
          <p className="mt-1 text-sm text-gray-500">파일 수를 확인하는 중...</p>
        ) : (
          <ul className="mt-1 list-inside list-disc text-sm text-gray-600">
            {videoCount > 0 && <li>동영상 {videoCount.toLocaleString()}개</li>}
            {imageCount > 0 && <li>이미지 {imageCount.toLocaleString()}개</li>}
            {videoCount === 0 && imageCount === 0 && <li>영향받는 파일 없음</li>}
          </ul>
        )}
        <p className="mt-2 text-sm text-gray-500">
          다시 동기화하려면 파일을 재처리해야 하며, 추가 크레딧이 소요될 수 있습니다.
        </p>
        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={isDisabling}
            className="rounded-lg border border-gray-300 px-6 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-50"
          >
            취소
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isDisabling || isLoading}
            className="rounded-lg bg-red-500 px-6 py-2 text-sm font-medium text-white transition-colors hover:bg-red-600 disabled:opacity-50"
          >
            {isDisabling ? (
              <span className="flex items-center gap-2">
                <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                해제 중...
              </span>
            ) : (
              "동기화 해제"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
