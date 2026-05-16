import { describe, expect, it } from "vitest";

import { friendlyParentError } from "../pages/WizardStepResult";

describe("friendlyParentError", () => {
  it("maps proxy_missing to a transcode-not-ready Korean message", () => {
    const out = friendlyParentError(
      "proxy_missing",
      "DriveFile abc has no proxy_s3_key — transcode incomplete",
    );
    // Domain-specific message — does not surface the raw file_id.
    expect(out).toContain("트랜스코딩");
    expect(out).not.toContain("DriveFile");
    expect(out).not.toContain("proxy_s3_key");
  });

  it("falls back to raw code+message for unknown error codes", () => {
    // Locks the contract that NEW backend error codes surface
    // visibly (raw) so a missed mapping is loud, not silent.
    const out = friendlyParentError("internal_error", "boom");
    expect(out).toBe("오류: internal_error — boom");
  });

  it("falls back to just the code when message is null", () => {
    expect(friendlyParentError("internal_error", null)).toBe(
      "오류: internal_error",
    );
  });
});
