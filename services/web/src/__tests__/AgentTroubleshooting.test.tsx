import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { AgentTroubleshooting } from "@/features/search/components/AgentTroubleshooting";

describe("AgentTroubleshooting", () => {
  it("renders warning message", () => {
    render(<AgentTroubleshooting onRetry={vi.fn()} />);
    expect(
      screen.getByText("Heimdex Agent is not responding")
    ).toBeInTheDocument();
  });

  it("renders agent URL", () => {
    render(<AgentTroubleshooting onRetry={vi.fn()} />);
    expect(screen.getByText("http://127.0.0.1:8787")).toBeInTheDocument();
  });

  it("renders troubleshooting checklist", () => {
    render(<AgentTroubleshooting onRetry={vi.fn()} />);
    expect(
      screen.getByText("Check that the Heimdex agent process is running")
    ).toBeInTheDocument();
    expect(
      screen.getByText("Verify no firewall is blocking port 8787")
    ).toBeInTheDocument();
    expect(
      screen.getByText("Try restarting the agent application")
    ).toBeInTheDocument();
  });

  it("calls onRetry when retry button clicked", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(<AgentTroubleshooting onRetry={onRetry} />);

    await user.click(screen.getByRole("button", { name: /retry connection/i }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
