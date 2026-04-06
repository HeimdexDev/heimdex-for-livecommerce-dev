"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useAuth } from "@/lib/auth";
import {
  getPeople,
  renamePerson as renamePersionApi,
  deletePerson as deletePersonApi,
  mergePeople as mergePeopleApi,
  getExcludePreferences,
  saveExcludePreferences,
  bulkDeletePeople,
} from "@/lib/api/people";
import type { PersonResponse, MergePersonRequest, MergePersonResponse } from "@/lib/types";
import { ApiError } from "@/lib/types";

export interface UsePeopleReturn {
  people: PersonResponse[];
  isLoading: boolean;
  error: string | null;
  renamePerson: (personClusterId: string, label: string | null) => Promise<void>;
  isRenaming: boolean;
  fetchPeople: (query?: string) => Promise<void>;
  excludedIds: Set<string>;
  toggleExclude: (personClusterId: string) => void;
  isSavingExcludes: boolean;
  selectedIds: Set<string>;
  toggleSelection: (personClusterId: string) => void;
  selectAll: () => void;
  clearSelection: () => void;
  bulkDelete: (ids: string[]) => Promise<void>;
  deletePerson: (personClusterId: string) => Promise<void>;
  isDeleting: boolean;
  mergePeople: (request: MergePersonRequest) => Promise<MergePersonResponse | null>;
  isMerging: boolean;
  dateFrom: string | null;
  dateTo: string | null;
  setDateRange: (from: string | null, to: string | null) => void;
}

export function usePeople(): UsePeopleReturn {
  const { getAccessToken } = useAuth();

  const [people, setPeople] = useState<PersonResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isRenaming, setIsRenaming] = useState(false);
  const [excludedIds, setExcludedIds] = useState<Set<string>>(new Set());
  const [isSavingExcludes, setIsSavingExcludes] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [isDeleting, setIsDeleting] = useState(false);
  const [isMerging, setIsMerging] = useState(false);
  const [dateFrom, setDateFrom] = useState<string | null>(null);
  const [dateTo, setDateTo] = useState<string | null>(null);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latestExcludedRef = useRef<Set<string>>(new Set());
  const latestDateRef = useRef<{ from: string | null; to: string | null }>({ from: null, to: null });

  const fetchPeopleList = useCallback(async (query?: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const dateOpts = {
        dateFrom: latestDateRef.current.from,
        dateTo: latestDateRef.current.to,
      };
      const [peopleRes, excludeRes] = await Promise.all([
        getPeople(getAccessToken, query, dateOpts),
        getExcludePreferences(getAccessToken),
      ]);
      setPeople(peopleRes.people);
      const excluded = new Set(excludeRes.excluded_person_cluster_ids);
      setExcludedIds(excluded);
      latestExcludedRef.current = excluded;
    } catch (err) {
      const msg =
        err instanceof ApiError ? err.detail : "Failed to load people";
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, [getAccessToken]);

  const persistExcludes = useCallback(
    async (ids: Set<string>) => {
      setIsSavingExcludes(true);
      try {
        await saveExcludePreferences(Array.from(ids), getAccessToken);
      } catch (err) {
        const msg =
          err instanceof ApiError
            ? err.detail
            : "Failed to save exclude preferences";
        setError(msg);
      } finally {
        setIsSavingExcludes(false);
      }
    },
    [getAccessToken],
  );

  const toggleExclude = useCallback(
    (personClusterId: string) => {
      setExcludedIds((prev) => {
        const next = new Set(prev);
        if (next.has(personClusterId)) {
          next.delete(personClusterId);
        } else {
          next.add(personClusterId);
        }
        latestExcludedRef.current = next;

        if (saveTimerRef.current) {
          clearTimeout(saveTimerRef.current);
        }
        saveTimerRef.current = setTimeout(() => {
          persistExcludes(latestExcludedRef.current);
        }, 500);

        return next;
      });
    },
    [persistExcludes],
  );

  const toggleSelection = useCallback((personClusterId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(personClusterId)) {
        next.delete(personClusterId);
      } else {
        next.add(personClusterId);
      }
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setSelectedIds(new Set(people.map((p) => p.person_cluster_id)));
  }, [people]);

  const clearSelection = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  const bulkDelete = useCallback(
    async (ids: string[]) => {
      setIsDeleting(true);
      setError(null);
      try {
        await bulkDeletePeople({ person_cluster_ids: ids }, getAccessToken);
        setPeople((prev) =>
          prev.filter((p) => !ids.includes(p.person_cluster_id)),
        );
        setSelectedIds((prev) => {
          const next = new Set(prev);
          ids.forEach((id) => next.delete(id));
          return next;
        });
        setExcludedIds((prev) => {
          const next = new Set(prev);
          ids.forEach((id) => next.delete(id));
          latestExcludedRef.current = next;
          return next;
        });
      } catch (err) {
        const msg =
          err instanceof ApiError ? err.detail : "인물 일괄 삭제에 실패했습니다.";
        setError(msg);
      } finally {
        setIsDeleting(false);
      }
    },
    [getAccessToken],
  );

  const rename = useCallback(
    async (personClusterId: string, label: string | null) => {
      setIsRenaming(true);
      setError(null);
      try {
        await renamePersionApi(personClusterId, label, getAccessToken);
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

  const remove = useCallback(
    async (personClusterId: string) => {
      setIsDeleting(true);
      setError(null);
      try {
        await deletePersonApi(personClusterId, getAccessToken);
        setPeople((prev) =>
          prev.filter((p) => p.person_cluster_id !== personClusterId),
        );
        setExcludedIds((prev) => {
          const next = new Set(prev);
          next.delete(personClusterId);
          latestExcludedRef.current = next;
          return next;
        });
        setSelectedIds((prev) => {
          const next = new Set(prev);
          next.delete(personClusterId);
          return next;
        });
      } catch (err) {
        const msg =
          err instanceof ApiError ? err.detail : "인물 삭제에 실패했습니다.";
        setError(msg);
      } finally {
        setIsDeleting(false);
      }
    },
    [getAccessToken],
  );

  const merge = useCallback(
    async (request: MergePersonRequest): Promise<MergePersonResponse | null> => {
      setIsMerging(true);
      setError(null);
      try {
        const response = await mergePeopleApi(request, getAccessToken);
        // Optimistic: remove source clusters and update target label immediately
        const sourceIds = new Set(response.merged_source_ids);
        setPeople((prev) => {
          const updated = prev.filter(
            (p) => !sourceIds.has(p.person_cluster_id),
          );
          return updated.map((p) =>
            p.person_cluster_id === response.target_cluster_id
              ? { ...p, label: response.label }
              : p,
          );
        });
        // Prune stale selectedIds — remove any IDs that no longer exist
        // (source clusters were merged away)
        setSelectedIds((prev) => {
          const next = new Set(prev);
          sourceIds.forEach((id) => next.delete(id));
          return next;
        });
        // Refetch full people list to get updated face_count,
        // representative scenes, and other server-computed fields
        // that the merge response doesn't include.
        fetchPeopleList().catch(() => {});
        return response;
      } catch (err) {
        const msg =
          err instanceof ApiError ? err.detail : "인물 병합에 실패했습니다.";
        setError(msg);
        return null;
      } finally {
        setIsMerging(false);
      }
    },
    [getAccessToken, fetchPeopleList],
  );

  const setDateRange = useCallback(
    (from: string | null, to: string | null) => {
      setDateFrom(from);
      setDateTo(to);
      latestDateRef.current = { from, to };
      fetchPeopleList();
    },
    [fetchPeopleList],
  );

  useEffect(() => {
    fetchPeopleList();
    return () => {
      if (saveTimerRef.current) {
        clearTimeout(saveTimerRef.current);
      }
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    people,
    isLoading,
    error,
    renamePerson: rename,
    isRenaming,
    fetchPeople: fetchPeopleList,
    excludedIds,
    toggleExclude,
    isSavingExcludes,
    selectedIds,
    toggleSelection,
    selectAll,
    clearSelection,
    bulkDelete,
    deletePerson: remove,
    isDeleting,
    mergePeople: merge,
    isMerging,
    dateFrom,
    dateTo,
    setDateRange,
  };
}
