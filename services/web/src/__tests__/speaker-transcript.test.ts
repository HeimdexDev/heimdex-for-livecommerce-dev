import { describe, expect, it } from "vitest";
import {
  parseSpeakerTranscript,
  getUniqueSpeakers,
  type SpeakerTurn,
  type SpeakerColor,
} from "@/lib/speaker-transcript";

describe("parseSpeakerTranscript", () => {
  it("returns empty array for null input", () => {
    expect(parseSpeakerTranscript(null)).toEqual([]);
  });

  it("returns empty array for undefined input", () => {
    expect(parseSpeakerTranscript(undefined)).toEqual([]);
  });

  it("returns empty array for empty string", () => {
    expect(parseSpeakerTranscript("")).toEqual([]);
  });

  it("returns empty array for whitespace-only string", () => {
    expect(parseSpeakerTranscript("   \n  \n  ")).toEqual([]);
  });

  it("parses single speaker without timestamp", () => {
    const result = parseSpeakerTranscript("SPEAKER_00: Hello world");
    expect(result).toHaveLength(1);
    expect(result[0].rawId).toBe("SPEAKER_00");
    expect(result[0].label).toBe("A");
    expect(result[0].text).toBe("Hello world");
    expect(result[0].timestamp).toBeNull();
  });

  it("parses single speaker with timestamp", () => {
    const result = parseSpeakerTranscript("SPEAKER_00 [1:23]: Hello world");
    expect(result).toHaveLength(1);
    expect(result[0].rawId).toBe("SPEAKER_00");
    expect(result[0].label).toBe("A");
    expect(result[0].text).toBe("Hello world");
    expect(result[0].timestamp).toBe("1:23");
  });

  it("assigns sequential letter labels to different speakers", () => {
    const input = [
      "SPEAKER_00 [0:00]: First speaker",
      "SPEAKER_01 [0:05]: Second speaker",
      "SPEAKER_02 [0:10]: Third speaker",
    ].join("\n");

    const result = parseSpeakerTranscript(input);
    expect(result).toHaveLength(3);
    expect(result[0].label).toBe("A");
    expect(result[1].label).toBe("B");
    expect(result[2].label).toBe("C");
  });

  it("reuses same label for same speaker across turns", () => {
    const input = [
      "SPEAKER_00 [0:00]: First turn",
      "SPEAKER_01 [0:05]: Response",
      "SPEAKER_00 [0:10]: Second turn",
    ].join("\n");

    const result = parseSpeakerTranscript(input);
    expect(result).toHaveLength(3);
    expect(result[0].label).toBe("A");
    expect(result[1].label).toBe("B");
    expect(result[2].label).toBe("A");
  });

  it("assigns different colors to different speakers", () => {
    const input = [
      "SPEAKER_00: Hello",
      "SPEAKER_01: World",
    ].join("\n");

    const result = parseSpeakerTranscript(input);
    expect(result[0].color.bg).not.toBe(result[1].color.bg);
  });

  it("cycles colors for more than 8 speakers", () => {
    const lines = Array.from({ length: 10 }, (_, i) =>
      `SPEAKER_${String(i).padStart(2, "0")}: Turn ${i}`
    ).join("\n");

    const result = parseSpeakerTranscript(lines);
    expect(result).toHaveLength(10);
    // Speakers 0 and 8 should have same color (cycle of 8)
    expect(result[0].color.bg).toBe(result[8].color.bg);
    expect(result[1].color.bg).toBe(result[9].color.bg);
  });

  it("appends continuation lines to the previous turn", () => {
    const input = [
      "SPEAKER_00 [0:00]: First line",
      "continues here",
      "SPEAKER_01 [0:05]: New turn",
    ].join("\n");

    const result = parseSpeakerTranscript(input);
    expect(result).toHaveLength(2);
    expect(result[0].text).toBe("First line continues here");
    expect(result[1].text).toBe("New turn");
  });

  it("ignores continuation lines before any speaker", () => {
    const input = [
      "orphan line",
      "SPEAKER_00: Hello",
    ].join("\n");

    const result = parseSpeakerTranscript(input);
    expect(result).toHaveLength(1);
    expect(result[0].text).toBe("Hello");
  });

  it("skips turns with empty text after speaker prefix", () => {
    const input = [
      "SPEAKER_00 [0:00]: Hello",
      "SPEAKER_01 [0:05]:   ",
      "SPEAKER_00 [0:10]: World",
    ].join("\n");

    const result = parseSpeakerTranscript(input);
    expect(result).toHaveLength(2);
    expect(result[0].text).toBe("Hello");
    expect(result[1].text).toBe("World");
  });

  it("handles timestamps with hours", () => {
    const result = parseSpeakerTranscript("SPEAKER_00 [1:23:45]: Long video");
    expect(result[0].timestamp).toBe("1:23:45");
  });

  it("handles non-SPEAKER_ raw IDs", () => {
    const result = parseSpeakerTranscript("host [0:00]: Welcome");
    expect(result).toHaveLength(1);
    expect(result[0].rawId).toBe("host");
    expect(result[0].label).toBe("A");
  });

  it("assigns labels beyond Z using multi-char labels", () => {
    const lines = Array.from({ length: 27 }, (_, i) =>
      `S${String(i).padStart(2, "0")}: Turn ${i}`
    ).join("\n");

    const result = parseSpeakerTranscript(lines);
    expect(result[0].label).toBe("A");
    expect(result[25].label).toBe("Z");
    expect(result[26].label).toBe("AA");
  });

  it("preserves all color fields (bg, text, border)", () => {
    const result = parseSpeakerTranscript("SPEAKER_00: Hello");
    expect(result[0].color).toHaveProperty("bg");
    expect(result[0].color).toHaveProperty("text");
    expect(result[0].color).toHaveProperty("border");
    expect(result[0].color.bg).toMatch(/^bg-/);
    expect(result[0].color.text).toMatch(/^text-/);
    expect(result[0].color.border).toMatch(/^border-/);
  });
});

describe("getUniqueSpeakers", () => {
  it("returns empty map for empty turns", () => {
    expect(getUniqueSpeakers([])).toEqual(new Map());
  });

  it("returns unique speakers with their colors", () => {
    const turns: SpeakerTurn[] = [
      { rawId: "SPEAKER_00", label: "A", color: { bg: "bg-blue-100", text: "text-blue-700", border: "border-blue-300" }, text: "Hi", timestamp: null },
      { rawId: "SPEAKER_01", label: "B", color: { bg: "bg-rose-100", text: "text-rose-700", border: "border-rose-300" }, text: "Hey", timestamp: null },
      { rawId: "SPEAKER_00", label: "A", color: { bg: "bg-blue-100", text: "text-blue-700", border: "border-blue-300" }, text: "Again", timestamp: null },
    ];

    const speakers = getUniqueSpeakers(turns);
    expect(speakers.size).toBe(2);
    expect(speakers.has("A")).toBe(true);
    expect(speakers.has("B")).toBe(true);
    expect(speakers.get("A")!.bg).toBe("bg-blue-100");
  });
});
