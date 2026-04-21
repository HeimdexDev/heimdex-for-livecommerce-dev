import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { PersonSelect } from "../components/PersonSelect";
import { getPeople } from "@/lib/api/people";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ getAccessToken: async () => "tok" }),
}));

vi.mock("@/lib/api/people", () => ({
  getPeople: vi.fn(),
}));

vi.mock("@/lib/agent", () => ({
  getFaceThumbnailUrl: (id: string) => `/face/${id}`,
}));

vi.mock("@/components/icons", () => ({
  PersonIcon: () => <svg data-testid="person-icon" />,
}));

const people = [
  { person_cluster_id: "p1", label: "호스트", face_count: 10 },
  { person_cluster_id: "p2", label: "게스트", face_count: 3 },
  { person_cluster_id: "p3", label: null, face_count: 1 },
];

beforeEach(() => {
  (getPeople as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ people });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("PersonSelect", () => {
  it("renders closed with placeholder when no value", () => {
    render(<PersonSelect value={null} onChange={() => {}} />);
    expect(screen.getByRole("combobox")).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("인물을 선택해 주세요")).toBeInTheDocument();
  });

  it("lazy-fetches people only on first open", async () => {
    render(<PersonSelect value={null} onChange={() => {}} />);
    expect(getPeople).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("combobox"));
    await waitFor(() => expect(getPeople).toHaveBeenCalledTimes(1));

    // Close then reopen — should NOT refetch
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(screen.getByRole("combobox"));
    await waitFor(() => expect(screen.getByText("호스트")).toBeInTheDocument());
    expect(getPeople).toHaveBeenCalledTimes(1);
  });

  it("filters by label search", async () => {
    render(<PersonSelect value={null} onChange={() => {}} />);
    fireEvent.click(screen.getByRole("combobox"));
    await waitFor(() => expect(screen.getByText("호스트")).toBeInTheDocument());

    const searchInput = screen.getByPlaceholderText("인물 검색...");
    fireEvent.change(searchInput, { target: { value: "게스" } });

    await waitFor(() => {
      expect(screen.queryByText("호스트")).not.toBeInTheDocument();
      expect(screen.getByText("게스트")).toBeInTheDocument();
    });
  });

  it("selects an option on click", async () => {
    const onChange = vi.fn();
    render(<PersonSelect value={null} onChange={onChange} />);
    fireEvent.click(screen.getByRole("combobox"));
    await waitFor(() => expect(screen.getByText("호스트")).toBeInTheDocument());

    fireEvent.click(screen.getByText("호스트"));
    expect(onChange).toHaveBeenCalledWith("p1");
  });

  it("supports keyboard navigation and Enter selection", async () => {
    const onChange = vi.fn();
    render(<PersonSelect value={null} onChange={onChange} />);
    fireEvent.click(screen.getByRole("combobox"));
    await waitFor(() => expect(screen.getByText("호스트")).toBeInTheDocument());

    const searchInput = screen.getByPlaceholderText("인물 검색...");
    fireEvent.keyDown(searchInput, { key: "ArrowDown" });
    fireEvent.keyDown(searchInput, { key: "ArrowDown" });
    fireEvent.keyDown(searchInput, { key: "Enter" });

    expect(onChange).toHaveBeenCalledWith("p2");
  });

  it("shows empty state when no people", async () => {
    (getPeople as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ people: [] });
    render(<PersonSelect value={null} onChange={() => {}} />);
    fireEvent.click(screen.getByRole("combobox"));
    await waitFor(() => expect(screen.getByText("등록된 인물이 없습니다")).toBeInTheDocument());
  });

  it("shows error state when fetch fails", async () => {
    (getPeople as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("fail"));
    render(<PersonSelect value={null} onChange={() => {}} />);
    fireEvent.click(screen.getByRole("combobox"));
    await waitFor(() => expect(screen.getByText(/인물 목록을 불러오지 못했습니다/)).toBeInTheDocument());
  });

  it("retry button clears error and refetches", async () => {
    const mockGetPeople = getPeople as unknown as ReturnType<typeof vi.fn>;
    mockGetPeople.mockRejectedValueOnce(new Error("fail"));
    render(<PersonSelect value={null} onChange={() => {}} />);
    fireEvent.click(screen.getByRole("combobox"));
    await waitFor(() => expect(screen.getByText(/인물 목록을 불러오지 못했습니다/)).toBeInTheDocument());

    // Second attempt succeeds
    mockGetPeople.mockResolvedValueOnce({ people });
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    await waitFor(() => expect(screen.getByText("호스트")).toBeInTheDocument());
    expect(mockGetPeople).toHaveBeenCalledTimes(2);
  });

  it("is disabled when disabled prop is set", () => {
    render(<PersonSelect value={null} onChange={() => {}} disabled />);
    expect(screen.getByRole("combobox")).toBeDisabled();
  });
});
