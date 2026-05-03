import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { LengthSelector } from "../components/LengthSelector";

describe("LengthSelector", () => {
  it("renders all five presets", () => {
    render(<LengthSelector value={60} onChange={vi.fn()} />);
    [15, 30, 60, 90, 120].forEach((preset) => {
      expect(screen.getByTestId(`length-preset-${preset}`)).toBeInTheDocument();
    });
  });

  it("highlights the active preset", () => {
    render(<LengthSelector value={30} onChange={vi.fn()} />);
    const active = screen.getByTestId("length-preset-30");
    expect(active.className).toMatch(/bg-indigo-500/);
    const inactive = screen.getByTestId("length-preset-60");
    expect(inactive.className).not.toMatch(/bg-indigo-500/);
  });

  it("fires onChange with the chosen preset", () => {
    const onChange = vi.fn();
    render(<LengthSelector value={60} onChange={onChange} />);
    fireEvent.click(screen.getByTestId("length-preset-90"));
    expect(onChange).toHaveBeenCalledWith(90);
  });

  it("clamps custom input to 10..120", () => {
    const onChange = vi.fn();
    render(<LengthSelector value={60} onChange={onChange} />);
    const input = screen.getByTestId("length-custom-input");
    fireEvent.change(input, { target: { value: "5" } });
    expect(onChange).toHaveBeenLastCalledWith(10);
    fireEvent.change(input, { target: { value: "999" } });
    expect(onChange).toHaveBeenLastCalledWith(120);
    fireEvent.change(input, { target: { value: "75" } });
    expect(onChange).toHaveBeenLastCalledWith(75);
  });

  it("ignores non-numeric input gracefully", () => {
    const onChange = vi.fn();
    render(<LengthSelector value={60} onChange={onChange} />);
    fireEvent.change(screen.getByTestId("length-custom-input"), {
      target: { value: "abc" },
    });
    expect(onChange).not.toHaveBeenCalled();
  });
});
