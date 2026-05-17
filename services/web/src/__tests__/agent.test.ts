import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { checkAgentHealth, getAgentPlaybackUrl } from "@/lib/agent";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

describe("agent utilities", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("checkAgentHealth returns AgentHealth on 200 OK", async () => {
    const payload = {
      status: "ok",
      version: "1.0.0",
      uptime_s: 12,
      device_id: "dev-1",
    };

    mockFetch.mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue(payload),
    });

    await expect(checkAgentHealth()).resolves.toEqual(payload);
    expect(mockFetch).toHaveBeenCalledWith("http://127.0.0.1:8787/health", {
      signal: expect.any(AbortSignal),
    });
  });

  it("checkAgentHealth returns null on network error", async () => {
    mockFetch.mockRejectedValue(new Error("network down"));

    await expect(checkAgentHealth()).resolves.toBeNull();
  });

  it("checkAgentHealth returns null on non-200 response", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      json: vi.fn(),
    });

    await expect(checkAgentHealth()).resolves.toBeNull();
  });

  it("checkAgentHealth returns null on timeout abort", async () => {
    vi.useFakeTimers();

    mockFetch.mockImplementation(
      (_url: string, init?: { signal?: AbortSignal }) =>
        new Promise((_, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("Request aborted", "AbortError"));
          });
        })
    );

    const healthPromise = checkAgentHealth();
    await vi.advanceTimersByTimeAsync(600);

    await expect(healthPromise).resolves.toBeNull();
  });

  it("getAgentPlaybackUrl builds correct URL", () => {
    expect(getAgentPlaybackUrl("video-123")).toBe(
      "http://127.0.0.1:8787/playback/file?file_id=video-123"
    );
  });

  it("getAgentPlaybackUrl encodes special characters", () => {
    expect(getAgentPlaybackUrl("video id/1?x=y&z")).toBe(
      "http://127.0.0.1:8787/playback/file?file_id=video%20id%2F1%3Fx%3Dy%26z"
    );
  });

  it("getAgentPlaybackUrl appends media fragment for startMs", () => {
    expect(getAgentPlaybackUrl("video-1", 5000)).toBe(
      "http://127.0.0.1:8787/playback/file?file_id=video-1#t=5.0"
    );
  });

  it("getAgentPlaybackUrl omits fragment for startMs=0", () => {
    expect(getAgentPlaybackUrl("video-1", 0)).toBe(
      "http://127.0.0.1:8787/playback/file?file_id=video-1"
    );
  });

  it("getAgentPlaybackUrl omits fragment when startMs undefined", () => {
    expect(getAgentPlaybackUrl("video-1")).toBe(
      "http://127.0.0.1:8787/playback/file?file_id=video-1"
    );
  });

  it("getAgentPlaybackUrl formats fractional seconds correctly", () => {
    expect(getAgentPlaybackUrl("video-1", 1500)).toBe(
      "http://127.0.0.1:8787/playback/file?file_id=video-1#t=1.5"
    );
  });
});
