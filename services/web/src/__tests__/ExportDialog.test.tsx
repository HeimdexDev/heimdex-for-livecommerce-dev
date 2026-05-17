import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { ExportDialog } from "@/features/videos/components/ExportDialog";

describe("ExportDialog", () => {
  it("renders form fields when open", () => {
    render(
      <ExportDialog
        isOpen={true}
        onClose={vi.fn()}
        onExport={vi.fn()}
        selectedCount={2}
        isExporting={false}
        defaultProjectName="Spring Campaign Shorts"
      />,
    );

    expect(screen.getByText("Premiere Pro 내보내기")).toBeInTheDocument();
    expect(screen.getByLabelText("프로젝트 이름")).toBeInTheDocument();
    expect(screen.getByLabelText("저장 위치")).toBeInTheDocument();
    expect(screen.getByLabelText("프레임 레이트")).toBeInTheDocument();
    expect(screen.getByText(/2개 선택됨/)).toBeInTheDocument();
  });

  it("export button disabled when project name empty", async () => {
    const user = userEvent.setup();
    render(
      <ExportDialog
        isOpen={true}
        onClose={vi.fn()}
        onExport={vi.fn()}
        selectedCount={2}
        isExporting={false}
        defaultProjectName="Spring Campaign Shorts"
      />,
    );

    await user.clear(screen.getByLabelText("프로젝트 이름"));
    expect(screen.getByRole("button", { name: "내보내기" })).toBeDisabled();
  });

  it("export button disabled when output dir empty", async () => {
    const user = userEvent.setup();
    render(
      <ExportDialog
        isOpen={true}
        onClose={vi.fn()}
        onExport={vi.fn()}
        selectedCount={2}
        isExporting={false}
        defaultProjectName="Spring Campaign Shorts"
      />,
    );

    await user.clear(screen.getByLabelText("저장 위치"));
    expect(screen.getByRole("button", { name: "내보내기" })).toBeDisabled();
  });

  it("calls onExport with form values when export clicked", async () => {
    const user = userEvent.setup();
    const onExport = vi.fn();
    render(
      <ExportDialog
        isOpen={true}
        onClose={vi.fn()}
        onExport={onExport}
        selectedCount={2}
        isExporting={false}
        defaultProjectName="Spring Campaign Shorts"
      />,
    );

    await user.selectOptions(screen.getByLabelText("프레임 레이트"), "30");
    await user.click(screen.getByRole("button", { name: "내보내기" }));

    expect(onExport).toHaveBeenCalledWith({
      projectName: "Spring Campaign Shorts",
      outputDir: "~/Desktop/Heimdex Exports",
      frameRate: 30,
    });
  });

  it("closes on cancel click", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <ExportDialog
        isOpen={true}
        onClose={onClose}
        onExport={vi.fn()}
        selectedCount={2}
        isExporting={false}
        defaultProjectName="Spring Campaign Shorts"
      />,
    );

    await user.click(screen.getByRole("button", { name: "취소" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("does not render when isOpen is false", () => {
    const { container } = render(
      <ExportDialog
        isOpen={false}
        onClose={vi.fn()}
        onExport={vi.fn()}
        selectedCount={2}
        isExporting={false}
        defaultProjectName="Spring Campaign Shorts"
      />,
    );

    expect(container.innerHTML).toBe("");
  });
});
