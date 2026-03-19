import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { DisableFolderConfirmDialog } from "@/components/sync/DisableFolderConfirmDialog";
import { FolderRow } from "@/components/sync/FolderRow";
import { FolderSyncTree } from "@/components/sync/FolderSyncTree";
import type { WatchedFolder, DriveInfo, ContentType } from "@/lib/types/drive";

function makeFolder(overrides?: Partial<WatchedFolder>): WatchedFolder {
  return {
    id: "folder-1",
    google_folder_id: "gf-1",
    folder_name: "Test Folder",
    folder_path: "/Test Folder",
    parent_folder_id: null,
    sync_enabled: false,
    content_types: ["video"],
    file_count_cached: 0,
    connection_id: "conn-1",
    ...overrides,
  };
}

function makeDrive(overrides?: Partial<DriveInfo>): DriveInfo {
  return {
    connection_id: "conn-1",
    drive_id: "drive-1",
    drive_name: "Test Drive",
    scope_type: "shared_drive",
    ...overrides,
  };
}

describe("DisableFolderConfirmDialog", () => {
  it("renders nothing when not open", () => {
    const { container } = render(
      <DisableFolderConfirmDialog
        isOpen={false}
        folderName="Test Folder"
        fileCount={100}
        isDisabling={false}
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("renders warning with folder name", () => {
    render(
      <DisableFolderConfirmDialog
        isOpen={true}
        folderName="My Videos"
        fileCount={50}
        isDisabling={false}
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.getByText("동기화를 해제할까요?")).toBeInTheDocument();
    expect(screen.getByText(/My Videos/)).toBeInTheDocument();
    expect(screen.getByText(/50개/)).toBeInTheDocument();
  });

  it("confirm button calls onConfirm", async () => {
    const onConfirm = vi.fn();
    const user = userEvent.setup();

    render(
      <DisableFolderConfirmDialog
        isOpen={true}
        folderName="Test Folder"
        fileCount={100}
        isDisabling={false}
        onCancel={vi.fn()}
        onConfirm={onConfirm}
      />,
    );

    await user.click(screen.getByText("동기화 해제"));
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("cancel button calls onCancel", async () => {
    const onCancel = vi.fn();
    const user = userEvent.setup();

    render(
      <DisableFolderConfirmDialog
        isOpen={true}
        folderName="Test Folder"
        fileCount={100}
        isDisabling={false}
        onCancel={onCancel}
        onConfirm={vi.fn()}
      />,
    );

    await user.click(screen.getByText("취소"));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("buttons disabled while disabling", () => {
    render(
      <DisableFolderConfirmDialog
        isOpen={true}
        folderName="Test Folder"
        fileCount={100}
        isDisabling={true}
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );

    const buttons = screen.getAllByRole("button");
    const cancelButton = buttons.find((btn) => btn.textContent?.includes("취소"));
    const confirmButton = buttons.find((btn) => btn.textContent?.includes("해제"));

    expect(cancelButton).toBeDisabled();
    expect(confirmButton).toBeDisabled();
  });

  it("handles null folder name with default text", () => {
    render(
      <DisableFolderConfirmDialog
        isOpen={true}
        folderName={null}
        fileCount={25}
        isDisabling={false}
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );

    expect(screen.getByText(/이 폴더/)).toBeInTheDocument();
  });
});

describe("FolderRow", () => {
  it("renders folder name", () => {
    render(
      <FolderRow
        folder={makeFolder({ folder_name: "My Videos" })}
        depth={0}
        hasChildren={false}
        isExpanded={false}
        isToggling={false}
        onToggle={vi.fn()}
        onExpand={vi.fn()}
        onContentTypeChange={vi.fn()}
      />,
    );

    expect(screen.getByText("My Videos")).toBeInTheDocument();
  });

  it("checkbox reflects sync_enabled", () => {
    const { rerender } = render(
      <FolderRow
        folder={makeFolder({ sync_enabled: false })}
        depth={0}
        hasChildren={false}
        isExpanded={false}
        isToggling={false}
        onToggle={vi.fn()}
        onExpand={vi.fn()}
        onContentTypeChange={vi.fn()}
      />,
    );

    const checkbox = screen.getByRole("checkbox");
    expect(checkbox).not.toBeChecked();

    rerender(
      <FolderRow
        folder={makeFolder({ sync_enabled: true })}
        depth={0}
        hasChildren={false}
        isExpanded={false}
        isToggling={false}
        onToggle={vi.fn()}
        onExpand={vi.fn()}
        onContentTypeChange={vi.fn()}
      />,
    );

    expect(checkbox).toBeChecked();
  });

  it("content type selector visible when enabled", () => {
    render(
      <FolderRow
        folder={makeFolder({ sync_enabled: true, content_types: ["video"] })}
        depth={0}
        hasChildren={false}
        isExpanded={false}
        isToggling={false}
        onToggle={vi.fn()}
        onExpand={vi.fn()}
        onContentTypeChange={vi.fn()}
      />,
    );

    const select = screen.getByDisplayValue("동영상");
    expect(select).toBeInTheDocument();
  });

  it("content type selector hidden when disabled", () => {
    render(
      <FolderRow
        folder={makeFolder({ sync_enabled: false })}
        depth={0}
        hasChildren={false}
        isExpanded={false}
        isToggling={false}
        onToggle={vi.fn()}
        onExpand={vi.fn()}
        onContentTypeChange={vi.fn()}
      />,
    );

    expect(screen.queryByDisplayValue("동영상")).not.toBeInTheDocument();
  });

  it("expand button visible with children", () => {
    const { container } = render(
      <FolderRow
        folder={makeFolder()}
        depth={0}
        hasChildren={true}
        isExpanded={false}
        isToggling={false}
        onToggle={vi.fn()}
        onExpand={vi.fn()}
        onContentTypeChange={vi.fn()}
      />,
    );

    const expandButton = container.querySelector("button[aria-label='펼치기']");
    expect(expandButton).toBeInTheDocument();
    expect(expandButton).not.toHaveClass("invisible");
  });

  it("expand button invisible without children", () => {
    const { container } = render(
      <FolderRow
        folder={makeFolder()}
        depth={0}
        hasChildren={false}
        isExpanded={false}
        isToggling={false}
        onToggle={vi.fn()}
        onExpand={vi.fn()}
        onContentTypeChange={vi.fn()}
      />,
    );

    const expandButton = container.querySelector("button[aria-label='펼치기']");
    expect(expandButton).toHaveClass("invisible");
  });

  it("calls onToggle when checkbox clicked", async () => {
    const onToggle = vi.fn();
    const user = userEvent.setup();

    render(
      <FolderRow
        folder={makeFolder({ sync_enabled: false })}
        depth={0}
        hasChildren={false}
        isExpanded={false}
        isToggling={false}
        onToggle={onToggle}
        onExpand={vi.fn()}
        onContentTypeChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("checkbox"));
    expect(onToggle).toHaveBeenCalledOnce();
  });

  it("calls onExpand when expand button clicked", async () => {
    const onExpand = vi.fn();
    const user = userEvent.setup();

    const { container } = render(
      <FolderRow
        folder={makeFolder()}
        depth={0}
        hasChildren={true}
        isExpanded={false}
        isToggling={false}
        onToggle={vi.fn()}
        onExpand={onExpand}
        onContentTypeChange={vi.fn()}
      />,
    );

    const expandButton = container.querySelector("button[aria-label='펼치기']");
    await user.click(expandButton!);
    expect(onExpand).toHaveBeenCalledOnce();
  });

  it("calls onContentTypeChange when select changes", async () => {
    const onContentTypeChange = vi.fn();
    const user = userEvent.setup();

    render(
      <FolderRow
        folder={makeFolder({ sync_enabled: true, content_types: ["video"] })}
        depth={0}
        hasChildren={false}
        isExpanded={false}
        isToggling={false}
        onToggle={vi.fn()}
        onExpand={vi.fn()}
        onContentTypeChange={onContentTypeChange}
      />,
    );

    const select = screen.getByDisplayValue("동영상");
    await user.selectOptions(select, "image");
    expect(onContentTypeChange).toHaveBeenCalledWith(["image"]);
  });

  it("displays file count when greater than zero", () => {
    render(
      <FolderRow
        folder={makeFolder({ file_count_cached: 42 })}
        depth={0}
        hasChildren={false}
        isExpanded={false}
        isToggling={false}
        onToggle={vi.fn()}
        onExpand={vi.fn()}
        onContentTypeChange={vi.fn()}
      />,
    );

    expect(screen.getByText("42개")).toBeInTheDocument();
  });

  it("hides file count when zero", () => {
    render(
      <FolderRow
        folder={makeFolder({ file_count_cached: 0 })}
        depth={0}
        hasChildren={false}
        isExpanded={false}
        isToggling={false}
        onToggle={vi.fn()}
        onExpand={vi.fn()}
        onContentTypeChange={vi.fn()}
      />,
    );

    expect(screen.queryByText(/개$/)).not.toBeInTheDocument();
  });

  it("checkbox disabled while toggling", () => {
    render(
      <FolderRow
        folder={makeFolder()}
        depth={0}
        hasChildren={false}
        isExpanded={false}
        isToggling={true}
        onToggle={vi.fn()}
        onExpand={vi.fn()}
        onContentTypeChange={vi.fn()}
      />,
    );

    const checkbox = screen.getByRole("checkbox");
    expect(checkbox).toBeDisabled();
  });

  it("applies correct padding based on depth", () => {
    const { container } = render(
      <FolderRow
        folder={makeFolder()}
        depth={2}
        hasChildren={false}
        isExpanded={false}
        isToggling={false}
        onToggle={vi.fn()}
        onExpand={vi.fn()}
        onContentTypeChange={vi.fn()}
      />,
    );

    const row = container.querySelector("div.flex.items-center.gap-2");
    expect(row).toHaveStyle("padding-left: 60px");
  });
});

describe("FolderSyncTree", () => {
  it("renders empty state when no trees", () => {
    render(
      <FolderSyncTree
        folders={[]}
        drives={[]}
        onToggle={vi.fn()}
        onContentTypeChange={vi.fn()}
        onRefresh={vi.fn()}
        isRefreshing={false}
      />,
    );

    expect(
      screen.getByText(/폴더를 불러오려면.*새로고침.*버튼을 눌러주세요/),
    ).toBeInTheDocument();
  });

  it("renders drive section header", () => {
    const drive = makeDrive({ drive_name: "My Drive", scope_type: "my_drive" });
    const folder = makeFolder({ connection_id: drive.connection_id });

    render(
      <FolderSyncTree
        folders={[folder]}
        drives={[drive]}
        onToggle={vi.fn()}
        onContentTypeChange={vi.fn()}
        onRefresh={vi.fn()}
        isRefreshing={false}
      />,
    );

    expect(screen.getByText("내 드라이브")).toBeInTheDocument();
  });

  it("renders shared drive name correctly", () => {
    const drive = makeDrive({
      drive_name: "Team Drive",
      scope_type: "shared_drive",
    });
    const folder = makeFolder({ connection_id: drive.connection_id });

    render(
      <FolderSyncTree
        folders={[folder]}
        drives={[drive]}
        onToggle={vi.fn()}
        onContentTypeChange={vi.fn()}
        onRefresh={vi.fn()}
        isRefreshing={false}
      />,
    );

    expect(screen.getByText("Team Drive")).toBeInTheDocument();
  });

  it("renders folder rows under drive", () => {
    const drive = makeDrive();
    const folder1 = makeFolder({
      id: "f1",
      folder_name: "Folder 1",
      connection_id: drive.connection_id,
    });
    const folder2 = makeFolder({
      id: "f2",
      folder_name: "Folder 2",
      connection_id: drive.connection_id,
    });

    render(
      <FolderSyncTree
        folders={[folder1, folder2]}
        drives={[drive]}
        onToggle={vi.fn()}
        onContentTypeChange={vi.fn()}
        onRefresh={vi.fn()}
        isRefreshing={false}
      />,
    );

    expect(screen.getByText("Folder 1")).toBeInTheDocument();
    expect(screen.getByText("Folder 2")).toBeInTheDocument();
  });

  it("refresh button calls onRefresh", async () => {
    const onRefresh = vi.fn();
    const user = userEvent.setup();

    render(
      <FolderSyncTree
        folders={[]}
        drives={[]}
        onToggle={vi.fn()}
        onContentTypeChange={vi.fn()}
        onRefresh={onRefresh}
        isRefreshing={false}
      />,
    );

    await user.click(screen.getByText("새로고침"));
    expect(onRefresh).toHaveBeenCalledOnce();
  });

  it("refresh button disabled while refreshing", () => {
    render(
      <FolderSyncTree
        folders={[]}
        drives={[]}
        onToggle={vi.fn()}
        onContentTypeChange={vi.fn()}
        onRefresh={vi.fn()}
        isRefreshing={true}
      />,
    );

    const refreshButton = screen.getByText("불러오는 중...");
    expect(refreshButton).toBeDisabled();
  });

  it("shows enabled folder count badge", () => {
    const drive = makeDrive();
    const folder1 = makeFolder({
      id: "f1",
      sync_enabled: true,
      connection_id: drive.connection_id,
    });
    const folder2 = makeFolder({
      id: "f2",
      sync_enabled: true,
      connection_id: drive.connection_id,
    });
    const folder3 = makeFolder({
      id: "f3",
      sync_enabled: false,
      connection_id: drive.connection_id,
    });

    render(
      <FolderSyncTree
        folders={[folder1, folder2, folder3]}
        drives={[drive]}
        onToggle={vi.fn()}
        onContentTypeChange={vi.fn()}
        onRefresh={vi.fn()}
        isRefreshing={false}
      />,
    );

    expect(screen.getByText("2개 폴더 동기화 중")).toBeInTheDocument();
  });

  it("hides badge when no folders enabled", () => {
    const drive = makeDrive();
    const folder = makeFolder({
      sync_enabled: false,
      connection_id: drive.connection_id,
    });

    render(
      <FolderSyncTree
        folders={[folder]}
        drives={[drive]}
        onToggle={vi.fn()}
        onContentTypeChange={vi.fn()}
        onRefresh={vi.fn()}
        isRefreshing={false}
      />,
    );

    expect(screen.queryByText(/개 폴더 동기화 중/)).not.toBeInTheDocument();
  });

  it("toggles drive section expansion", async () => {
    const drive = makeDrive();
    const folder = makeFolder({ connection_id: drive.connection_id });
    const user = userEvent.setup();

    render(
      <FolderSyncTree
        folders={[folder]}
        drives={[drive]}
        onToggle={vi.fn()}
        onContentTypeChange={vi.fn()}
        onRefresh={vi.fn()}
        isRefreshing={false}
      />,
    );

    expect(screen.getByText("Test Folder")).toBeInTheDocument();

    const driveButton = screen.getByText("Test Drive");
    await user.click(driveButton);

    await waitFor(() => {
      expect(screen.queryByText("Test Folder")).not.toBeInTheDocument();
    });
  });

  it("calls onToggle when folder checkbox clicked", async () => {
    const onToggle = vi.fn();
    const user = userEvent.setup();
    const drive = makeDrive();
    const folder = makeFolder({
      sync_enabled: false,
      connection_id: drive.connection_id,
    });

    render(
      <FolderSyncTree
        folders={[folder]}
        drives={[drive]}
        onToggle={onToggle}
        onContentTypeChange={vi.fn()}
        onRefresh={vi.fn()}
        isRefreshing={false}
      />,
    );

    const checkbox = screen.getByRole("checkbox");
    await user.click(checkbox);

    await waitFor(() => {
      expect(onToggle).toHaveBeenCalled();
    });
  });

  it("shows disable confirmation dialog when disabling enabled folder", async () => {
    const onToggle = vi.fn();
    const user = userEvent.setup();
    const drive = makeDrive();
    const folder = makeFolder({
      sync_enabled: true,
      connection_id: drive.connection_id,
    });

    render(
      <FolderSyncTree
        folders={[folder]}
        drives={[drive]}
        onToggle={onToggle}
        onContentTypeChange={vi.fn()}
        onRefresh={vi.fn()}
        isRefreshing={false}
      />,
    );

    const checkbox = screen.getByRole("checkbox");
    await user.click(checkbox);

    await waitFor(() => {
      expect(screen.getByText("동기화를 해제할까요?")).toBeInTheDocument();
    });
  });

  it("calls onToggle with correct params when confirming disable", async () => {
    const onToggle = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    const drive = makeDrive();
    const folder = makeFolder({
      id: "folder-123",
      sync_enabled: true,
      connection_id: drive.connection_id,
    });

    render(
      <FolderSyncTree
        folders={[folder]}
        drives={[drive]}
        onToggle={onToggle}
        onContentTypeChange={vi.fn()}
        onRefresh={vi.fn()}
        isRefreshing={false}
      />,
    );

    const checkbox = screen.getByRole("checkbox");
    await user.click(checkbox);

    await waitFor(() => {
      expect(screen.getByText("동기화를 해제할까요?")).toBeInTheDocument();
    });

    await user.click(screen.getByText("동기화 해제"));

    await waitFor(() => {
      expect(onToggle).toHaveBeenCalledWith("folder-123", false);
    });
  });

  it("calls onContentTypeChange when content type changed", async () => {
    const onContentTypeChange = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    const drive = makeDrive();
    const folder = makeFolder({
      id: "folder-123",
      sync_enabled: true,
      content_types: ["video"],
      connection_id: drive.connection_id,
    });

    render(
      <FolderSyncTree
        folders={[folder]}
        drives={[drive]}
        onToggle={vi.fn()}
        onContentTypeChange={onContentTypeChange}
        onRefresh={vi.fn()}
        isRefreshing={false}
      />,
    );

    const select = screen.getByDisplayValue("동영상");
    await user.selectOptions(select, "image");

    await waitFor(() => {
      expect(onContentTypeChange).toHaveBeenCalledWith("folder-123", ["image"]);
    });
  });

  it("renders nested folder hierarchy", async () => {
    const drive = makeDrive();
    const parentFolder = makeFolder({
      id: "parent",
      google_folder_id: "gf-parent",
      folder_name: "Parent",
      parent_folder_id: null,
      connection_id: drive.connection_id,
    });
    const childFolder = makeFolder({
      id: "child",
      folder_name: "Child",
      parent_folder_id: "gf-parent",
      connection_id: drive.connection_id,
    });

    const user = userEvent.setup();

    render(
      <FolderSyncTree
        folders={[parentFolder, childFolder]}
        drives={[drive]}
        onToggle={vi.fn()}
        onContentTypeChange={vi.fn()}
        onRefresh={vi.fn()}
        isRefreshing={false}
      />,
    );

    expect(screen.getByText("Parent")).toBeInTheDocument();

    const expandButtons = screen.getAllByRole("button", { name: /펼치기|접기/ });
    await user.click(expandButtons[0]);

    await waitFor(() => {
      expect(screen.getByText("Child")).toBeInTheDocument();
    });
  });

  it("handles multiple drives", () => {
    const drive1 = makeDrive({
      connection_id: "conn-1",
      drive_name: "Drive 1",
    });
    const drive2 = makeDrive({
      connection_id: "conn-2",
      drive_name: "Drive 2",
    });
    const folder1 = makeFolder({
      id: "f1",
      folder_name: "Folder 1",
      connection_id: "conn-1",
    });
    const folder2 = makeFolder({
      id: "f2",
      folder_name: "Folder 2",
      connection_id: "conn-2",
    });

    render(
      <FolderSyncTree
        folders={[folder1, folder2]}
        drives={[drive1, drive2]}
        onToggle={vi.fn()}
        onContentTypeChange={vi.fn()}
        onRefresh={vi.fn()}
        isRefreshing={false}
      />,
    );

    expect(screen.getByText("Drive 1")).toBeInTheDocument();
    expect(screen.getByText("Drive 2")).toBeInTheDocument();
    expect(screen.getByText("Folder 1")).toBeInTheDocument();
    expect(screen.getByText("Folder 2")).toBeInTheDocument();
  });
});
