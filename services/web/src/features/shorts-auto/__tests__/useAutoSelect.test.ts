import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";

import { useAutoSelect } from "../hooks/useAutoSelect";
import { AutoShortsRateLimitError } from "@/lib/api/shorts-auto";

async function getToken() {
  return "tok";
}

const originalFetch = global.fetch;

beforeEach(() => {
  vi.resetAllMocks();
});

afterEach(() => {
  global.fetch = originalFetch;
});

describe("useAutoSelect", () => {
  it("starts idle", () => {
    const { result } = renderHook(() => useAutoSelect(getToken));
    expect(result.current.isLoading).toBe(false);
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it("sets loading then data on success", async () => {
    const response = {
      video_id: "vid",
      mode: "both" as const,
      clips: [],
      total_duration_ms: 0,
      skipped_reason: null,
    };
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => response,
    }) as unknown as typeof fetch;

    const { result } = renderHook(() => useAutoSelect(getToken));
    await act(async () => {
      await result.current.mutate({ video_id: "vid", mode: "both" });
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
      expect(result.current.data).toEqual(response);
      expect(result.current.error).toBeNull();
    });
  });

  it("preserves rate-limit error subclass", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 429,
      json: async () => ({ detail: "slow down" }),
    }) as unknown as typeof fetch;

    const { result } = renderHook(() => useAutoSelect(getToken));
    await act(async () => {
      await result.current.mutate({ video_id: "v", mode: "both" });
    });

    await waitFor(() => {
      expect(result.current.error).toBeInstanceOf(AutoShortsRateLimitError);
      expect(result.current.data).toBeNull();
      expect(result.current.isLoading).toBe(false);
    });
  });

  it("reset() clears state", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ video_id: "v", mode: "both", clips: [], total_duration_ms: 0, skipped_reason: null }),
    }) as unknown as typeof fetch;

    const { result } = renderHook(() => useAutoSelect(getToken));
    await act(async () => {
      await result.current.mutate({ video_id: "v", mode: "both" });
    });
    expect(result.current.data).not.toBeNull();

    act(() => result.current.reset());
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeNull();
    expect(result.current.isLoading).toBe(false);
  });
});
