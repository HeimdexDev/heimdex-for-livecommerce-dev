"use client";

import { useCallback } from "react";
import type { EditorClip } from "../lib/types";
import { getClipDuration, formatTimelineTimestamp } from "../lib/timeline-math";

interface ClipPropertiesProps {
  clip: EditorClip;
  index: number;
  onTrim: (index: number, trimStartMs?: number, trimEndMs?: number) => void;
  onVolumeChange: (index: number, volume: number) => void;
  onRemove: (index: number) => void;
}

export function ClipProperties({
  clip,
  index,
  onTrim,
  onVolumeChange,
  onRemove,
}: ClipPropertiesProps) {
  const duration = getClipDuration(clip);

  const handleStartChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = parseInt(e.target.value, 10);
      if (!isNaN(val)) onTrim(index, val, undefined);
    },
    [index, onTrim],
  );

  const handleEndChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = parseInt(e.target.value, 10);
      if (!isNaN(val)) onTrim(index, undefined, val);
    },
    [index, onTrim],
  );

  const handleVolumeChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onVolumeChange(index, parseFloat(e.target.value));
    },
    [index, onVolumeChange],
  );

  return (
    <div className="space-y-4 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-grayscale-800">클립 속성</h3>
        <button
          type="button"
          onClick={() => onRemove(index)}
          className="text-xs text-red-500 hover:text-red-600"
        >
          삭제
        </button>
      </div>

      {/* Scene info */}
      <div className="rounded-lg bg-grayscale-100 p-3 space-y-1">
        <p className="text-[10px] font-medium text-grayscale-500">장면 정보</p>
        <p className="text-xs text-grayscale-500">장면 {index + 1}</p>
        <p className="text-[10px] text-grayscale-500">
          원본 범위: {formatTimelineTimestamp(clip.originalStartMs)} - {formatTimelineTimestamp(clip.originalEndMs)}
        </p>
      </div>

      {/* Trim controls */}
      <div className="space-y-2">
        <p className="text-[10px] font-medium text-grayscale-500">트리밍 (ms)</p>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-[10px] text-grayscale-400">시작</label>
            <input
              type="number"
              value={clip.trimStartMs}
              min={clip.originalStartMs}
              max={clip.trimEndMs - 1}
              onChange={handleStartChange}
              className="w-full rounded border border-grayscale-200 px-2 py-1 text-xs text-grayscale-800 focus:border-heimdex-navy-500 focus:outline-none focus:ring-1 focus:ring-heimdex-navy-500"
            />
          </div>
          <div>
            <label className="text-[10px] text-grayscale-400">종료</label>
            <input
              type="number"
              value={clip.trimEndMs}
              min={clip.trimStartMs + 1}
              max={clip.originalEndMs}
              onChange={handleEndChange}
              className="w-full rounded border border-grayscale-200 px-2 py-1 text-xs text-grayscale-800 focus:border-heimdex-navy-500 focus:outline-none focus:ring-1 focus:ring-heimdex-navy-500"
            />
          </div>
        </div>
        <p className="text-[10px] text-grayscale-400">
          길이: {(duration / 1000).toFixed(1)}초
        </p>
      </div>

      {/* Volume */}
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <p className="text-[10px] font-medium text-grayscale-500">볼륨</p>
          <span className="text-[10px] text-grayscale-400">{Math.round(clip.volume * 100)}%</span>
        </div>
        <input
          type="range"
          min={0}
          max={3}
          step={0.1}
          value={clip.volume}
          onChange={handleVolumeChange}
          className="w-full accent-indigo-500"
        />
        <div className="flex justify-between text-[9px] text-grayscale-400">
          <span>음소거</span>
          <span>300%</span>
        </div>
      </div>
    </div>
  );
}
