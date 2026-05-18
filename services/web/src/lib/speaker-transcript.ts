export interface SpeakerTurn {
  rawId: string;
  label: string;
  color: SpeakerColor;
  text: string;
  timestamp: string | null;
}

export interface SpeakerColor {
  bg: string;
  text: string;
  border: string;
}

// Figma P3 1713:270773 매핑: 화자 A = red-h.400 (#d53b49), B = green-h.400 (#3fb675).
// 3번째 화자부터는 보조 팔레트.
const SPEAKER_COLORS: SpeakerColor[] = [
  { bg: "bg-red-h-50",    text: "text-red-h-400",   border: "border-red-h-400" },
  { bg: "bg-green-h-50",  text: "text-green-h-400", border: "border-green-h-400" },
  { bg: "bg-blue-100",    text: "text-blue-700",    border: "border-blue-300" },
  { bg: "bg-amber-100",   text: "text-amber-700",   border: "border-amber-300" },
  { bg: "bg-violet-100",  text: "text-violet-700",  border: "border-violet-300" },
  { bg: "bg-cyan-100",    text: "text-cyan-700",    border: "border-cyan-300" },
  { bg: "bg-pink-100",    text: "text-pink-700",    border: "border-pink-300" },
  { bg: "bg-teal-100",    text: "text-teal-700",    border: "border-teal-300" },
];

function indexToLabel(index: number): string {
  if (index < 26) return String.fromCharCode(65 + index);
  return indexToLabel(Math.floor(index / 26) - 1) + String.fromCharCode(65 + (index % 26));
}

// Matches: "SPEAKER_00 [1:23]: text" or "SPEAKER_00: text" (no timestamp)
const LINE_PATTERN = /^(\S+?)(?:\s+\[([^\]]+)\])?\s*:\s*(.+)$/;

/**
 * Parse speaker_transcript into structured turns with letter labels and timestamps.
 * Handles both formats:
 *   - New: "SPEAKER_00 [1:23]: text"  (with timestamp)
 *   - Old: "SPEAKER_00: text"         (without timestamp)
 */
export function parseSpeakerTranscript(transcript: string | undefined | null): SpeakerTurn[] {
  if (!transcript || !transcript.trim()) return [];

  const lines = transcript.split("\n").filter((l) => l.trim());
  const speakerIndex = new Map<string, number>();
  const turns: SpeakerTurn[] = [];

  for (const line of lines) {
    const match = LINE_PATTERN.exec(line);
    if (!match) {
      if (turns.length > 0) {
        turns[turns.length - 1].text += " " + line.trim();
      }
      continue;
    }

    const rawId = match[1];
    const timestamp = match[2] ?? null;
    const text = match[3].trim();

    if (!text) continue;

    if (!speakerIndex.has(rawId)) {
      speakerIndex.set(rawId, speakerIndex.size);
    }
    const idx = speakerIndex.get(rawId)!;

    turns.push({
      rawId,
      label: indexToLabel(idx),
      color: SPEAKER_COLORS[idx % SPEAKER_COLORS.length],
      text,
      timestamp,
    });
  }

  return turns;
}

export function getUniqueSpeakers(turns: SpeakerTurn[]): Map<string, SpeakerColor> {
  const map = new Map<string, SpeakerColor>();
  for (const turn of turns) {
    if (!map.has(turn.label)) {
      map.set(turn.label, turn.color);
    }
  }
  return map;
}
