// ============================================================================
// Page-level "쇼츠 내보내기" button + per-child checkbox dropdown.
//
// Replaces the legacy in-editor "내 편집으로 다시 렌더링" footer button.
// Lets the operator pick which clips to render (single, multi, or all),
// and exposes per-clip progress badges as the export batch proceeds.
//
// Pure presentational — caller owns the export batch state (see
// useExportBatch hook in Phase D). This component renders + emits intent.
// ============================================================================

"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import type { JobStatusResponse } from "@/lib/types/shorts-auto-product-wizard";
import { cn } from "@/lib/utils";

export type ExportItemState =
  | { status: "idle" }
  | { status: "queued" }
  | { status: "rendering" }
  | { status: "completed"; downloadUrl: string | null }
  | { status: "failed"; message: string };

interface Props {
  /** Sorted children (by shorts_index) — only those with render_job_id. */
  children: JobStatusResponse[];
  /** Currently-focused clip's job_id — used to pre-select on first open. */
  activeJobId: string | null;
  /** Per-job export state (from useExportBatch). Empty until a batch runs. */
  exportState: ReadonlyMap<string, ExportItemState>;
  /** Fires when the operator clicks 내보내기 inside the dropdown. */
  onExport: (jobIds: string[]) => void;
  /** Disables the trigger button entirely (e.g. while no children are ready). */
  disabled?: boolean;
  /** True while a batch is in flight — drives button copy + disabled state. */
  isRunning?: boolean;
  /** Optional progress display when isRunning (e.g. "1/3"). */
  progressLabel?: string;
  className?: string;
}

export function ExportShortsButton({
  children,
  activeJobId,
  exportState,
  onExport,
  disabled,
  isRunning,
  progressLabel,
  className,
}: Props) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const containerRef = useRef<HTMLDivElement | null>(null);
  // One-shot guard so the pre-select runs ONCE per open, not every time
  // ``selected`` goes back to empty via the user's deselects. Without this
  // a user who toggles off the pre-selected clip would see it snap back on.
  const preselectedThisOpenRef = useRef(false);

  // Resolve Q10: default selection = currently-focused clip. The user can
  // promote to "모두" with one click, or pick others manually.
  useEffect(() => {
    if (!open) {
      preselectedThisOpenRef.current = false;
      return;
    }
    if (preselectedThisOpenRef.current) return;
    preselectedThisOpenRef.current = true;
    if (activeJobId && children.some((c) => c.render_job_id === activeJobId)) {
      setSelected(new Set([activeJobId]));
    }
  }, [open, activeJobId, children]);

  // Q8 — close the dropdown when the consumer signals a context change
  // (parent uses ``key`` to remount on tab switch).
  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (event: MouseEvent) => {
      if (!containerRef.current) return;
      if (!containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  const allRenderableIds = children
    .map((c) => c.render_job_id)
    .filter((id): id is string => Boolean(id));

  const selectAll = () => setSelected(new Set(allRenderableIds));
  const isAllSelected =
    allRenderableIds.length > 0 &&
    allRenderableIds.every((id) => selected.has(id));

  const toggleOne = (jobId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(jobId)) next.delete(jobId);
      else next.add(jobId);
      return next;
    });
  };

  const handleExport = () => {
    if (selected.size === 0) return;
    onExport(Array.from(selected));
  };

  const buttonLabel = isRunning
    ? `렌더링 중... ${progressLabel ?? ""}`.trim()
    : "쇼츠 내보내기";

  return (
    <div
      ref={containerRef}
      className={cn("relative", className)}
      data-testid="export-shorts-container"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled || isRunning || allRenderableIds.length === 0}
        className={cn(
          "rounded-full px-4 py-1.5 text-sm font-medium text-white transition-colors",
          disabled || isRunning || allRenderableIds.length === 0
            ? "bg-red-300"
            : "bg-red-500 hover:bg-red-600",
        )}
        data-testid="export-shorts-trigger"
        aria-expanded={open}
        aria-haspopup="menu"
      >
        {buttonLabel}
      </button>

      {open ? (
        <div
          role="menu"
          aria-label="쇼츠 내보내기 옵션"
          className="absolute right-0 z-20 mt-2 w-56 rounded-md border border-gray-200 bg-white p-2 text-sm shadow-lg"
          data-testid="export-shorts-dropdown"
        >
          <button
            type="button"
            onClick={selectAll}
            disabled={isAllSelected || allRenderableIds.length === 0}
            className={cn(
              "block w-full rounded px-2 py-1.5 text-left text-gray-700",
              isAllSelected ? "text-gray-400" : "hover:bg-gray-50",
            )}
            data-testid="export-shorts-select-all"
          >
            모두 내보내기
          </button>
          <div className="px-2 py-1 text-xs font-medium text-gray-400">
            선택한 쇼츠 내보내기
          </div>
          <ul className="max-h-48 overflow-y-auto">
            {children.map((child) => {
              const jobId = child.render_job_id;
              if (!jobId) return null;
              const state = exportState.get(jobId);
              const checked = selected.has(jobId);
              const idx = child.shorts_index ?? 0;
              return (
                <li key={jobId}>
                  <label
                    className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 hover:bg-gray-50"
                    data-testid={`export-shorts-row-${idx}`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleOne(jobId)}
                      data-testid={`export-shorts-checkbox-${idx}`}
                    />
                    <span className="flex-1 text-gray-700">쇼츠 {idx}</span>
                    <ExportStateBadge state={state} />
                  </label>
                </li>
              );
            })}
          </ul>
          <button
            type="button"
            onClick={handleExport}
            disabled={selected.size === 0}
            className={cn(
              "mt-2 w-full rounded px-3 py-2 text-sm font-medium",
              selected.size === 0
                ? "bg-gray-200 text-gray-500"
                : "bg-gray-900 text-white hover:bg-gray-700",
            )}
            data-testid="export-shorts-submit"
          >
            내보내기
          </button>
        </div>
      ) : null}
    </div>
  );
}

function ExportStateBadge({
  state,
}: {
  state: ExportItemState | undefined;
}): ReactNode {
  if (!state || state.status === "idle") return null;
  switch (state.status) {
    case "queued":
      return (
        <span className="text-xs text-gray-500" data-testid="export-badge-queued">
          대기
        </span>
      );
    case "rendering":
      return (
        <span
          className="text-xs text-amber-600"
          data-testid="export-badge-rendering"
        >
          렌더링 중
        </span>
      );
    case "completed":
      return (
        <span
          className="text-xs text-green-600"
          data-testid="export-badge-completed"
        >
          완료
        </span>
      );
    case "failed":
      return (
        <span className="text-xs text-red-600" data-testid="export-badge-failed">
          실패
        </span>
      );
  }
}
