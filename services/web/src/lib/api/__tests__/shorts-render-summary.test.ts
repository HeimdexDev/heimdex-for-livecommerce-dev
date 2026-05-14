/**
 * Tests for generateRenderJobSummary — the API client for
 * POST /api/shorts/render/{job_id}/summary (migration 059 / per-short
 * summary). Mocks global fetch; asserts URL, body shaping, and error
 * surfacing.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { generateRenderJobSummary } from "../shorts-render";

const getToken = () => Promise.resolve("test-token");

const OK_BODY = {
  render_job_id: "job-1",
  summary: "글로우 마스크팩의 보습 효과를 강조하는 쇼츠.",
  prompt_version: "v1",
  model: "gpt-4o-mini",
  cost_usd: 0.00038,
  generated_at: "2026-05-14T00:00:00Z",
};

function mockFetchOnce(opts: { ok: boolean; status?: number; body: unknown }) {
  return vi.fn().mockResolvedValueOnce({
    ok: opts.ok,
    status: opts.status ?? (opts.ok ? 200 : 500),
    json: async () => opts.body,
  });
}

describe("generateRenderJobSummary", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("POSTs to the summary endpoint and returns the parsed response", async () => {
    const fetchMock = mockFetchOnce({ ok: true, body: OK_BODY });
    vi.stubGlobal("fetch", fetchMock);

    const result = await generateRenderJobSummary("job-1", getToken);

    expect(result).toEqual(OK_BODY);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/shorts/render/job-1/summary");
    expect(init.method).toBe("POST");
    expect(init.headers["Authorization"]).toBe("Bearer test-token");
  });

  it("omits the body when max_sentences is not provided", async () => {
    const fetchMock = mockFetchOnce({ ok: true, body: OK_BODY });
    vi.stubGlobal("fetch", fetchMock);

    await generateRenderJobSummary("job-1", getToken);

    expect(fetchMock.mock.calls[0][1].body).toBeUndefined();
  });

  it("sends max_sentences in the body when provided", async () => {
    const fetchMock = mockFetchOnce({ ok: true, body: OK_BODY });
    vi.stubGlobal("fetch", fetchMock);

    await generateRenderJobSummary("job-1", getToken, 4);

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      max_sentences: 4,
    });
  });

  it("throws the backend detail message on a non-ok response", async () => {
    const fetchMock = mockFetchOnce({
      ok: false,
      status: 503,
      body: { detail: "shorts_render_summary disabled" },
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      generateRenderJobSummary("job-1", getToken),
    ).rejects.toThrow("shorts_render_summary disabled");
  });

  it("falls back to a status-coded message when the error body has no detail", async () => {
    const fetchMock = mockFetchOnce({ ok: false, status: 409, body: {} });
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      generateRenderJobSummary("job-1", getToken),
    ).rejects.toThrow("(409)");
  });
});
