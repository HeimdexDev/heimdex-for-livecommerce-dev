"use client";

// figma: 1602:41198  (cache: .figma-cache/screenshots/1607-65302_reference.png)
// node-name: 템플릿 탭 (right-panel "템플릿" tab content)
// spec: action row (dropdown + "적용하기") + 2-col card grid (9:16, checker bg,
//   centered placeholder text, top-right rounded-square check indicator).
// Save trigger lives in EditorHeader's TemplateSaveMenu (the standalone
// "+" affordance was removed); the empty state mirrors that entry point.

import { useId, useState } from "react";

import { Check, Plus, Trash2 } from "lucide-react";

import { cn } from "@/lib/utils";
import type { WirePreset } from "../lib/overlay-types";

interface TemplatePanelProps {
  presets: WirePreset[];
  isLoading?: boolean;
  error?: string | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onApply: (preset: WirePreset) => void;
  onOpenSaveDialog: () => void;
  onDelete?: (preset: WirePreset) => void;
}

export function TemplatePanel({
  presets,
  isLoading = false,
  error = null,
  selectedId,
  onSelect,
  onApply,
  onOpenSaveDialog,
  onDelete,
}: TemplatePanelProps) {
  const selected = presets.find((p) => p.id === selectedId) ?? null;

  return (
    <div className="flex h-full flex-col gap-4 rounded-dialog bg-white p-5">
      <ActionRow
        selectedName={selected?.name ?? null}
        disabled={!selected}
        onApply={() => {
          if (selected) onApply(selected);
        }}
      />

      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <p className="text-xs text-grayscale-400">템플릿 불러오는 중…</p>
        ) : presets.length === 0 ? (
          <EmptyState onOpenSaveDialog={onOpenSaveDialog} />
        ) : (
          <div className="grid grid-cols-2 gap-4">
            {presets.map((preset) => (
              <TemplateCard
                key={preset.id}
                preset={preset}
                selected={preset.id === selectedId}
                onSelect={() => onSelect(preset.id)}
                onDelete={onDelete ? () => onDelete(preset) : undefined}
              />
            ))}
          </div>
        )}
        {error && (
          <p className="mt-2 text-[11px] text-red-h-500">{error}</p>
        )}
      </div>
    </div>
  );
}

function ActionRow({
  selectedName,
  disabled,
  onApply,
}: {
  selectedName: string | null;
  disabled: boolean;
  onApply: () => void;
}) {
  const [open, setOpen] = useState(false);

  // figma: 1602:41198 — dropdown + primary "적용하기" 만 노출.
  return (
    <div className="flex items-center gap-2.5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex h-10 flex-1 items-center justify-between gap-2.5 rounded-card border border-grayscale-300 bg-white px-3 py-2.5 text-sm font-medium text-grayscale-800 transition-colors hover:border-heimdex-navy-500 focus:outline-none focus:ring-1 focus:ring-heimdex-navy-500"
        aria-expanded={open}
      >
        <span className={cn("truncate", !selectedName && "text-grayscale-400")}>
          {selectedName ?? "템플릿 선택"}
        </span>
        <Chevron open={open} />
      </button>

      <button
        type="button"
        onClick={onApply}
        disabled={disabled}
        className="inline-flex h-10 items-center justify-center rounded-card bg-heimdex-navy-500 px-5 text-sm font-semibold text-white transition-colors hover:bg-heimdex-navy-600 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-heimdex-navy-500"
      >
        적용하기
      </button>
    </div>
  );
}

function TemplateCard({
  preset,
  selected,
  onSelect,
  onDelete,
}: {
  preset: WirePreset;
  selected: boolean;
  onSelect: () => void;
  onDelete?: () => void;
}) {
  return (
    <div
      className="group flex flex-col gap-1.5 text-left"
      aria-pressed={selected}
    >
      {/* figma: 1602:41198 — 9:16 카드 (격자 패턴 + 중앙 placeholder). */}
      <button
        type="button"
        onClick={onSelect}
        style={{ aspectRatio: "9 / 16" }}
        className={cn(
          "relative w-full overflow-hidden rounded-card border bg-white transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-heimdex-navy-500",
          selected
            ? "border-heimdex-navy-500"
            : "border-grayscale-200 group-hover:border-heimdex-navy-400",
        )}
      >
        <CheckerPattern />

        {/* 가운데 placeholder — figma 의 "확실한 두께 자신감!" */}
        <div className="absolute inset-0 flex items-center justify-center px-2">
          <span className="text-center text-sm font-semibold leading-snug text-heimdex-navy-500">
            확실한 두께 자신감!
          </span>
        </div>

        {/* UR4: 단일 선택 — 라디오 의미의 rounded-square 체크 인디케이터.
            토큰: w/h-5.5 (22px), rounded-checkbox (4px). */}
        <span
          aria-hidden
          className={cn(
            "absolute right-2 top-2 inline-flex h-5.5 w-5.5 items-center justify-center rounded-checkbox border transition-colors",
            selected
              ? "border-heimdex-navy-500 bg-heimdex-navy-500"
              : "border-grayscale-300 bg-white group-hover:border-heimdex-navy-400",
          )}
        >
          {selected && (
            <Check className="h-3.5 w-3.5 text-white" strokeWidth={2.5} />
          )}
        </span>
      </button>

      {/* 라벨 행 — 좌측 이름 truncate, 우측 hover-only 삭제 버튼.
          삭제는 figma 미정의 — 라벨 행 우측 휴지통 hover-show 로 head 결정. */}
      <div className="flex items-center gap-1">
        <span className="flex-1 truncate text-sm font-medium text-grayscale-800">
          {preset.name}
        </span>
        {onDelete && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            aria-label={`${preset.name} 템플릿 삭제`}
            className="hidden h-6 w-6 shrink-0 items-center justify-center rounded text-grayscale-400 transition-colors hover:bg-grayscale-100 hover:text-red-h-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-h-500 group-hover:inline-flex"
          >
            <Trash2 className="h-3.5 w-3.5" strokeWidth={2} />
          </button>
        )}
      </div>
    </div>
  );
}

function CheckerPattern() {
  // 격자(체커) 패턴 — figma 1602:41198 카드 배경. svg 패턴(id 충돌 방지용
  // useId) 으로 표현.
  const id = useId();
  const patternId = `checker-${id}`;
  return (
    <svg
      className="pointer-events-none absolute inset-0 h-full w-full text-grayscale-100"
      aria-hidden
      preserveAspectRatio="none"
    >
      <defs>
        <pattern
          id={patternId}
          width="20"
          height="20"
          patternUnits="userSpaceOnUse"
        >
          <rect x="0" y="0" width="10" height="10" fill="currentColor" />
          <rect x="10" y="10" width="10" height="10" fill="currentColor" />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill={`url(#${patternId})`} />
    </svg>
  );
}

function EmptyState({ onOpenSaveDialog }: { onOpenSaveDialog: () => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 py-12 text-center">
      <p className="text-xs text-grayscale-500">저장된 템플릿이 없습니다.</p>
      <button
        type="button"
        onClick={onOpenSaveDialog}
        className="inline-flex items-center gap-1.5 rounded-lg border border-grayscale-200 bg-white px-3 py-2 text-xs font-medium text-grayscale-800 transition-colors hover:border-heimdex-navy-500 hover:text-heimdex-navy-500"
      >
        <Plus className="h-3.5 w-3.5" strokeWidth={2} />
        현재 스타일 저장
      </button>
    </div>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      className={cn(
        "h-5 w-5 shrink-0 text-grayscale-500 transition-transform",
        open && "rotate-180",
      )}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
      aria-hidden
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="m6 9 6 6 6-6" />
    </svg>
  );
}
