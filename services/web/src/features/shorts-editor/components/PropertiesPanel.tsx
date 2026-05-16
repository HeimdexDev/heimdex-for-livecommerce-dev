"use client";

import type { EditorClip, EditorSubtitle } from "../lib/types";
import { ClipProperties } from "./ClipProperties";
import { SubtitleEditor } from "./SubtitleEditor";

interface PropertiesPanelProps {
  clips: EditorClip[];
  subtitles: EditorSubtitle[];
  selectedClipIndex: number | null;
  selectedSubtitleIndex: number | null;
  onTrimClip: (index: number, trimStartMs?: number, trimEndMs?: number) => void;
  onVolumeChange: (index: number, volume: number) => void;
  onRemoveClip: (index: number) => void;
  onUpdateSubtitle: (index: number, updates: Partial<Omit<EditorSubtitle, "id">>) => void;
  onRemoveSubtitle: (index: number) => void;
}

export function PropertiesPanel({
  clips,
  subtitles,
  selectedClipIndex,
  selectedSubtitleIndex,
  onTrimClip,
  onVolumeChange,
  onRemoveClip,
  onUpdateSubtitle,
  onRemoveSubtitle,
}: PropertiesPanelProps) {
  if (selectedClipIndex != null && selectedClipIndex < clips.length) {
    return (
      <ClipProperties
        clip={clips[selectedClipIndex]}
        index={selectedClipIndex}
        onTrim={onTrimClip}
        onVolumeChange={onVolumeChange}
        onRemove={onRemoveClip}
      />
    );
  }

  if (selectedSubtitleIndex != null && selectedSubtitleIndex < subtitles.length) {
    return (
      <SubtitleEditor
        subtitle={subtitles[selectedSubtitleIndex]}
        index={selectedSubtitleIndex}
        onUpdate={onUpdateSubtitle}
        onRemove={onRemoveSubtitle}
      />
    );
  }

  return (
    <div className="flex h-full items-center justify-center p-4 text-gray-400">
      <div className="text-center">
        <p className="text-sm font-medium">속성</p>
        <p className="mt-1 text-xs">클립 또는 자막을 선택하세요</p>
      </div>
    </div>
  );
}
