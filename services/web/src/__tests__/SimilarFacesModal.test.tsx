import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import type { PersonResponse } from "@/lib/types/people";
import type { SimilarPeopleResponse } from "@/lib/types/people";

// Must be declared before the mock factory so the factory can capture the reference
const mockGetSimilarPeople = vi.fn();

vi.mock("@/lib/api/people", () => ({
  getSimilarPeople: (...args: unknown[]) => mockGetSimilarPeople(...args),
  renamePerson: vi.fn(),
  deletePerson: vi.fn(),
  mergePeople: vi.fn(),
}));

vi.mock("@/components/people/AvatarThumbnail", () => ({
  AvatarThumbnail: ({
    person,
    className,
  }: {
    person: { person_cluster_id: string; label: string | null };
    className?: string;
  }) => (
    <div
      data-testid={`avatar-${person.person_cluster_id}`}
      className={className}
    >
      {person.label}
    </div>
  ),
}));

import { SimilarFacesModal } from "@/features/people/components/SimilarFacesModal";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makePerson(
  id: string,
  label: string | null,
  faceCount = 3,
): PersonResponse {
  return {
    person_cluster_id: id,
    label,
    face_count: faceCount,
    last_seen_scene_time: null,
    representative_video_id: "vid-1",
    representative_scene_id: `scene-${id}`,
    is_excluded: false,
  };
}

function makeSimilarResponse(
  targetId: string,
  items: Array<{ id: string; similarity: number }>,
): SimilarPeopleResponse {
  return {
    target_cluster_id: targetId,
    similarities: items.map(({ id, similarity }) => ({
      person_cluster_id: id,
      similarity,
    })),
    total: items.length,
    threshold: 0.5,
  };
}

const mockGetAccessToken = vi.fn().mockResolvedValue("test-token");
const mockOnClose = vi.fn();
const mockOnMerge = vi.fn();

// ---------------------------------------------------------------------------
// Each test uses a unique targetId so the module-level similarCache never
// returns a stale hit from a previous test.
// ---------------------------------------------------------------------------
let testCounter = 0;
function uniqueTargetId(): string {
  return `target-${++testCounter}`;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SimilarFacesModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetSimilarPeople.mockReset();
    mockGetAccessToken.mockResolvedValue("test-token");
  });

  it("renders loading skeleton on mount", () => {
    // Never resolves so the loading state persists throughout this assertion
    mockGetSimilarPeople.mockReturnValue(new Promise(() => {}));

    const targetPerson = makePerson(uniqueTargetId(), "Alice");
    const { container } = render(
      <SimilarFacesModal
        targetPerson={targetPerson}
        people={[]}
        onClose={mockOnClose}
        onMerge={mockOnMerge}
        isMerging={false}
        getAccessToken={mockGetAccessToken}
      />,
    );

    const skeletons = container.querySelectorAll(".animate-pulse");
    // 8 skeleton cards × 2 divs each (avatar placeholder + label placeholder)
    expect(skeletons.length).toBeGreaterThanOrEqual(8);
  });

  it("renders similar faces after fetch", async () => {
    const targetId = uniqueTargetId();
    const people = [
      makePerson("person-a", "Bob", 5),
      makePerson("person-b", "Carol", 2),
      makePerson("person-c", null, 1),
    ];

    mockGetSimilarPeople.mockResolvedValue(
      makeSimilarResponse(targetId, [
        { id: "person-a", similarity: 0.92 },
        { id: "person-b", similarity: 0.75 },
        { id: "person-c", similarity: 0.61 },
      ]),
    );

    render(
      <SimilarFacesModal
        targetPerson={makePerson(targetId, "Alice")}
        people={people}
        onClose={mockOnClose}
        onMerge={mockOnMerge}
        isMerging={false}
        getAccessToken={mockGetAccessToken}
      />,
    );

    await waitFor(() =>
      expect(screen.getByTestId("avatar-person-a")).toBeInTheDocument(),
    );

    expect(screen.getByTestId("avatar-person-b")).toBeInTheDocument();
    expect(screen.getByTestId("avatar-person-c")).toBeInTheDocument();

    // Similarity % badges — use regex to match across potential split text nodes
    expect(screen.getByText(/92%/)).toBeInTheDocument();
    expect(screen.getByText(/75%/)).toBeInTheDocument();
    expect(screen.getByText(/61%/)).toBeInTheDocument();
  });

  it("shows empty state when no similar faces", async () => {
    const targetId = uniqueTargetId();

    mockGetSimilarPeople.mockResolvedValue(
      makeSimilarResponse(targetId, []),
    );

    render(
      <SimilarFacesModal
        targetPerson={makePerson(targetId, "Alice")}
        people={[]}
        onClose={mockOnClose}
        onMerge={mockOnMerge}
        isMerging={false}
        getAccessToken={mockGetAccessToken}
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByText("유사한 인물이 없습니다"),
      ).toBeInTheDocument(),
    );
  });

  it("shows error state on fetch failure", async () => {
    const targetId = uniqueTargetId();

    mockGetSimilarPeople.mockRejectedValue(new Error("network error"));

    render(
      <SimilarFacesModal
        targetPerson={makePerson(targetId, "Alice")}
        people={[]}
        onClose={mockOnClose}
        onMerge={mockOnMerge}
        isMerging={false}
        getAccessToken={mockGetAccessToken}
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByText("유사한 인물을 불러오지 못했습니다."),
      ).toBeInTheDocument(),
    );
  });

  it("toggles individual face selection", async () => {
    const user = userEvent.setup();
    const targetId = uniqueTargetId();
    const people = [makePerson("person-a", "Bob")];

    mockGetSimilarPeople.mockResolvedValue(
      makeSimilarResponse(targetId, [{ id: "person-a", similarity: 0.85 }]),
    );

    const { container } = render(
      <SimilarFacesModal
        targetPerson={makePerson(targetId, "Alice")}
        people={people}
        onClose={mockOnClose}
        onMerge={mockOnMerge}
        isMerging={false}
        getAccessToken={mockGetAccessToken}
      />,
    );

    await waitFor(() =>
      expect(screen.getByTestId("avatar-person-a")).toBeInTheDocument(),
    );

    const card = container.querySelector("button[type=button].group");
    expect(card).not.toBeNull();

    // Not selected initially
    expect(card).not.toHaveClass("ring-2");

    await user.click(card!);
    expect(card).toHaveClass("ring-2");

    await user.click(card!);
    expect(card).not.toHaveClass("ring-2");
  });

  it("select all and deselect all", async () => {
    const user = userEvent.setup();
    const targetId = uniqueTargetId();
    const people = [
      makePerson("person-a", "Bob"),
      makePerson("person-b", "Carol"),
      makePerson("person-c", "Dave"),
    ];

    mockGetSimilarPeople.mockResolvedValue(
      makeSimilarResponse(targetId, [
        { id: "person-a", similarity: 0.9 },
        { id: "person-b", similarity: 0.8 },
        { id: "person-c", similarity: 0.7 },
      ]),
    );

    const { container } = render(
      <SimilarFacesModal
        targetPerson={makePerson(targetId, "Alice")}
        people={people}
        onClose={mockOnClose}
        onMerge={mockOnMerge}
        isMerging={false}
        getAccessToken={mockGetAccessToken}
      />,
    );

    await waitFor(() =>
      expect(screen.getByText("전체 선택")).toBeInTheDocument(),
    );

    await user.click(screen.getByText("전체 선택"));

    const cards = container.querySelectorAll("button[type=button].group");
    expect(cards).toHaveLength(3);
    cards.forEach((card) => expect(card).toHaveClass("ring-2"));

    expect(screen.getByText("전체 해제")).toBeInTheDocument();

    await user.click(screen.getByText("전체 해제"));

    cards.forEach((card) => expect(card).not.toHaveClass("ring-2"));
    expect(screen.getByText("전체 선택")).toBeInTheDocument();
  });

  it("footer is hidden when no faces are selected", async () => {
    const targetId = uniqueTargetId();
    const people = [makePerson("person-a", "Bob")];

    mockGetSimilarPeople.mockResolvedValue(
      makeSimilarResponse(targetId, [{ id: "person-a", similarity: 0.85 }]),
    );

    render(
      <SimilarFacesModal
        targetPerson={makePerson(targetId, "Alice")}
        people={people}
        onClose={mockOnClose}
        onMerge={mockOnMerge}
        isMerging={false}
        getAccessToken={mockGetAccessToken}
      />,
    );

    await waitFor(() =>
      expect(screen.getByTestId("avatar-person-a")).toBeInTheDocument(),
    );

    expect(screen.queryByText("병합하기")).not.toBeInTheDocument();
  });

  it("calls onMerge with correct request", async () => {
    const user = userEvent.setup();
    const targetId = uniqueTargetId();
    const people = [
      makePerson("person-a", "Bob"),
      makePerson("person-b", "Carol"),
    ];

    mockGetSimilarPeople.mockResolvedValue(
      makeSimilarResponse(targetId, [
        { id: "person-a", similarity: 0.9 },
        { id: "person-b", similarity: 0.8 },
      ]),
    );

    mockOnMerge.mockResolvedValue(null);

    const { container } = render(
      <SimilarFacesModal
        targetPerson={makePerson(targetId, "Alice")}
        people={people}
        onClose={mockOnClose}
        onMerge={mockOnMerge}
        isMerging={false}
        getAccessToken={mockGetAccessToken}
      />,
    );

    await waitFor(() =>
      expect(screen.getByTestId("avatar-person-a")).toBeInTheDocument(),
    );

    const cards = container.querySelectorAll("button[type=button].group");
    await user.click(cards[0]);
    await user.click(cards[1]);

    await waitFor(() =>
      expect(screen.getByText("병합하기")).toBeInTheDocument(),
    );

    await user.click(screen.getByText("병합하기"));

    expect(mockOnMerge).toHaveBeenCalledOnce();
    const callArg = mockOnMerge.mock.calls[0][0];
    expect(callArg.target_cluster_id).toBe(targetId);
    expect(callArg.source_cluster_ids).toHaveLength(2);
    expect(callArg.source_cluster_ids).toContain("person-a");
    expect(callArg.source_cluster_ids).toContain("person-b");
  });

  it("closes on escape key", async () => {
    const targetId = uniqueTargetId();

    mockGetSimilarPeople.mockResolvedValue(
      makeSimilarResponse(targetId, []),
    );

    render(
      <SimilarFacesModal
        targetPerson={makePerson(targetId, "Alice")}
        people={[]}
        onClose={mockOnClose}
        onMerge={mockOnMerge}
        isMerging={false}
        getAccessToken={mockGetAccessToken}
      />,
    );

    await waitFor(() =>
      expect(screen.getByText("유사한 인물이 없습니다")).toBeInTheDocument(),
    );

    // The onKeyDown handler is on the modal's outer div (the fixed overlay wrapper)
    const modalOverlay = screen
      .getByText("유사한 인물 찾기")
      .closest(".fixed");
    expect(modalOverlay).not.toBeNull();
    fireEvent.keyDown(modalOverlay!, { key: "Escape" });

    expect(mockOnClose).toHaveBeenCalledOnce();
  });

  it("does not close when merging", async () => {
    const targetId = uniqueTargetId();

    mockGetSimilarPeople.mockResolvedValue(
      makeSimilarResponse(targetId, []),
    );

    render(
      <SimilarFacesModal
        targetPerson={makePerson(targetId, "Alice")}
        people={[]}
        onClose={mockOnClose}
        onMerge={mockOnMerge}
        isMerging={true}
        getAccessToken={mockGetAccessToken}
      />,
    );

    await waitFor(() =>
      expect(screen.getByText("유사한 인물이 없습니다")).toBeInTheDocument(),
    );

    const modalOverlay = screen
      .getByText("유사한 인물 찾기")
      .closest(".fixed");
    expect(modalOverlay).not.toBeNull();
    fireEvent.keyDown(modalOverlay!, { key: "Escape" });

    expect(mockOnClose).not.toHaveBeenCalled();
  });
});
