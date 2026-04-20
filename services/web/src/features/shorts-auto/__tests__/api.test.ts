import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AutoShortsFeatureDisabledError,
  AutoShortsRateLimitError,
  AutoShortsValidationError,
  postAutoRender,
  postAutoSelect,
  probeAutoShortsAvailability,
} from "@/lib/api/shorts-auto";

const originalFetch = global.fetch;

function mockFetchOnce(status: number, body: unknown): ReturnType<typeof vi.fn> {
  const json = vi.fn().mockResolvedValue(body);
  const mock = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json,
  });
  global.fetch = mock as unknown as typeof fetch;
  return mock;
}

async function getToken() {
  return "fake-token";
}

beforeEach(() => {
  vi.resetAllMocks();
});

afterEach(() => {
  global.fetch = originalFetch;
});

describe("postAutoSelect", () => {
  it("posts to /api/shorts/auto-select with auth header + body", async () => {
    const mock = mockFetchOnce(200, {
      video_id: "vid",
      mode: "both",
      clips: [],
      total_duration_ms: 0,
      skipped_reason: null,
    });

    await postAutoSelect({ video_id: "vid", mode: "both" }, getToken);

    expect(mock).toHaveBeenCalledTimes(1);
    const [url, init] = mock.mock.calls[0];
    expect(String(url)).toContain("/api/shorts/auto-select");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer fake-token");
    expect(JSON.parse(init.body as string)).toMatchObject({ video_id: "vid", mode: "both" });
  });

  it("throws AutoShortsRateLimitError on 429", async () => {
    mockFetchOnce(429, { detail: "too fast" });
    await expect(postAutoSelect({ video_id: "v", mode: "both" }, getToken)).rejects.toBeInstanceOf(
      AutoShortsRateLimitError,
    );
  });

  it("throws AutoShortsFeatureDisabledError on 404", async () => {
    mockFetchOnce(404, { detail: "Not Found" });
    await expect(postAutoSelect({ video_id: "v", mode: "both" }, getToken)).rejects.toBeInstanceOf(
      AutoShortsFeatureDisabledError,
    );
  });

  it("throws AutoShortsValidationError on 422", async () => {
    mockFetchOnce(422, { detail: "insufficient qualifying clips" });
    await expect(postAutoSelect({ video_id: "v", mode: "both" }, getToken)).rejects.toBeInstanceOf(
      AutoShortsValidationError,
    );
  });

  it("throws generic Error on 500", async () => {
    mockFetchOnce(500, { detail: "boom" });
    await expect(postAutoSelect({ video_id: "v", mode: "both" }, getToken)).rejects.toThrow(/boom/);
  });
});

describe("postAutoRender", () => {
  it("posts to /api/shorts/auto-render", async () => {
    const mock = mockFetchOnce(201, {
      id: "job-1",
      video_id: "vid",
      status: "queued",
    });
    await postAutoRender({ video_id: "vid", mode: "both" }, getToken);
    const [url] = mock.mock.calls[0];
    expect(String(url)).toContain("/api/shorts/auto-render");
  });

  it("surfaces 422 detail in error message", async () => {
    mockFetchOnce(422, { detail: "insufficient qualifying clips: requested 5, found 2" });
    await expect(postAutoRender({ video_id: "v", mode: "both" }, getToken)).rejects.toThrow(
      /insufficient/,
    );
  });
});

describe("probeAutoShortsAvailability", () => {
  it("returns false when backend 404s", async () => {
    mockFetchOnce(404, { detail: "Not Found" });
    await expect(probeAutoShortsAvailability(getToken)).resolves.toBe(false);
  });

  it("returns true when backend 422s (feature live, bad body)", async () => {
    mockFetchOnce(422, { detail: "validation" });
    await expect(probeAutoShortsAvailability(getToken)).resolves.toBe(true);
  });

  it("returns true on 500 — treat as available to avoid hiding CTAs", async () => {
    mockFetchOnce(500, { detail: "boom" });
    await expect(probeAutoShortsAvailability(getToken)).resolves.toBe(true);
  });

  it("returns true on network error — treat as available", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("network")) as unknown as typeof fetch;
    await expect(probeAutoShortsAvailability(getToken)).resolves.toBe(true);
  });
});
