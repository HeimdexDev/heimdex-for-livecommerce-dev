import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SelectionTray, MAX_TRAY_VISIBLE } from "@/features/people/components/SelectionTray";
import type { PersonResponse } from "@/lib/types";

vi.mock("@/lib/agent", () => ({
  getFaceThumbnailUrl: vi.fn((id: string) => `http://test/face/${id}`),
  getCloudThumbnailUrl: vi.fn((vid: string, sid: string) => `http://test/scene/${vid}/${sid}`),
}));

function makePerson(index: number): PersonResponse {
  return {
    person_cluster_id: `cluster_${index}`,
    label: `Person ${index}`,
    face_count: index + 1,
    is_excluded: false,
    last_seen_scene_time: null,
    representative_video_id: `vid_${index}`,
    representative_scene_id: `scene_${index}`,
    matched_video_titles: [],
  };
}

const noop = () => {};

const defaultProps = {
  agentAvailable: true,
  onRemove: noop,
  onSelectAll: noop,
  onMerge: noop,
  onDelete: noop,
  onClear: noop,
};

describe("SelectionTray", () => {
  it("renders a thumbnail for each selected person", () => {
    const people = [makePerson(1), makePerson(2), makePerson(3)];
    const { container } = render(
      <SelectionTray selectedPeople={people} {...defaultProps} />
    );
    const images = container.querySelectorAll("img");
    expect(images.length).toBe(3);
  });

  it("shows correct count text", () => {
    const people = [makePerson(1), makePerson(2)];
    render(<SelectionTray selectedPeople={people} {...defaultProps} />);
    expect(screen.getByText("2명 선택됨")).toBeTruthy();
  });

  it("does NOT show merge/delete buttons when only 1 person selected", () => {
    const people = [makePerson(1)];
    render(<SelectionTray selectedPeople={people} {...defaultProps} />);
    expect(screen.queryByText("병합")).toBeNull();
    expect(screen.queryByText("삭제")).toBeNull();
  });

  it("shows merge/delete buttons when 2+ people selected", () => {
    const people = [makePerson(1), makePerson(2)];
    render(<SelectionTray selectedPeople={people} {...defaultProps} />);
    expect(screen.getByText("병합")).toBeTruthy();
    expect(screen.getByText("삭제")).toBeTruthy();
  });

  it("shows overflow badge when more than MAX_TRAY_VISIBLE selected", () => {
    const people = Array.from({ length: MAX_TRAY_VISIBLE + 3 }, (_, i) =>
      makePerson(i)
    );
    render(<SelectionTray selectedPeople={people} {...defaultProps} />);
    const badge = screen.getByTestId("overflow-badge");
    expect(badge.textContent).toBe("+3");
  });

  it("does NOT show overflow badge when at or below MAX_TRAY_VISIBLE", () => {
    const people = Array.from({ length: MAX_TRAY_VISIBLE }, (_, i) =>
      makePerson(i)
    );
    render(<SelectionTray selectedPeople={people} {...defaultProps} />);
    expect(screen.queryByTestId("overflow-badge")).toBeNull();
  });

  it("calls onRemove with person_cluster_id when × button clicked", () => {
    const onRemove = vi.fn();
    const people = [makePerson(1)];
    render(
      <SelectionTray selectedPeople={people} {...defaultProps} onRemove={onRemove} />
    );
    const removeBtn = screen.getByLabelText("Person 1 선택 해제");
    fireEvent.click(removeBtn);
    expect(onRemove).toHaveBeenCalledWith("cluster_1");
    expect(onRemove).toHaveBeenCalledTimes(1);
  });

  it("calls onClear when 취소 clicked", () => {
    const onClear = vi.fn();
    const people = [makePerson(1)];
    render(
      <SelectionTray selectedPeople={people} {...defaultProps} onClear={onClear} />
    );
    fireEvent.click(screen.getByText("취소"));
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("calls onMerge when 병합 clicked", () => {
    const onMerge = vi.fn();
    const people = [makePerson(1), makePerson(2)];
    render(
      <SelectionTray selectedPeople={people} {...defaultProps} onMerge={onMerge} />
    );
    fireEvent.click(screen.getByText("병합"));
    expect(onMerge).toHaveBeenCalledTimes(1);
  });

  it("calls onDelete when 삭제 clicked", () => {
    const onDelete = vi.fn();
    const people = [makePerson(1), makePerson(2)];
    render(
      <SelectionTray selectedPeople={people} {...defaultProps} onDelete={onDelete} />
    );
    fireEvent.click(screen.getByText("삭제"));
    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it("calls onSelectAll when 전체 선택 clicked", () => {
    const onSelectAll = vi.fn();
    const people = [makePerson(1)];
    render(
      <SelectionTray selectedPeople={people} {...defaultProps} onSelectAll={onSelectAll} />
    );
    fireEvent.click(screen.getByText("전체 선택"));
    expect(onSelectAll).toHaveBeenCalledTimes(1);
  });

  it("uses aria-label fallback for unlabeled person", () => {
    const unlabeled: PersonResponse = {
      ...makePerson(1),
      label: null,
    };
    render(
      <SelectionTray selectedPeople={[unlabeled]} {...defaultProps} />
    );
    expect(screen.getByLabelText("인물 선택 해제")).toBeTruthy();
  });
});
