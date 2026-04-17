export function msToPixels(ms: number, zoom: number): number {
  return (ms / 1000) * zoom;
}

export function pixelsToMs(px: number, zoom: number): number {
  if (zoom === 0) return 0;
  return (px / zoom) * 1000;
}

export function snapToGrid(ms: number, gridMs: number): number {
  if (gridMs <= 0) return ms;
  return Math.round(ms / gridMs) * gridMs;
}

export function formatTimelineTimestamp(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  if (h > 0) {
    return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }
  return `${m}:${String(s).padStart(2, "0")}`;
}
