"use client";

import { useCallback, useEffect, useState } from "react";
import type { EditorSubtitle } from "../lib/types";
import { FONT_OPTIONS } from "../constants";
import { loadPresets, savePreset, deletePreset, type SubtitlePreset } from "../lib/subtitle-presets";

type Tab = "text" | "background";

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
  const [tab, setTab] = useState<Tab>("text");

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
  const bgEnabled = subtitle?.style.backgroundColor != null;

  return (
    <div className="flex h-full flex-col bg-white">
      {/* Tabs */}
      <div className="flex items-center gap-4 border-b border-gray-200 px-4 pt-4">
        <TabButton active={tab === "text"} onClick={() => setTab("text")}>
          텍스트
        </TabButton>
        <TabButton active={tab === "background"} onClick={() => setTab("background")}>
          배경
        </TabButton>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* + 텍스트 추가 CTA — always visible */}
        <button
          type="button"
          onClick={onAddOverlay}
          className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2.5 text-sm font-medium text-white transition-colors hover:bg-indigo-700"
        >
          <PlusIcon />
          텍스트 추가
        </button>

        {/* Text content */}
        <div>
          <textarea
            value={subtitle?.text ?? ""}
            onChange={(e) => {
              if (subtitleIndex == null) return;
              onUpdateSubtitle(subtitleIndex, { text: e.target.value.slice(0, 500) });
            }}
            disabled={!hasSelection}
            placeholder={hasSelection ? "내용을 입력해주세요." : "타임라인에서 텍스트를 선택하거나 위 버튼을 눌러 추가하세요."}
            rows={3}
            maxLength={500}
            className="w-full resize-none rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:cursor-not-allowed disabled:bg-gray-50"
          />
          {hasSelection && (
            <span className="mt-1 block text-right text-[10px] text-gray-400">
              {subtitle.text.length}/500
            </span>
          )}
        </div>

        {/* Font / Size / Color row */}
        {tab === "text" && (
          <div className="grid grid-cols-[1fr_72px_40px] gap-2">
            <select
              value={subtitle?.style.fontFamily ?? "Pretendard"}
              onChange={(e) => handleStyleChange("fontFamily", e.target.value)}
              disabled={!hasSelection}
              className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:cursor-not-allowed disabled:bg-gray-50"
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
                className="w-full rounded-lg border border-gray-200 bg-white px-2 py-2 pr-7 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:cursor-not-allowed disabled:bg-gray-50"
              />
              <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-gray-400">
                px
              </span>
            </div>
            <input
              type="color"
              value={subtitle?.style.fontColor ?? "#FF3B30"}
              onChange={(e) => handleStyleChange("fontColor", e.target.value)}
              disabled={!hasSelection}
              className="h-10 w-10 cursor-pointer rounded-lg border border-gray-200 bg-white p-0.5 disabled:cursor-not-allowed disabled:opacity-50"
              aria-label="텍스트 색상"
            />
          </div>
        )}

        {/* Background tab content */}
        {tab === "background" && (
          <div className="space-y-3">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={bgEnabled}
                disabled={!hasSelection}
                onChange={(e) =>
                  handleStyleChange("backgroundColor", e.target.checked ? "#000000" : null)
                }
                className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 disabled:cursor-not-allowed"
              />
              <span className="text-sm text-gray-700">배경 색상 사용</span>
            </label>
            {bgEnabled && hasSelection && (
              <>
                <div className="flex items-center gap-2">
                  <input
                    type="color"
                    value={subtitle.style.backgroundColor ?? "#000000"}
                    onChange={(e) => handleStyleChange("backgroundColor", e.target.value)}
                    className="h-9 w-9 cursor-pointer rounded-lg border border-gray-200 p-0.5"
                  />
                  <span className="text-xs text-gray-500">색상</span>
                </div>
                <div>
                  <div className="mb-1 flex items-center justify-between">
                    <span className="text-xs text-gray-500">투명도</span>
                    <span className="text-[10px] text-gray-400">
                      {Math.round(subtitle.style.backgroundOpacity * 100)}%
                    </span>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={Math.round(subtitle.style.backgroundOpacity * 100)}
                    onChange={(e) =>
                      handleStyleChange("backgroundOpacity", parseInt(e.target.value, 10) / 100)
                    }
                    className="w-full accent-indigo-500"
                  />
                </div>
              </>
            )}
          </div>
        )}

        {/* Selection-only controls */}
        {hasSelection && tab === "text" && (
          <>
            {/* Weight */}
            <div>
              <label className="mb-1.5 block text-xs font-medium text-gray-500">굵기</label>
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
                        ? "border-indigo-500 bg-indigo-50 text-indigo-700"
                        : "border-gray-200 text-gray-600 hover:bg-gray-50"
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Position */}
            <div>
              <label className="mb-1.5 block text-xs font-medium text-gray-500">위치</label>
              <div className="space-y-2">
                {(["positionX", "positionY"] as const).map((axis) => (
                  <div key={axis} className="flex items-center gap-2">
                    <span className="w-6 text-xs text-gray-500">
                      {axis === "positionX" ? "X" : "Y"}
                    </span>
                    <input
                      type="range"
                      min={0}
                      max={100}
                      value={Math.round(subtitle.style[axis] * 100)}
                      onChange={(e) =>
                        handleStyleChange(axis, parseInt(e.target.value, 10) / 100)
                      }
                      className="flex-1 accent-indigo-500"
                    />
                    <span className="w-8 text-right text-[10px] text-gray-400">
                      {Math.round(subtitle.style[axis] * 100)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Presets */}
            <PresetSection
              currentStyle={subtitle.style}
              onApplyPreset={(style) => onUpdateSubtitle(subtitleIndex, { style })}
            />

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

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`pb-2 text-sm transition-colors ${
        active
          ? "border-b-2 border-indigo-600 font-semibold text-gray-900"
          : "border-b-2 border-transparent font-medium text-gray-400 hover:text-gray-600"
      }`}
    >
      {children}
    </button>
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
      <label className="mb-1.5 block text-xs font-medium text-gray-500">프리셋</label>

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
            className="flex-1 rounded-lg border border-gray-200 px-2 py-1.5 text-xs focus:border-indigo-500 focus:outline-none"
          />
          <button
            type="button"
            onClick={handleSave}
            className="rounded-lg bg-indigo-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-indigo-700"
          >
            저장
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setIsNaming(true)}
          className="mb-2 w-full rounded-lg bg-indigo-50 px-3 py-2 text-xs font-medium text-indigo-700 transition-colors hover:bg-indigo-100"
        >
          현재 스타일 저장
        </button>
      )}

      {presets.length > 0 && (
        <div className="space-y-1">
          {presets.map((preset) => (
            <div
              key={preset.id}
              className="flex items-center gap-2 rounded-lg border border-gray-100 px-2.5 py-1.5 transition-colors hover:bg-gray-50"
            >
              <div
                className="h-5 w-5 shrink-0 rounded border border-gray-200"
                style={{
                  backgroundColor: preset.style.backgroundColor ?? preset.style.fontColor,
                  opacity: preset.style.backgroundColor ? preset.style.backgroundOpacity : 1,
                }}
              />
              <button
                type="button"
                onClick={() => onApplyPreset({ ...preset.style })}
                className="flex-1 truncate text-left text-xs text-gray-700"
              >
                {preset.name}
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  handleDelete(preset.id);
                }}
                className="shrink-0 text-[10px] text-gray-400 hover:text-red-500"
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
