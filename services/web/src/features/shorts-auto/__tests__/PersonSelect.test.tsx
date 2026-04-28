import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { PersonSelect } from "../components/PersonSelect";
import { getVideoPeople } from "@/lib/api/videos";

// IMPORTANT: stable getAccessToken reference. If we returned a fresh
// function on every render, useVideoPeople's [videoId, getToken] effect
// would refire each render → infinite loop → vitest worker timeout.
// Discovered after the new ``useVideoPeople`` hook landed in PR 3.
// vi.mock is hoisted and can't capture module-level closures, so the
// stable function lives inside the factory.
vi.mock("@/lib/auth", () => {
  const stableGetAccessToken = async () => "tok";
  return {
    useAuth: () => ({ getAccessToken: stableGetAccessToken }),
  };
});

vi.mock("@/lib/api/videos", () => ({
  getVideoPeople: vi.fn(),
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
  (getVideoPeople as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
    video_id: "vid",
    people,
    total: people.length,
  });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("PersonSelect", () => {
  it("renders closed with placeholder when no value", () => {
    render(<PersonSelect videoId="vid" value={null} onChange={() => {}} />);
    expect(screen.getByRole("combobox")).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("인물을 선택해 주세요")).toBeInTheDocument();
  });

  it("calls getVideoPeople with the videoId on mount", async () => {
    render(<PersonSelect videoId="vid" value={null} onChange={() => {}} />);
    await waitFor(() => expect(getVideoPeople).toHaveBeenCalledTimes(1));
    expect(getVideoPeople).toHaveBeenCalledWith("vid", expect.any(Function));
  });

  it("filters by label search", async () => {
    render(<PersonSelect videoId="vid" value={null} onChange={() => {}} />);
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
    render(<PersonSelect videoId="vid" value={null} onChange={onChange} />);
    fireEvent.click(screen.getByRole("combobox"));
    await waitFor(() => expect(screen.getByText("호스트")).toBeInTheDocument());

    fireEvent.click(screen.getByText("호스트"));
    expect(onChange).toHaveBeenCalledWith("p1");
  });

  it("shows video-scoped empty state when this video has no people", async () => {
    (getVideoPeople as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      video_id: "vid",
      people: [],
      total: 0,
    });
    render(<PersonSelect videoId="vid" value={null} onChange={() => {}} />);
    fireEvent.click(screen.getByRole("combobox"));
    await waitFor(() =>
      expect(
        screen.getByText("이 영상에 등장하는 인물이 없습니다"),
      ).toBeInTheDocument(),
    );
  });

  it("renders error message when fetch fails", async () => {
    (getVideoPeople as unknown as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error("network"),
    );
    render(<PersonSelect videoId="vid" value={null} onChange={() => {}} />);
    fireEvent.click(screen.getByRole("combobox"));
    await waitFor(() =>
      expect(
        screen.getByText("인물 목록을 불러오지 못했습니다."),
      ).toBeInTheDocument(),
    );
  });
});
