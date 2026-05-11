import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { SubtitleSceneHeader } from "../components/SubtitleSceneHeader";

describe("SubtitleSceneHeader", () => {
  it("renders the scene label, HH:MM:SS range, and duration", () => {
    render(
      <SubtitleSceneHeader sceneIndex={3} startMs={62_000} endMs={70_000} />,
    );
    const root = screen.getByTestId("subtitle-scene-header-3");
    expect(root.textContent).toContain("장면3");
    expect(root.textContent).toContain("00:01:02");
    expect(root.textContent).toContain("00:01:10");
    expect(root.textContent).toContain("8초");
  });

  it("renders the cue count badge when provided", () => {
    render(
      <SubtitleSceneHeader
        sceneIndex={1}
        startMs={0}
        endMs={5000}
        cueCount={4}
      />,
    );
    expect(screen.getByTestId("scene-header-cue-count").textContent).toBe(
      "4자막",
    );
  });

  it("omits the badge when cueCount is undefined", () => {
    render(
      <SubtitleSceneHeader sceneIndex={1} startMs={0} endMs={5000} />,
    );
    expect(
      screen.queryByTestId("scene-header-cue-count"),
    ).not.toBeInTheDocument();
  });
});
