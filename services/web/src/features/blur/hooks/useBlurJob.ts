/**
 * Hooks for the blur subsystem.
 *
 * Each hook is a thin self-polling wrapper around a single API call.
 * The polling interval backs off once a terminal state is reached so
 * a completed job doesn't quietly hammer the API. All hooks return
 * ``{ data, error, loading, refetch }`` so the calling components
 * stay uniform.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "@/lib/auth";

import {
  BlurDisabledError,
  BlurExportResponse,
  BlurJobListResponse,
  BlurJobResponse,
  getBlurExport,
  getBlurJob,
  listBlurJobsForFile,
} from "@/lib/api/blur";

const ACTIVE_STATUSES = new Set(["queued", "running"]);
const POLL_INTERVAL_MS = 3000;

// ---------- useBlurJobsForFile ----------

export interface UseBlurJobsForFileResult {
  data: BlurJobListResponse | null;
  loading: boolean;
  error: Error | null;
  disabled: boolean;
  refetch: () => void;
}

/**
 * List all blur jobs for a given video file. Used by VideoDetailPage
 * to decide whether to show "블러 처리 시작" or "블러 상세 보기".
 */
export function useBlurJobsForFile(fileId: string | null): UseBlurJobsForFileResult {
  const { getAccessToken } = useAuth();
  const [data, setData] = useState<BlurJobListResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(Boolean(fileId));
  const [error, setError] = useState<Error | null>(null);
  const [disabled, setDisabled] = useState<boolean>(false);
  const [tick, setTick] = useState(0);

  const refetch = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!fileId) {
      setData(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    listBlurJobsForFile(fileId, getAccessToken)
      .then((res) => {
        if (cancelled) return;
        setData(res);
        setError(null);
        setDisabled(false);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof BlurDisabledError) {
          setDisabled(true);
          setData(null);
          setError(null);
        } else {
          setError(err instanceof Error ? err : new Error(String(err)));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [fileId, getAccessToken, tick]);

  return { data, loading, error, disabled, refetch };
}

// ---------- useBlurJob (self-polling while active) ----------

export interface UseBlurJobResult {
  data: BlurJobResponse | null;
  loading: boolean;
  error: Error | null;
  refetch: () => void;
}

export function useBlurJob(jobId: string | null): UseBlurJobResult {
  const { getAccessToken } = useAuth();
  const [data, setData] = useState<BlurJobResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(Boolean(jobId));
  const [error, setError] = useState<Error | null>(null);
  const [tick, setTick] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refetch = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!jobId) {
      setData(null);
      setLoading(false);
      return;
    }
    let cancelled = false;

    const fetchOnce = async () => {
      try {
        const res = await getBlurJob(jobId, getAccessToken);
        if (cancelled) return;
        setData(res);
        setError(null);
        // Stop polling once the job reaches a terminal state — nothing
        // more to observe.
        if (!ACTIVE_STATUSES.has(res.status) && intervalRef.current) {
          clearInterval(intervalRef.current);
          intervalRef.current = null;
        }
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err : new Error(String(err)));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    setLoading(true);
    void fetchOnce();
    intervalRef.current = setInterval(() => {
      void fetchOnce();
    }, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [jobId, getAccessToken, tick]);

  return { data, loading, error, refetch };
}

// ---------- useBlurExport (self-polling while active) ----------

export interface UseBlurExportResult {
  data: BlurExportResponse | null;
  loading: boolean;
  error: Error | null;
  refetch: () => void;
}

export function useBlurExport(exportId: string | null): UseBlurExportResult {
  const { getAccessToken } = useAuth();
  const [data, setData] = useState<BlurExportResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(Boolean(exportId));
  const [error, setError] = useState<Error | null>(null);
  const [tick, setTick] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refetch = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!exportId) {
      setData(null);
      setLoading(false);
      return;
    }
    let cancelled = false;

    const fetchOnce = async () => {
      try {
        const res = await getBlurExport(exportId, getAccessToken);
        if (cancelled) return;
        setData(res);
        setError(null);
        if (!ACTIVE_STATUSES.has(res.status) && intervalRef.current) {
          clearInterval(intervalRef.current);
          intervalRef.current = null;
        }
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err : new Error(String(err)));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    setLoading(true);
    void fetchOnce();
    intervalRef.current = setInterval(() => {
      void fetchOnce();
    }, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [exportId, getAccessToken, tick]);

  return { data, loading, error, refetch };
}
