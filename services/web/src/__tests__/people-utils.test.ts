import { describe, it, expect } from "vitest";
import { splitByLabel } from "@/lib/people-utils";
import type { PersonResponse } from "@/lib/types/people";

function makePerson(id: string, label: string | null): PersonResponse {
  return {
    person_cluster_id: id,
    label,
    face_count: 1,
    last_seen_scene_time: null,
    representative_video_id: null,
    representative_scene_id: null,
    is_excluded: false,
  };
}

describe("splitByLabel", () => {
  it("returns empty arrays for empty input", () => {
    const result = splitByLabel([]);
    expect(result.labelled).toEqual([]);
    expect(result.unlabelled).toEqual([]);
  });

  it("puts all labelled people in labelled array", () => {
    const people = [makePerson("a", "Alice"), makePerson("b", "Bob")];
    const result = splitByLabel(people);
    expect(result.labelled).toHaveLength(2);
    expect(result.unlabelled).toHaveLength(0);
  });

  it("puts all unlabelled people in unlabelled array", () => {
    const people = [makePerson("a", null), makePerson("b", null)];
    const result = splitByLabel(people);
    expect(result.labelled).toHaveLength(0);
    expect(result.unlabelled).toHaveLength(2);
  });

  it("splits mixed people correctly", () => {
    const people = [
      makePerson("a", null),
      makePerson("b", "Bob"),
      makePerson("c", null),
      makePerson("d", "Diana"),
    ];
    const result = splitByLabel(people);
    expect(result.labelled).toHaveLength(2);
    expect(result.labelled[0].label).toBe("Bob");
    expect(result.labelled[1].label).toBe("Diana");
    expect(result.unlabelled).toHaveLength(2);
    expect(result.unlabelled[0].person_cluster_id).toBe("a");
    expect(result.unlabelled[1].person_cluster_id).toBe("c");
  });

  it("preserves order within each group", () => {
    const people = [
      makePerson("1", "Zoe"),
      makePerson("2", null),
      makePerson("3", "Amy"),
      makePerson("4", null),
    ];
    const result = splitByLabel(people);
    expect(result.labelled.map(p => p.person_cluster_id)).toEqual(["1", "3"]);
    expect(result.unlabelled.map(p => p.person_cluster_id)).toEqual(["2", "4"]);
  });
});
