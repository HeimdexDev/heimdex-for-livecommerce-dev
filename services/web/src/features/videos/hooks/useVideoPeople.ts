"use client";

import { useState, useEffect, useCallback } from "react";
import { useAuth } from "@/lib/auth";
import { getVideoPeople } from "@/lib/api/videos";
import { renamePerson as renamePersonApi, deletePerson as deletePersonApi } from "@/lib/api/people";
import type { PersonResponse } from "@/lib/types";
import { ApiError } from "@/lib/types";

export interface UseVideoPeopleReturn {
  people: PersonResponse[];
  isLoading: boolean;
  error: string | null;
  renamePerson: (personClusterId: string, label: string | null) => Promise<void>;
  isRenaming: boolean;
  deletePerson: (personClusterId: string) => Promise<void>;
  isDeleting: boolean;
  refetch: () => Promise<void>;
}

export function useVideoPeople(videoId: string): UseVideoPeopleReturn {
  const { getAccessToken } = useAuth();

  const [people, setPeople] = useState<PersonResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isRenaming, setIsRenaming] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  const fetchPeople = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await getVideoPeople(videoId, getAccessToken);
      setPeople(res.people);
    } catch (err) {
      const msg = err instanceof ApiError ? err.detail : "인물 정보를 불러올 수 없습니다.";
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, [videoId, getAccessToken]);

  useEffect(() => {
    let cancelled = false;

    setIsLoading(true);
    setError(null);

    getVideoPeople(videoId, getAccessToken)
      .then((res) => {
        if (!cancelled) {
          setPeople(res.people);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          const msg = err instanceof ApiError ? err.detail : "인물 정보를 불러올 수 없습니다.";
          setError(msg);
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [videoId, getAccessToken]);

  const rename = useCallback(
    async (personClusterId: string, label: string | null) => {
      setIsRenaming(true);
      setError(null);
      try {
        await renamePersonApi(personClusterId, label, getAccessToken);
        setPeople((prev) =>
          prev.map((p) =>
            p.person_cluster_id === personClusterId ? { ...p, label } : p,
          ),
        );
      } catch (err) {
        const msg = err instanceof ApiError ? err.detail : "이름 변경에 실패했습니다.";
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
      } catch (err) {
        const msg = err instanceof ApiError ? err.detail : "인물 삭제에 실패했습니다.";
        setError(msg);
      } finally {
        setIsDeleting(false);
      }
    },
    [getAccessToken],
  );

  return {
    people,
    isLoading,
    error,
    renamePerson: rename,
    isRenaming,
    deletePerson: remove,
    isDeleting,
    refetch: fetchPeople,
  };
}
