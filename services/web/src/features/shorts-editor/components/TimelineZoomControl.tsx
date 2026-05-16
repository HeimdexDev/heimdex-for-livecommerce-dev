"use client";

// figma: 1670:185907 — 타임라인 zoom 슬라이더 (minus icon + 88px track + plus icon)
//        1669:154010 (펼침) / 1669:49002 (접힘) — zoom 변동 시 자막 섹션 펼침/접힘 신호로도 사용
import { useCallback } from "react";
import { MIN_ZOOM, MAX_ZOOM } from "../constants";

interface TimelineZoomControlProps {
  zoom: number;
  onZoomChange: (zoom: number) => void;
}

const STEP = 25;

function MinusIcon() {
  return (
    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M18 12H6" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v12m6-6H6" />
    </svg>
  );
}

export function TimelineZoomControl({ zoom, onZoomChange }: TimelineZoomControlProps) {
  const handleDec = useCallback(() => {
    onZoomChange(Math.max(MIN_ZOOM, zoom - STEP));
  }, [zoom, onZoomChange]);

  const handleInc = useCallback(() => {
    onZoomChange(Math.min(MAX_ZOOM, zoom + STEP));
  }, [zoom, onZoomChange]);

  return (
    <div className="flex items-center gap-1.5">
      <button
        type="button"
        onClick={handleDec}
        disabled={zoom <= MIN_ZOOM}
        aria-label="타임라인 축소"
        className="rounded p-0.5 text-gray-500 hover:bg-gray-200 hover:text-gray-700 disabled:cursor-not-allowed disabled:opacity-30"
      >
        <MinusIcon />
      </button>
      <input
        type="range"
        min={MIN_ZOOM}
        max={MAX_ZOOM}
        step={STEP}
        value={zoom}
        onChange={(e) => onZoomChange(Number(e.target.value))}
        aria-label={`타임라인 배율 ${zoom}%`}
        className="h-1 w-20 cursor-pointer accent-grayscale-800"
      />
      <button
        type="button"
        onClick={handleInc}
        disabled={zoom >= MAX_ZOOM}
        aria-label="타임라인 확대"
        className="rounded p-0.5 text-gray-500 hover:bg-gray-200 hover:text-gray-700 disabled:cursor-not-allowed disabled:opacity-30"
      >
        <PlusIcon />
      </button>
      <span className="w-9 text-center text-[10px] text-gray-500">{zoom}%</span>
    </div>
  );
}
