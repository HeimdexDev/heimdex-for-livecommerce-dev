"use client";

import { useState, useEffect, useCallback } from "react";
import { useAuth } from "@/lib/auth";
import { getPeople, renamePerson as renamePersionApi } from "@/lib/api/people";
import type { PersonResponse } from "@/lib/types";
import { ApiError } from "@/lib/types";

export interface UsePeopleReturn {
  people: PersonResponse[];
  isLoading: boolean;
  error: string | null;
  renamePerson: (personClusterId: string, label: string | null) => Promise<void>;
  isRenaming: boolean;
  fetchPeople: () => Promise<void>;
}

export function usePeople(): UsePeopleReturn {
  const { getAccessToken } = useAuth();

  const [people, setPeople] = useState<PersonResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isRenaming, setIsRenaming] = useState(false);

  const fetchPeopleList = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await getPeople(getAccessToken);
      setPeople(response.people);
    } catch (err) {
      const msg =
        err instanceof ApiError ? err.detail : "Failed to load people";
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, [getAccessToken]);

  const rename = useCallback(
    async (personClusterId: string, label: string | null) => {
      setIsRenaming(true);
      setError(null);
      try {
        await renamePersionApi(personClusterId, label, getAccessToken);
        // Optimistic update
        setPeople((prev) =>
          prev.map((p) =>
            p.person_cluster_id === personClusterId ? { ...p, label } : p,
          ),
        );
      } catch (err) {
        const msg =
          err instanceof ApiError ? err.detail : "Failed to rename person";
        setError(msg);
      } finally {
        setIsRenaming(false);
      }
    },
    [getAccessToken],
  );

  useEffect(() => {
    fetchPeopleList();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    people,
    isLoading,
    error,
    renamePerson: rename,
    isRenaming,
    fetchPeople: fetchPeopleList,
  };
}
