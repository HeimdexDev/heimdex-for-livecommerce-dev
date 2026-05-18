"use client";

// figma: 1713:275432  (cache: .figma-cache/1713-275432_phase5_editor-3.api.json)
// node-name: 텍스트 오버레이 패널  · spec: w=371 padLRTB=20 gap=16 radius=20 (panel)
// V1 panel — rendered when the V2 OverlayPanel feature flag is off.
// Only exposes X/Y accordion-stepper + 300-char cap; rotation/stroke/shadow/
// opacity live exclusively on the V2 OverlayPanel. Tab navigation is owned
// by the outer RightPanel container.

import { useCallback, useEffect, useState } from "react";
import type { EditorSubtitle } from "../lib/types";
import { FONT_OPTIONS } from "../constants";
import { loadPresets, savePreset, deletePreset, type SubtitlePreset } from "../lib/subtitle-presets";
import { NumericStepper } from "./primitives/NumericStepper";

interface TextOverlayPanelProps {
  subtitle: EditorSubtitle | null;
  subtitleIndex: number | null;
  onAddOverlay: () => void;
  onUpdateSubtitle: (index: number, updates: Partial<Omit<EditorSubtitle, "id">>) => void;
  onRemoveSubtitle: (index: number) => void;
}

export function TextOverlayPanel({
  subtitle,
  subtitleIndex,
  onAddOverlay,
  onUpdateSubtitle,
  onRemoveSubtitle,
}: TextOverlayPanelProps) {
  const handleStyleChange = useCallback(
    (field: string, value: string | number | null) => {
      if (subtitleIndex == null || !subtitle) return;
      onUpdateSubtitle(subtitleIndex, {
        style: { ...subtitle.style, [field]: value },
      });
    },
    [subtitleIndex, subtitle, onUpdateSubtitle],
  );

  const hasSelection = subtitle != null && subtitleIndex != null;

  return (
    <div className="flex h-full flex-col bg-white">
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* + 텍스트 추가 CTA — always visible */}
        <button
          type="button"
          onClick={onAddOverlay}
          className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-heimdex-navy-500 px-3 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-heimdex-navy-600"
        >
          <PlusIcon />
          텍스트 추가
        </button>

        {/* Text content — figma counter max=300 (1713:275432, "0/300") */}
        <div>
          <textarea
            value={subtitle?.text ?? ""}
            onChange={(e) => {
              if (subtitleIndex == null) return;
              onUpdateSubtitle(subtitleIndex, { text: e.target.value.slice(0, 300) });
            }}
            disabled={!hasSelection}
            placeholder={hasSelection ? "내용을 입력해주세요." : "타임라인에서 텍스트를 선택하거나 위 버튼을 눌러 추가하세요."}
            rows={3}
            maxLength={300}
            className="w-full resize-none rounded-card border border-grayscale-200 bg-white px-3 py-2 text-sm text-grayscale-800 placeholder-grayscale-400 focus:border-heimdex-navy-500 focus:outline-none focus:ring-1 focus:ring-heimdex-navy-500 disabled:cursor-not-allowed disabled:bg-grayscale-10"
          />
          {hasSelection && (
            <span className="mt-1 block text-right text-grayscale-400" style={{ fontSize: "10px" }}>
              {subtitle.text.length}/300
            </span>
          )}
        </div>

        {/* Font / Size / Color row */}
        <div className="grid grid-cols-[1fr_72px_40px] gap-2">
          <select
            value={subtitle?.style.fontFamily ?? "Pretendard"}
            onChange={(e) => handleStyleChange("fontFamily", e.target.value)}
            disabled={!hasSelection}
            className="rounded-card border border-grayscale-200 bg-white px-3 py-2 text-sm text-grayscale-800 focus:border-heimdex-navy-500 focus:outline-none focus:ring-1 focus:ring-heimdex-navy-500 disabled:cursor-not-allowed disabled:bg-grayscale-10"
          >
            {FONT_OPTIONS.map((font) => (
              <option key={font.value} value={font.value}>
                {font.label}
              </option>
            ))}
          </select>
          <div className="relative">
            <input
              type="number"
              value={subtitle?.style.fontSizePx ?? 16}
              onChange={(e) =>
                handleStyleChange("fontSizePx", parseInt(e.target.value, 10) || 16)
              }
              disabled={!hasSelection}
              min={8}
              max={200}
              className="w-full rounded-card border border-grayscale-200 bg-white px-2 py-2 pr-7 text-sm text-grayscale-800 focus:border-heimdex-navy-500 focus:outline-none focus:ring-1 focus:ring-heimdex-navy-500 disabled:cursor-not-allowed disabled:bg-grayscale-10"
            />
            <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-grayscale-400" style={{ fontSize: "10px" }}>
              px
            </span>
          </div>
          <input
            type="color"
            value={subtitle?.style.fontColor ?? "#FF3B30"}
            onChange={(e) => handleStyleChange("fontColor", e.target.value)}
            disabled={!hasSelection}
            className="h-10 w-10 cursor-pointer rounded-lg border border-grayscale-200 bg-white p-0.5 disabled:cursor-not-allowed disabled:opacity-50"
            aria-label="텍스트 색상"
          />
        </div>

        {/* Selection-only controls */}
        {hasSelection && (
          <>
            {/* Weight */}
            <div>
              <label className="mb-1.5 block text-xs font-medium text-grayscale-500">굵기</label>
              <div className="flex gap-2">
                {[
                  { value: 400, label: "보통" },
                  { value: 700, label: "굵게" },
                ].map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => handleStyleChange("fontWeight", opt.value)}
                    className={`flex-1 rounded-lg border px-3 py-1.5 text-xs transition-colors ${
                      subtitle.style.fontWeight === opt.value
                        ? "border-heimdex-navy-500 bg-grayscale-10 text-heimdex-navy-500 font-semibold"
                        : "border-grayscale-200 text-grayscale-500 hover:bg-grayscale-10"
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Position — figma X/Y accordion-stepper (1713:275432, w=97 h=40 r=10) */}
            <div>
              <label className="mb-1.5 block text-xs font-medium text-grayscale-500">위치</label>
              <div className="flex items-stretch gap-2">
                <NumericStepper
                  value={Math.round(subtitle.style.positionX * 100)}
                  min={0}
                  max={100}
                  onChange={(v) => handleStyleChange("positionX", v / 100)}
                  unit="X"
                  ariaLabel="X position"
                  className="flex-1"
                />
                <NumericStepper
                  value={Math.round(subtitle.style.positionY * 100)}
                  min={0}
                  max={100}
                  onChange={(v) => handleStyleChange("positionY", v / 100)}
                  unit="Y"
                  ariaLabel="Y position"
                  className="flex-1"
                />
              </div>
            </div>

            {/* Preset section (inline preset save + apply inside the
                wrapper) was dropped per the 2026-05-18 goal capture — the
                GNB TemplateSaveMenu + the right-wrapper 템플릿 tab cover the
                same surface. Same reasoning as the V2 OverlayPanel. The
                local PresetSection helper below is retained as dead code
                but no longer rendered. */}

            {/* Delete */}
            <button
              type="button"
              onClick={() => onRemoveSubtitle(subtitleIndex)}
              className="w-full rounded-lg border border-red-200 px-3 py-2 text-xs font-medium text-red-600 transition-colors hover:bg-red-50"
            >
              자막 삭제
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function PlusIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 5v14m-7-7h14" />
    </svg>
  );
}

function PresetSection({
  currentStyle,
  onApplyPreset,
}: {
  currentStyle: EditorSubtitle["style"];
  onApplyPreset: (style: EditorSubtitle["style"]) => void;
}) {
  const [presets, setPresets] = useState<SubtitlePreset[]>([]);
  const [isNaming, setIsNaming] = useState(false);
  const [presetName, setPresetName] = useState("");

  useEffect(() => {
    setPresets(loadPresets());
  }, []);

  const handleSave = () => {
    if (!presetName.trim()) return;
    savePreset(presetName.trim(), currentStyle);
    setPresets(loadPresets());
    setPresetName("");
    setIsNaming(false);
  };

  const handleDelete = (id: string) => {
    deletePreset(id);
    setPresets(loadPresets());
  };

  return (
    <div>
      <label className="mb-1.5 block text-xs font-medium text-grayscale-500">프리셋</label>

      {isNaming ? (
        <div className="mb-2 flex gap-1.5">
          <input
            type="text"
            value={presetName}
            onChange={(e) => setPresetName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSave();
              if (e.key === "Escape") setIsNaming(false);
            }}
            placeholder="프리셋 이름"
            autoFocus
            className="flex-1 rounded-lg border border-grayscale-200 px-2 py-1.5 text-xs focus:border-heimdex-navy-500 focus:outline-none"
          />
          <button
            type="button"
            onClick={handleSave}
            className="rounded-lg bg-heimdex-navy-500 px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-heimdex-navy-600"
          >
            저장
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setIsNaming(true)}
          className="mb-2 w-full rounded-lg border border-grayscale-200 bg-white px-3 py-2 text-xs font-semibold text-heimdex-navy-500 transition-colors hover:bg-grayscale-10"
        >
          현재 스타일 저장
        </button>
      )}

      {presets.length > 0 && (
        <div className="space-y-1">
          {presets.map((preset) => (
            <div
              key={preset.id}
              className="flex items-center gap-2 rounded-lg border border-grayscale-100 px-2.5 py-1.5 transition-colors hover:bg-grayscale-10"
            >
              <div
                className="h-5 w-5 shrink-0 rounded border border-grayscale-200"
                style={{
                  backgroundColor: preset.style.backgroundColor ?? preset.style.fontColor,
                  opacity: preset.style.backgroundColor ? preset.style.backgroundOpacity : 1,
                }}
              />
              <button
                type="button"
                onClick={() => onApplyPreset({ ...preset.style })}
                className="flex-1 truncate text-left text-xs text-grayscale-800"
              >
                {preset.name}
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  handleDelete(preset.id);
                }}
                className="shrink-0 text-grayscale-400 hover:text-red-500"
                style={{ fontSize: "10px" }}
              >
                삭제
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
