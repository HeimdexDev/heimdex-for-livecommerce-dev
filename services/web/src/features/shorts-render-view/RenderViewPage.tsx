"use client";

/**
 * Single-render view: shows one ``RenderJobResponse`` — its status,
 * a video player when complete, and a download link.
 *
 * Linked from the auto-shorts wizard's "렌더 결과 보기" button on each
 * child clip card. Without this page, that link was a dead 404 that
 * the AppLayout auth-flicker turned into a redirect ping-pong with the
 * root in some browser sessions (staging incident 2026-05-06 on
 * render id 70ac4755-f565-4553-a79d-077e326a2167).
 *
 * Polls every 3s while the job is in a non-terminal state. Stops the
 * moment status flips to ``completed`` or ``failed``.
 */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { getRenderJob, type RenderJobResponse } from "@/lib/api/shorts-render";
import { useAuth } from "@/lib/auth";

interface Props {
  jobId: string;
}

const POLL_INTERVAL_MS = 3000;
// Terminal states match the backend ``ShortsRenderJob.status`` enum.
const TERMINAL_STATUSES: ReadonlySet<string> = new Set(["completed", "failed"]);

export function RenderViewPage({ jobId }: Props) {
  const { getAccessToken } = useAuth();
  const [job, setJob] = useState<RenderJobResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;

    const fetchOnce = async () => {
      try {
        const fresh = await getRenderJob(jobId, getAccessToken);
        if (cancelled) return;
        setJob(fresh);
        setError(null);
        // Stop polling once terminal.
        if (TERMINAL_STATUSES.has(fresh.status) && pollRef.current != null) {
          window.clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "렌더 조회 실패");
      }
    };

    void fetchOnce();
    pollRef.current = window.setInterval(() => {
      void fetchOnce();
    }, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      if (pollRef.current != null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [jobId, getAccessToken]);

  if (!jobId) {
    return <Banner message="잘못된 렌더 ID입니다." />;
  }

  if (error) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-gray-50 p-6">
        <p className="text-sm text-red-700">{error}</p>
        <Link href="/" className="text-sm text-indigo-600 hover:underline">
          ← 홈으로
        </Link>
      </div>
    );
  }

  if (!job) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <div className="h-10 w-10 animate-spin rounded-full border-b-2 border-indigo-500" />
      </div>
    );
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-4xl flex-col gap-6 p-6">
      <div className="flex items-center justify-between">
        <Link href="/" className="text-sm text-gray-700 hover:text-indigo-600">
          ← 홈으로
        </Link>
        <div className="text-xs text-gray-500" data-testid="render-job-id">
          {jobId.slice(0, 8)}
        </div>
      </div>

      <h1 className="text-xl font-semibold text-gray-800">
        {job.title || "쇼츠 렌더 결과"}
      </h1>

      {job.status === "completed" && job.download_url ? (
        <video
          controls
          src={job.download_url}
          className="w-full rounded-lg bg-black"
          data-testid="render-video"
        />
      ) : job.status === "failed" ? (
        <div className="rounded-md bg-red-50 p-4 text-sm text-red-700">
          렌더링 실패: {job.error || "알 수 없는 오류"}
        </div>
      ) : (
        <div className="flex items-center gap-3 rounded-md border border-gray-200 bg-white p-4">
          <div className="h-5 w-5 animate-spin rounded-full border-b-2 border-indigo-500" />
          <p className="text-sm text-gray-600">
            상태: <span className="font-medium">{job.status}</span> · 3초마다 갱신
          </p>
        </div>
      )}

      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 rounded border border-gray-200 bg-white p-4 text-xs text-gray-600">
        <dt>비디오 ID</dt>
        <dd className="font-mono">{job.video_id}</dd>
        <dt>상태</dt>
        <dd>{job.status}</dd>
        <dt>생성</dt>
        <dd>{new Date(job.created_at).toLocaleString("ko-KR")}</dd>
        {job.completed_at ? (
          <>
            <dt>완료</dt>
            <dd>{new Date(job.completed_at).toLocaleString("ko-KR")}</dd>
          </>
        ) : null}
        {job.render_time_ms != null ? (
          <>
            <dt>렌더 시간</dt>
            <dd>{(job.render_time_ms / 1000).toFixed(1)}s</dd>
          </>
        ) : null}
        {job.output_duration_ms != null ? (
          <>
            <dt>길이</dt>
            <dd>{(job.output_duration_ms / 1000).toFixed(1)}s</dd>
          </>
        ) : null}
      </dl>

      {job.download_url ? (
        <div className="flex justify-end">
          <a
            href={job.download_url}
            target="_blank"
            rel="noreferrer"
            className="rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
          >
            다운로드
          </a>
        </div>
      ) : null}
    </div>
  );
}

function Banner({ message }: { message: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 p-6">
      <p className="text-sm text-red-700">{message}</p>
    </div>
  );
}
