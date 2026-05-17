"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { useSceneBasket } from "./useSceneBasket";
import { ExportModal } from "./ExportModal";

const fmt = (ms: number) => {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)
    .toString()
    .padStart(2, "0")}:${(s % 60).toString().padStart(2, "0")}`;
};

function truncateTitle(title: string, max = 30): string {
  if (title.length <= max) {
    return title;
  }
  return `${title.slice(0, max)}...`;
}

export function BasketPanel() {
  const { items, removeItem, clearBasket, itemCount, totalDurationMs } = useSceneBasket();
  const [open, setOpen] = useState(false);
  const [exportModalOpen, setExportModalOpen] = useState(false);

  const handleClear = () => {
    if (!window.confirm("바구니를 비우시겠습니까?")) {
      return;
    }
    clearBasket();
  };

  return (
    <>
      {itemCount > 0 && (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="fixed bottom-6 right-6 z-40 bg-primary-600 text-white rounded-full p-3 shadow-lg hover:bg-primary-700"
          aria-label="내보내기 바구니 열기"
        >
          <div className="relative">
            <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M5 8h14l-1 11H6L5 8zm2-3h10l1 3H6l1-3z"
              />
            </svg>
            <span className="absolute -top-2 -right-2 bg-white text-primary-700 text-xs font-semibold min-w-5 h-5 px-1 rounded-full flex items-center justify-center">
              {itemCount}
            </span>
          </div>
        </button>
      )}

      {open && (
        <button
          type="button"
          className="fixed inset-0 bg-black/30 z-40"
          onClick={() => setOpen(false)}
          aria-label="바구니 닫기"
        />
      )}

      <aside
        className={cn(
          "fixed top-0 right-0 h-full w-96 bg-white shadow-xl z-50 transition-transform duration-300 ease-out flex flex-col",
          open ? "translate-x-0" : "translate-x-full"
        )}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
          <h2 className="text-base font-semibold text-gray-900">내보내기 바구니</h2>
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="text-gray-500 hover:text-gray-700 text-xl leading-none"
            aria-label="닫기"
          >
            ×
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
          {items.length === 0 ? (
            <p className="text-sm text-gray-500">담긴 장면이 없습니다.</p>
          ) : (
            items.map((item) => (
              <div
                key={item.scene_id}
                className="border border-gray-200 rounded-lg px-3 py-2 flex items-start justify-between gap-2"
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-900 truncate">
                    {truncateTitle(item.video_title || item.video_id)}
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    {fmt(item.start_ms)} - {fmt(item.end_ms)}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => removeItem(item.scene_id)}
                  className="text-gray-400 hover:text-red-500 text-lg leading-none"
                  aria-label="항목 제거"
                >
                  ×
                </button>
              </div>
            ))
          )}
        </div>

        <div className="border-t border-gray-200 px-4 py-3 space-y-3">
          <p className="text-sm text-gray-600">
            {itemCount}개 장면 · {fmt(totalDurationMs)}
          </p>
          <button
            type="button"
            onClick={() => setExportModalOpen(true)}
            disabled={itemCount === 0}
            className="w-full bg-primary-600 text-white py-2.5 rounded-lg hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            내보내기
          </button>
          <button
            type="button"
            onClick={handleClear}
            className="text-sm text-gray-500 hover:text-red-500"
          >
            전체 삭제
          </button>
        </div>
      </aside>

      <ExportModal isOpen={exportModalOpen} onClose={() => setExportModalOpen(false)} />
    </>
  );
}
