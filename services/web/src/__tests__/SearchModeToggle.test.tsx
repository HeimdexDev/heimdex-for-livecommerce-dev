import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { SearchModeToggle } from "@/features/search/components/SearchModeToggle";
import type { SearchMode } from "@/lib/types/search";

describe("SearchModeToggle", () => {
  const MODES: { key: SearchMode; label: string }[] = [
    { key: "metadata", label: "파일 검색" },
    { key: "lexical", label: "내용 검색" },
    { key: "semantic", label: "의미 검색" },
  ];

  it("renders all three mode buttons", () => {
    render(<SearchModeToggle value="lexical" onChange={() => {}} />);
    for (const { label } of MODES) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("renders a radiogroup with correct aria-label", () => {
    render(<SearchModeToggle value="lexical" onChange={() => {}} />);
    const group = screen.getByRole("radiogroup", { name: "검색 모드" });
    expect(group).toBeInTheDocument();
  });

  it("renders radio buttons with aria-checked reflecting active mode", () => {
    render(<SearchModeToggle value="semantic" onChange={() => {}} />);
    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(3);

    // metadata = unchecked, lexical = unchecked, semantic = checked
    expect(radios[0]).toHaveAttribute("aria-checked", "false");
    expect(radios[1]).toHaveAttribute("aria-checked", "false");
    expect(radios[2]).toHaveAttribute("aria-checked", "true");
  });

  it("marks the correct button as active for each mode", () => {
    for (const { key } of MODES) {
      const { unmount } = render(
        <SearchModeToggle value={key} onChange={() => {}} />,
      );
      const radios = screen.getAllByRole("radio");
      const activeIndex = MODES.findIndex((m) => m.key === key);
      for (let i = 0; i < radios.length; i++) {
        expect(radios[i]).toHaveAttribute(
          "aria-checked",
          String(i === activeIndex),
        );
      }
      unmount();
    }
  });

  it("calls onChange with correct mode when clicking each button", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();

    render(<SearchModeToggle value="lexical" onChange={onChange} />);

    await user.click(screen.getByText("파일 검색"));
    expect(onChange).toHaveBeenCalledWith("metadata");

    await user.click(screen.getByText("의미 검색"));
    expect(onChange).toHaveBeenCalledWith("semantic");

    await user.click(screen.getByText("내용 검색"));
    expect(onChange).toHaveBeenCalledWith("lexical");

    expect(onChange).toHaveBeenCalledTimes(3);
  });

  it("renders question mark help icons on each pill", () => {
    render(<SearchModeToggle value="lexical" onChange={() => {}} />);
    const helpIcons = screen.getAllByText("?");
    expect(helpIcons).toHaveLength(3);
  });

  it("renders tooltip elements with description text", () => {
    render(<SearchModeToggle value="lexical" onChange={() => {}} />);
    const tooltips = screen.getAllByRole("tooltip");
    expect(tooltips).toHaveLength(3);
  });

  it("provides aria-label with mode name for screen readers", () => {
    render(<SearchModeToggle value="lexical" onChange={() => {}} />);
    const radios = screen.getAllByRole("radio");

    expect(radios[0]).toHaveAttribute("aria-label", "파일 검색");
    expect(radios[1]).toHaveAttribute("aria-label", "내용 검색");
    expect(radios[2]).toHaveAttribute("aria-label", "의미 검색");
  });

  it("renders emoji icons", () => {
    render(<SearchModeToggle value="lexical" onChange={() => {}} />);
    expect(screen.getByText("📋")).toBeInTheDocument();
    expect(screen.getByText("📝")).toBeInTheDocument();
    expect(screen.getByText("🧠")).toBeInTheDocument();
  });

  it("all buttons have type='button' to prevent form submission", () => {
    render(<SearchModeToggle value="lexical" onChange={() => {}} />);
    const radios = screen.getAllByRole("radio");
    for (const radio of radios) {
      expect(radio).toHaveAttribute("type", "button");
    }
  });
});
