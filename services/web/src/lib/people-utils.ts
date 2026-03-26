import type { PersonResponse } from "@/lib/types/people";

export interface SortedPeopleGroups {
  labelled: PersonResponse[];
  unlabelled: PersonResponse[];
}

/**
 * Split people into labelled (with label) and unlabelled (no label) groups.
 * Each group preserves the original order from the API.
 *
 * Used by VideoPeoplePanel and PeopleSettings to display labelled faces
 * on top, separated from unlabelled faces by a visual divider.
 */
export function splitByLabel(people: PersonResponse[]): SortedPeopleGroups {
  const labelled: PersonResponse[] = [];
  const unlabelled: PersonResponse[] = [];
  for (const person of people) {
    if (person.label) {
      labelled.push(person);
    } else {
      unlabelled.push(person);
    }
  }
  return { labelled, unlabelled };
}
