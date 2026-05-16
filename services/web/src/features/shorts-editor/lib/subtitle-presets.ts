import type { SubtitleStyle } from "./types";

const STORAGE_KEY = "heimdex:subtitle-presets";
const MAX_PRESETS = 10;

export interface SubtitlePreset {
  id: string;
  name: string;
  style: SubtitleStyle;
  createdAt: number;
}

export function loadPresets(): SubtitlePreset[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as SubtitlePreset[];
  } catch {
    return [];
  }
}

export function savePreset(name: string, style: SubtitleStyle): SubtitlePreset {
  const presets = loadPresets();
  const preset: SubtitlePreset = {
    id: `preset_${Date.now()}`,
    name,
    style: { ...style },
    createdAt: Date.now(),
  };

  presets.push(preset);

  // FIFO eviction if over limit
  while (presets.length > MAX_PRESETS) {
    presets.shift();
  }

  localStorage.setItem(STORAGE_KEY, JSON.stringify(presets));
  return preset;
}

export function deletePreset(id: string): void {
  const presets = loadPresets().filter((p) => p.id !== id);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(presets));
}
