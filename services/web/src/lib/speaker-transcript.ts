export interface SpeakerTurn {
  rawId: string;
  label: string;
  color: SpeakerColor;
  text: string;
}

export interface SpeakerColor {
  bg: string;
  text: string;
  border: string;
}

// Ordered for maximum visual contrast between adjacent speakers.
const SPEAKER_COLORS: SpeakerColor[] = [
  { bg: "bg-blue-100",   text: "text-blue-700",   border: "border-blue-300" },
  { bg: "bg-rose-100",   text: "text-rose-700",   border: "border-rose-300" },
  { bg: "bg-emerald-100", text: "text-emerald-700", border: "border-emerald-300" },
  { bg: "bg-amber-100",  text: "text-amber-700",  border: "border-amber-300" },
  { bg: "bg-violet-100", text: "text-violet-700",  border: "border-violet-300" },
  { bg: "bg-cyan-100",   text: "text-cyan-700",   border: "border-cyan-300" },
  { bg: "bg-pink-100",   text: "text-pink-700",   border: "border-pink-300" },
  { bg: "bg-teal-100",   text: "text-teal-700",   border: "border-teal-300" },
];

function indexToLabel(index: number): string {
  if (index < 26) return String.fromCharCode(65 + index);
  return indexToLabel(Math.floor(index / 26) - 1) + String.fromCharCode(65 + (index % 26));
}

/**
 * Parse speaker_transcript ("SPEAKER_00: text\nSPEAKER_01: text") into
 * structured turns with letter labels (A, B, C) and color assignments.
 * Input format produced by aggregate_speaker_transcript() in heimdex-media-contracts.
 */
export function parseSpeakerTranscript(transcript: string | undefined | null): SpeakerTurn[] {
  if (!transcript || !transcript.trim()) return [];

  const lines = transcript.split("\n").filter((l) => l.trim());
  const speakerIndex = new Map<string, number>();
  const turns: SpeakerTurn[] = [];

  for (const line of lines) {
    const colonIdx = line.indexOf(": ");
    if (colonIdx === -1) {
      if (turns.length > 0) {
        turns[turns.length - 1].text += " " + line.trim();
      }
      continue;
    }

    const rawId = line.slice(0, colonIdx).trim();
    const text = line.slice(colonIdx + 2).trim();

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
