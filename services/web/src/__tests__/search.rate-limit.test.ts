/**
 * search.ts 429 → SearchRateLimitError coverage.
 *
 * Pairs with the backend ``test_search_rate_limit.py`` — backend emits
 * 429 + Retry-After; this test locks in that the client turns that
 * envelope into a typed error the hook layer can branch on.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { search, searchScenes, SearchRateLimitError } from "@/lib/api/search";
import { ApiError } from "@/lib/types";

const originalFetch = global.fetch;

function mockFetchOnce(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): ReturnType<typeof vi.fn> {
  const json = vi.fn().mockResolvedValue(body);
  const mock = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    headers: {
      get: (name: string) => headers[name] ?? null,
    },
    json,
  });
  global.fetch = mock as unknown as typeof fetch;
  return mock;
}

async function getToken() {
  return "tok";
}

beforeEach(() => {
  vi.resetAllMocks();
});

afterEach(() => {
  global.fetch = originalFetch;
});

describe("search() 429 handling", () => {
  it("throws SearchRateLimitError with parsed Retry-After seconds", async () => {
    mockFetchOnce(
      429,
      { detail: "slow down" },
      { "Retry-After": "45" },
    );

    await expect(
      search({ q: "센트룸", alpha: 0.5, filters: {} }, getToken),
    ).rejects.toMatchObject({
      name: "SearchRateLimitError",
      isRateLimit: true,
      status: 429,
      retryAfterSeconds: 45,
    });
  });

  it("defaults Retry-After to 60s when the header is missing", async () => {
    mockFetchOnce(429, { detail: "slow down" });
    await expect(search({ q: "q", alpha: 0.5, filters: {} }, getToken)).rejects.toMatchObject({
      retryAfterSeconds: 60,
    });
  });

  it("defaults Retry-After to 60s when the header is not a positive number", async () => {
    mockFetchOnce(429, { detail: "slow down" }, { "Retry-After": "garbage" });
    await expect(search({ q: "q", alpha: 0.5, filters: {} }, getToken)).rejects.toMatchObject({
      retryAfterSeconds: 60,
    });
  });

  it("surfaces backend detail as the error message when present", async () => {
    mockFetchOnce(
      429,
      { detail: "Search rate limit exceeded (60/60s per user)." },
      { "Retry-After": "60" },
    );
    await expect(search({ q: "q", alpha: 0.5, filters: {} }, getToken)).rejects.toThrow(/per user/);
  });

  it("falls back to a generic message when the body has no detail", async () => {
    mockFetchOnce(429, null, { "Retry-After": "30" });
    await expect(search({ q: "q", alpha: 0.5, filters: {} }, getToken)).rejects.toThrow(
      /rate limit/i,
    );
  });

  it("does NOT get swallowed by the catch-all network error wrapper", async () => {
    // Regression guard: the catch block at the bottom of apiRequest
    // wraps unknown errors in ApiError("network", 0, ...). A naive
    // ``if (err instanceof ApiError) throw err`` would re-wrap our
    // typed 429 as a network error.
    mockFetchOnce(429, { detail: "slow down" }, { "Retry-After": "10" });
    await expect(
      search({ q: "q", alpha: 0.5, filters: {} }, getToken),
    ).rejects.toBeInstanceOf(SearchRateLimitError);
  });
});

describe("searchScenes() 429 handling", () => {
  it("also throws SearchRateLimitError (same apiRequest path)", async () => {
    mockFetchOnce(429, { detail: "slow" }, { "Retry-After": "7" });
    await expect(
      searchScenes({ q: "q", alpha: 0.5, filters: {} }, getToken),
    ).rejects.toMatchObject({
      isRateLimit: true,
      retryAfterSeconds: 7,
    });
  });
});

describe("non-429 error paths still go through ApiError", () => {
  it("500 throws ApiError, not SearchRateLimitError", async () => {
    mockFetchOnce(500, { detail: "boom" });
    await expect(search({ q: "q", alpha: 0.5, filters: {} }, getToken)).rejects.toBeInstanceOf(
      ApiError,
    );
  });

  it("network error throws ApiError('network'), not SearchRateLimitError", async () => {
    global.fetch = vi
      .fn()
      .mockRejectedValue(new Error("connection reset")) as unknown as typeof fetch;
    await expect(search({ q: "q", alpha: 0.5, filters: {} }, getToken)).rejects.toBeInstanceOf(
      ApiError,
    );
  });
});
