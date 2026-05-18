"use client";

import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from "lucide-react";

import { cn } from "@/lib/utils";

interface PaginationProps {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  /** Visible page-number window size. Default 7 (current ±3). */
  windowSize?: number;
  className?: string;
  /** Optional aria-label on the nav element. */
  ariaLabel?: string;
}

/**
 * Numbered pagination with ellipsis-style windowing.
 *
 * Shows first + last page always, with up to ``windowSize`` pages
 * around the current page. Renders an ellipsis on either side when
 * the window doesn't touch the edges, matching the pattern:
 *
 *     1 … 4 5 [6] 7 8 … 12
 *
 * Prev/next + first/last chevron buttons guard the edges (disabled
 * on page 1 / totalPages). ``aria-current="page"`` marks the active
 * page; the whole control lives inside a ``<nav>`` with ``aria-label``
 * so screen readers can jump past it.
 *
 * Contract:
 *   - ``onPageChange`` is called with the clicked page; callers own
 *     state. Component is otherwise stateless.
 *   - Returns ``null`` when ``totalPages <= 1`` — callers never need
 *     to conditionally render.
 */
export function Pagination({
  currentPage,
  totalPages,
  onPageChange,
  windowSize = 7,
  className,
  ariaLabel = "페이지",
}: PaginationProps) {
  if (totalPages <= 1) return null;

  const safePage = Math.min(Math.max(1, currentPage), totalPages);
  const pages = buildPageList(safePage, totalPages, windowSize);
  const atFirst = safePage === 1;
  const atLast = safePage === totalPages;

  // Numbered slot + double-chevron edge buttons: 24×24, rounded-4.
  const slotBase =
    "inline-flex size-[24px] items-center justify-center rounded-[4px] p-[2px] font-pretendard text-[16px] font-medium leading-[1.4] tracking-[-0.4px] transition-colors";
  // Single-chevron prev/next buttons sit at 20×20 per figma.
  const chevBase =
    "inline-flex size-[20px] items-center justify-center rounded-[4px] p-[2px] transition-colors";

  return (
    <nav
      aria-label={ariaLabel}
      className={cn(
        "flex flex-wrap items-center justify-center gap-y-0 gap-x-[16px]",
        className,
      )}
    >
      <div className="flex items-center">
        <button
          type="button"
          disabled={atFirst}
          onClick={() => onPageChange(1)}
          aria-label="첫 페이지"
          className={cn(
            slotBase,
            atFirst
              ? "cursor-not-allowed text-neutral-h-300"
              : "text-neutral-h-500 hover:bg-neutral-h-50",
          )}
        >
          <ChevronsLeft className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
        </button>
        <button
          type="button"
          disabled={atFirst}
          onClick={() => onPageChange(safePage - 1)}
          aria-label="이전 페이지"
          className={cn(
            chevBase,
            atFirst
              ? "cursor-not-allowed text-neutral-h-300"
              : "text-neutral-h-500 hover:bg-neutral-h-50",
          )}
        >
          <ChevronLeft className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
        </button>
      </div>

      <div className="flex items-center">
        {pages.map((p, i) =>
          p === "…" ? (
            <span
              key={`gap-${i}`}
              aria-hidden="true"
              className={cn(slotBase, "text-neutral-h-500")}
            >
              …
            </span>
          ) : (
            <button
              key={p}
              type="button"
              onClick={() => onPageChange(p)}
              aria-current={p === safePage ? "page" : undefined}
              aria-label={`${p} 페이지`}
              className={cn(
                slotBase,
                p === safePage
                  ? "bg-heimdex-navy-500 text-white"
                  : "text-neutral-h-500 hover:bg-neutral-h-50",
              )}
            >
              {p}
            </button>
          ),
        )}
      </div>

      <div className="flex items-center">
        <button
          type="button"
          disabled={atLast}
          onClick={() => onPageChange(safePage + 1)}
          aria-label="다음 페이지"
          className={cn(
            chevBase,
            atLast
              ? "cursor-not-allowed text-neutral-h-300"
              : "text-neutral-h-500 hover:bg-neutral-h-50",
          )}
        >
          <ChevronRight className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
        </button>
        <button
          type="button"
          disabled={atLast}
          onClick={() => onPageChange(totalPages)}
          aria-label="마지막 페이지"
          className={cn(
            slotBase,
            atLast
              ? "cursor-not-allowed text-neutral-h-300"
              : "text-neutral-h-500 hover:bg-neutral-h-50",
          )}
        >
          <ChevronsRight className="h-4 w-4" strokeWidth={1.75} aria-hidden="true" />
        </button>
      </div>
    </nav>
  );
}

/**
 * Build the displayed page list with ellipsis where appropriate.
 *
 * Rules (given the default ``windowSize=7`` and 1-indexed pages):
 *   - If ``totalPages <= windowSize``, return every page number.
 *   - Else, anchor the window on ``currentPage`` with roughly equal
 *     halves. Always include page 1 and ``totalPages``. Insert a
 *     ``"…"`` sentinel when the window starts after 2 or ends before
 *     ``totalPages - 1``.
 *
 * Exported for unit tests.
 */
export function buildPageList(
  currentPage: number,
  totalPages: number,
  windowSize: number,
): (number | "…")[] {
  if (totalPages <= windowSize) {
    return Array.from({ length: totalPages }, (_, i) => i + 1);
  }

  const half = Math.max(1, Math.floor((windowSize - 2) / 2));
  let start = Math.max(2, currentPage - half);
  let end = Math.min(totalPages - 1, currentPage + half);

  while (end - start + 1 < windowSize - 2 && (start > 2 || end < totalPages - 1)) {
    if (start > 2) start -= 1;
    else if (end < totalPages - 1) end += 1;
    else break;
  }

  const pages: (number | "…")[] = [1];
  if (start > 2) pages.push("…");
  for (let p = start; p <= end; p++) pages.push(p);
  if (end < totalPages - 1) pages.push("…");
  pages.push(totalPages);
  return pages;
}
