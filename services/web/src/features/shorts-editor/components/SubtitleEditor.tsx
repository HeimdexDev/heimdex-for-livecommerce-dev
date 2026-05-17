"use client";

import { useCallback, useMemo, useState } from "react";
import { Search } from "lucide-react";
import type { EditorSubtitle } from "../lib/types";
import { FONT_OPTIONS } from "../constants";
import { SubtitleCancelActionBar } from "./SubtitleCancelActionBar";
import { cn } from "@/lib/utils";

interface SubtitleEditorProps {
  subtitle: EditorSubtitle;
  index: number;
  onUpdate: (index: number, updates: Partial<Omit<EditorSubtitle, "id">>) => void;
  onRemove: (index: number) => void;
}

export function SubtitleEditor({
  subtitle,
  index,
  onUpdate,
  onRemove,
}: SubtitleEditorProps) {
  const handleTextChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      onUpdate(index, { text: e.target.value.slice(0, 500) });
    },
    [index, onUpdate],
  );

  const handleStyleChange = useCallback(
    (field: string, value: string | number | null) => {
      onUpdate(index, {
        style: { ...subtitle.style, [field]: value },
      });
    },
    [index, subtitle.style, onUpdate],
  );

  const handleTimingChange = useCallback(
    (field: "startMs" | "endMs", value: string) => {
      const ms = parseInt(value, 10);
      if (!isNaN(ms)) onUpdate(index, { [field]: Math.max(0, ms) });
    },
    [index, onUpdate],
  );

  return (
    <div className="space-y-4 p-4">
      {/* figma: 1713:274808 — 자막 박스/취소 액션바 */}
      <SubtitleCancelActionBar text={subtitle.text} onRemove={() => onRemove(index)} />
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">자막 편집</h3>
        <button
          type="button"
          onClick={() => onRemove(index)}
          className="text-xs text-red-h-400 hover:text-red-h-500"
        >
          삭제
        </button>
      </div>

      {/* Text input */}
      <div className="space-y-1">
        <label className="text-[10px] font-medium text-gray-500">텍스트</label>
        <textarea
          value={subtitle.text}
          onChange={handleTextChange}
          placeholder="자막 텍스트를 입력하세요..."
          maxLength={500}
          rows={3}
          className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs text-gray-900 placeholder-gray-400 resize-none focus:border-heimdex-navy-500 focus:outline-none focus:ring-1 focus:ring-heimdex-navy-500"
        />
        <p className="text-right text-[9px] text-gray-400">{subtitle.text.length}/500</p>
      </div>

      {/* Timing */}
      <div className="space-y-1">
        <p className="text-[10px] font-medium text-gray-500">타이밍 (ms)</p>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-[10px] text-gray-400">시작</label>
            <input
              type="number"
              value={subtitle.startMs}
              min={0}
              onChange={(e) => handleTimingChange("startMs", e.target.value)}
              className="w-full rounded border border-gray-300 px-2 py-1 text-xs text-gray-900 focus:border-heimdex-navy-500 focus:outline-none focus:ring-1 focus:ring-heimdex-navy-500"
            />
          </div>
          <div>
            <label className="text-[10px] text-gray-400">종료</label>
            <input
              type="number"
              value={subtitle.endMs}
              min={subtitle.startMs + 100}
              onChange={(e) => handleTimingChange("endMs", e.target.value)}
              className="w-full rounded border border-gray-300 px-2 py-1 text-xs text-gray-900 focus:border-heimdex-navy-500 focus:outline-none focus:ring-1 focus:ring-heimdex-navy-500"
            />
          </div>
        </div>
      </div>

      {/* Font */}
      <div className="space-y-1">
        <p className="text-[10px] font-medium text-gray-500">글꼴</p>
        <select
          value={subtitle.style.fontFamily}
          onChange={(e) => handleStyleChange("fontFamily", e.target.value)}
          className="w-full rounded border border-gray-300 px-2 py-1 text-xs text-gray-900 focus:border-heimdex-navy-500 focus:outline-none"
        >
          {FONT_OPTIONS.map((f) => (
            <option key={f.value} value={f.value}>{f.label}</option>
          ))}
        </select>
      </div>

      {/* Font size + weight */}
      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <label className="text-[10px] text-gray-500">크기 (px)</label>
          <input
            type="number"
            value={subtitle.style.fontSizePx}
            min={8}
            max={200}
            onChange={(e) => handleStyleChange("fontSizePx", parseInt(e.target.value, 10) || 36)}
            className="w-full rounded border border-gray-300 px-2 py-1 text-xs text-gray-900 focus:border-heimdex-navy-500 focus:outline-none"
          />
        </div>
        <div className="space-y-1">
          <label className="text-[10px] text-gray-500">굵기</label>
          <select
            value={subtitle.style.fontWeight}
            onChange={(e) => handleStyleChange("fontWeight", parseInt(e.target.value, 10))}
            className="w-full rounded border border-gray-300 px-2 py-1 text-xs text-gray-900 focus:border-heimdex-navy-500 focus:outline-none"
          >
            <option value={400}>Regular</option>
            <option value={700}>Bold</option>
          </select>
        </div>
      </div>

      {/* Color */}
      <div className="space-y-1">
        <label className="text-[10px] text-gray-500">색상</label>
        <div className="flex items-center gap-2">
          <input
            type="color"
            value={subtitle.style.fontColor}
            onChange={(e) => handleStyleChange("fontColor", e.target.value.toUpperCase())}
            className="h-7 w-7 cursor-pointer rounded border border-gray-300"
          />
          <input
            type="text"
            value={subtitle.style.fontColor}
            onChange={(e) => {
              const v = e.target.value;
              if (/^#[0-9A-Fa-f]{6}$/.test(v)) handleStyleChange("fontColor", v.toUpperCase());
            }}
            className="flex-1 rounded border border-gray-300 px-2 py-1 text-xs text-gray-900 font-mono focus:border-heimdex-navy-500 focus:outline-none"
          />
        </div>
      </div>

      {/* Position */}
      <div className="space-y-1">
        <p className="text-[10px] font-medium text-gray-500">위치</p>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-[10px] text-gray-400">X ({Math.round(subtitle.style.positionX * 100)}%)</label>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={subtitle.style.positionX}
              onChange={(e) => handleStyleChange("positionX", parseFloat(e.target.value))}
              className="w-full accent-heimdex-navy-500"
            />
          </div>
          <div>
            <label className="text-[10px] text-gray-400">Y ({Math.round(subtitle.style.positionY * 100)}%)</label>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={subtitle.style.positionY}
              onChange={(e) => handleStyleChange("positionY", parseFloat(e.target.value))}
              className="w-full accent-heimdex-navy-500"
            />
          </div>
        </div>
      </div>

      {/* Background */}
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={subtitle.style.backgroundColor !== null}
            onChange={(e) =>
              handleStyleChange("backgroundColor", e.target.checked ? "#000000" : null)
            }
            className="rounded border-gray-300 text-heimdex-navy-500"
          />
          <label className="text-[10px] text-gray-500">배경색</label>
        </div>
        {subtitle.style.backgroundColor && (
          <div className="flex items-center gap-2 pl-5">
            <input
              type="color"
              value={subtitle.style.backgroundColor}
              onChange={(e) => handleStyleChange("backgroundColor", e.target.value.toUpperCase())}
              className="h-6 w-6 cursor-pointer rounded border border-gray-300"
            />
            <div className="flex-1">
              <label className="text-[9px] text-gray-400">투명도 ({Math.round(subtitle.style.backgroundOpacity * 100)}%)</label>
              <input
                type="range"
                min={0}
                max={1}
                step={0.1}
                value={subtitle.style.backgroundOpacity}
                onChange={(e) => handleStyleChange("backgroundOpacity", parseFloat(e.target.value))}
                className="w-full accent-heimdex-navy-500"
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

interface SubtitleListNavProps {
  subtitles: EditorSubtitle[];
  selectedSubtitleIndex: number | null;
  onSelectSubtitle: (index: number | null) => void;
  onSeek: (ms: number) => void;
}

function formatTimecode(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  const cs = Math.floor((ms % 1000) / 10);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}.${String(cs).padStart(2, "0")}`;
}

// figma: 1602:37844 (left subtitle panel) — wrapper bg-white r-20 padding-20 gap-16
// figma: 1602:37863 (search bar) — h~44 r=10 border-grayscale-500 px=14 py=10 gap=10
// figma: 1670:186095 (subtitle list — row click seeks playhead to subtitle.startMs)
export function SubtitleListNav({
  subtitles,
  selectedSubtitleIndex,
  onSelectSubtitle,
  onSeek,
}: SubtitleListNavProps) {
  const [query, setQuery] = useState("");

  const order = useMemo(() => {
    const indexes = subtitles
      .map((_, i) => i)
      .sort((a, b) => subtitles[a].startMs - subtitles[b].startMs);
    const q = query.trim().toLowerCase();
    if (!q) return indexes;
    return indexes.filter((i) =>
      subtitles[i].text.toLowerCase().includes(q),
    );
  }, [subtitles, query]);

  return (
    <div className="flex flex-col gap-4 p-5">
      {/* figma 1602:37863 search bar */}
      <div className="flex items-center gap-[10px] rounded-[10px] border border-grayscale-500 bg-white px-[14px] py-[10px]">
        <Search className="h-6 w-6 shrink-0 text-grayscale-500" strokeWidth={2} />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="찾고 싶은 자막을 검색하세요."
          aria-label="자막 검색"
          className="flex-1 bg-transparent text-[14px] font-medium leading-[1.4] tracking-[-0.35px] text-grayscale-800 placeholder:text-neutral-h-300 focus:outline-none"
        />
      </div>

      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-grayscale-800">자막 목록</h3>
        <span className="text-[10px] text-grayscale-400">
          {order.length}/{subtitles.length}개
        </span>
      </div>

      <ul className="flex max-h-[420px] flex-col gap-[10px] overflow-y-auto pr-1">
        {order.map((i) => {
          const sub = subtitles[i];
          const isSelected = i === selectedSubtitleIndex;
          return (
            <li key={sub.id}>
              <button
                type="button"
                onClick={() => {
                  onSelectSubtitle(i);
                  onSeek(sub.startMs);
                }}
                aria-pressed={isSelected}
                className={cn(
                  // figma 1663:48041 selected: border-2 heimdex-navy-500
                  // figma 1663:48057 default: border neutral-h-100
                  "block w-full rounded-[10px] p-3 text-left transition-colors",
                  isSelected
                    ? "border-2 border-heimdex-navy-500 bg-white"
                    : "border border-neutral-h-100 bg-white hover:bg-grayscale-10",
                )}
              >
                <div className="mb-1.5 flex items-center gap-[10px]">
                  <span className="text-[12px] font-semibold tracking-[-0.3px] text-grayscale-800">
                    #{i + 1}
                  </span>
                  <span className="rounded-[4px] bg-grayscale-100 px-1 py-0.5 text-[10px] font-medium tracking-[-0.25px] text-grayscale-500">
                    {formatTimecode(sub.startMs)} - {formatTimecode(sub.endMs)}
                  </span>
                </div>
                <p
                  className={cn(
                    "line-clamp-2 text-[14px] font-medium leading-[1.6] tracking-[-0.35px]",
                    isSelected ? "text-heimdex-navy-500" : "text-grayscale-800",
                  )}
                >
                  {sub.text || "(빈 자막)"}
                </p>
              </button>
            </li>
          );
        })}
        {order.length === 0 && (
          <li className="px-4 py-6 text-center text-xs text-grayscale-400">
            {query ? "검색 결과 없음" : "자막이 없습니다"}
          </li>
        )}
      </ul>
    </div>
  );
}
