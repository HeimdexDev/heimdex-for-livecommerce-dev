"use client";

interface OAuthExpiredDialogProps {
  isOpen: boolean;
  googleEmail: string | null;
  isLoading: boolean;
  onReconnect: () => void;
  onClose: () => void;
}

export function OAuthExpiredDialog({
  isOpen,
  googleEmail,
  isLoading,
  onReconnect,
  onClose,
}: OAuthExpiredDialogProps) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/40"
        onClick={isLoading ? undefined : onClose}
        onKeyDown={(e) => {
          if (e.key === "Escape" && !isLoading) onClose();
        }}
        role="button"
        tabIndex={-1}
        aria-label="닫기"
      />
      <div className="relative w-[420px] rounded-xl bg-white p-6 shadow-xl">
        {/* Warning icon */}
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-amber-50">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="h-6 w-6 text-amber-500"
            viewBox="0 0 20 20"
            fill="currentColor"
          >
            <path
              fillRule="evenodd"
              d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z"
              clipRule="evenodd"
            />
          </svg>
        </div>

        <h2 className="mt-4 text-center text-lg font-bold text-gray-900">
          Google 연결이 만료되었습니다
        </h2>

        <p className="mt-2 text-center text-sm text-gray-600">
          Google 드라이브에 접근하려면 다시 인증해 주세요.
        </p>

        {googleEmail && (
          <div className="mt-3 flex items-center justify-center gap-2 rounded-lg bg-gray-50 px-4 py-2.5">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-4 w-4 text-gray-400"
              viewBox="0 0 20 20"
              fill="currentColor"
            >
              <path d="M2.003 5.884L10 9.882l7.997-3.998A2 2 0 0016 4H4a2 2 0 00-1.997 1.884z" />
              <path d="M18 8.118l-8 4-8-4V14a2 2 0 002 2h12a2 2 0 002-2V8.118z" />
            </svg>
            <span className="text-sm text-gray-700">{googleEmail}</span>
          </div>
        )}

        <div className="mt-6 flex flex-col gap-3">
          <button
            type="button"
            onClick={onReconnect}
            disabled={isLoading}
            className="w-full rounded-lg bg-blue-500 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-600 disabled:opacity-50"
          >
            {isLoading ? (
              <span className="flex items-center justify-center gap-2">
                <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                연결 중...
              </span>
            ) : (
              "다시 연결"
            )}
          </button>
          <button
            type="button"
            onClick={onClose}
            disabled={isLoading}
            className="w-full rounded-lg border border-gray-300 px-6 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-50"
          >
            닫기
          </button>
        </div>
      </div>
    </div>
  );
}
