"use client";

import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { downloadClipCloud } from "@/lib/cloud-export";
import { getAgentClipUrl } from "@/lib/agent";
import { getApiBaseUrl } from "@/lib/api/utils";
import { SceneThumbnail } from "@/components/SceneThumbnail";
import { ExportModal } from "@/features/basket/ExportModal";
import type { BasketItem } from "@/features/basket/useSceneBasket";
import { getRenderJobStatus, type RenderJobResponse } from "@/lib/api/highlight-reel";

interface SavedShort {
  id: string;
  video_id: string;
  scene_ids: string[];
  title: string | null;
  start_ms: number | null;
  end_ms: number | null;
  created_at: string;
}

type SortKey = "newest" | "oldest";

// Unified card type for both saved shorts and render jobs
interface DisplayItem {
  id: string;
  type: "saved" | "render";
  title: string | null;
  video_id: string;
  scene_id?: string;
  scene_ids?: string[];
  start_ms?: number;
  end_ms?: number;
  created_at: string;
  // Render-specific
  status?: string;
  output_duration_ms?: number | null;
  output_size_bytes?: number | null;
  render_time_ms?: number | null;
  error?: string | null;
}

function BackArrowIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
    </svg>
  );
}

function VideoFileIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
    </svg>
  );
}

function FolderIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" />
    </svg>
  );
}

function CalendarIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
    </svg>
  );
}

function ChevronDownIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
    </svg>
  );
}

function FilmIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3.375 19.5h17.25m-17.25 0a1.125 1.125 0 01-1.125-1.125M3.375 19.5h1.5C5.496 19.5 6 18.996 6 18.375m-2.625 0V5.625m0 12.75v-1.5c0-.621.504-1.125 1.125-1.125m18.375 2.625V5.625m0 12.75c0 .621-.504 1.125-1.125 1.125m1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125m0 3.75h-1.5A1.125 1.125 0 0118 18.375M20.625 4.5H3.375m17.25 0c.621 0 1.125.504 1.125 1.125M20.625 4.5h-1.5C18.504 4.5 18 5.004 18 5.625m3.75 0v1.5c0 .621-.504 1.125-1.125 1.125M3.375 4.5c-.621 0-1.125.504-1.125 1.125M3.375 4.5h1.5C5.496 4.5 6 5.004 6 5.625m-2.625 0v1.5c0 .621.504 1.125 1.125 1.125m0 0h1.5m-1.5 0c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125m1.5-3.75C5.496 8.25 6 7.746 6 7.125v-1.5M4.875 8.25C5.496 8.25 6 8.754 6 9.375v1.5c0 .621-.504 1.125-1.125 1.125m1.5 0h12m-12 0c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125m12-3.75c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125m0 3.75h1.5c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125m0 0h-1.5m1.5 0c.621 0 1.125.504 1.125 1.125v1.5c0 .621-.504 1.125-1.125 1.125m-1.5-3.75c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125m-12 0c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125m12-3.75c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125m0 3.75h1.5c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125" />
    </svg>
  );
}

function CheckIcon({ checked }: { checked: boolean }) {
  if (checked) {
    return (
      <svg className="h-6 w-6 text-indigo-500" viewBox="0 0 24 24" fill="currentColor">
        <path fillRule="evenodd" d="M2.25 12c0-5.385 4.365-9.75 9.75-9.75s9.75 4.365 9.75 9.75-4.365 9.75-9.75 9.75S2.25 17.385 2.25 12zm13.36-1.814a.75.75 0 10-1.22-.872l-3.236 4.53L9.53 12.22a.75.75 0 00-1.06 1.06l2.25 2.25a.75.75 0 001.14-.094l3.75-5.25z" clipRule="evenodd" />
      </svg>
    );
  }
  return (
    <svg className="h-6 w-6 text-gray-300 hover:text-gray-400 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  );
}

function CircularProgress({ size = 40 }: { size?: number }) {
  const r = (size - 6) / 2;
  const circumference = 2 * Math.PI * r;
  return (
    <svg className="animate-spin" width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,0.3)" strokeWidth={3} />
      <circle
        cx={size / 2} cy={size / 2} r={r} fill="none" stroke="white" strokeWidth={3}
        strokeDasharray={circumference}
        strokeDashoffset={circumference * 0.75}
        strokeLinecap="round"
      />
    </svg>
  );
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

const ITEMS_PER_PAGE = 12;
const RENDER_POLL_INTERVAL = 5000;

export function SavedShortsPage() {
  const { getAccessToken } = useAuth();
  const [savedShorts, setSavedShorts] = useState<SavedShort[]>([]);
  const [renderJobs, setRenderJobs] = useState<RenderJobResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [sortKey, setSortKey] = useState<SortKey>("newest");
  const [currentPage, setCurrentPage] = useState(1);
  const [showSort, setShowSort] = useState(false);
  const [showExportMenu, setShowExportMenu] = useState(false);
  const [showExportDialog, setShowExportDialog] = useState(false);
  const exportMenuRef = useRef<HTMLDivElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval>>();

  // Fetch saved shorts + render jobs
  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);

    (async () => {
      try {
        const token = await getAccessToken();
        const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};

        const [shortsRes, rendersRes] = await Promise.all([
          fetch(`${getApiBaseUrl()}/api/shorts`, { headers }),
          fetch(`${getApiBaseUrl()}/api/shorts/render`, { headers }),
        ]);

        if (!cancelled) {
          const shortsData = shortsRes.ok ? await shortsRes.json() : { shorts: [] };
          const rendersData = rendersRes.ok ? await rendersRes.json() : { items: [] };
          setSavedShorts(shortsData.shorts ?? []);
          setRenderJobs(rendersData.items ?? []);
        }
      } catch {
        if (!cancelled) { setSavedShorts([]); setRenderJobs([]); }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [getAccessToken]);

  // Poll for in-progress render jobs
  useEffect(() => {
    const inProgress = renderJobs.filter((j) => j.status === "queued" || j.status === "rendering");
    if (inProgress.length === 0) {
      if (pollRef.current) clearInterval(pollRef.current);
      return;
    }

    pollRef.current = setInterval(async () => {
      const updates = await Promise.all(
        inProgress.map((j) => getRenderJobStatus(j.id, getAccessToken).catch(() => j)),
      );
      setRenderJobs((prev) =>
        prev.map((job) => {
          const updated = updates.find((u) => u.id === job.id);
          return updated ?? job;
        }),
      );
    }, RENDER_POLL_INTERVAL);

    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [renderJobs, getAccessToken]);

  useEffect(() => {
    if (!showExportMenu) return;
    const handler = (e: MouseEvent) => {
      if (exportMenuRef.current && !exportMenuRef.current.contains(e.target as Node)) {
        setShowExportMenu(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showExportMenu]);

  // Merge saved shorts and render jobs into unified list
  const displayItems: DisplayItem[] = useMemo(() => {
    const items: DisplayItem[] = [];

    for (const s of savedShorts) {
      items.push({
        id: s.id,
        type: "saved",
        title: s.title,
        video_id: s.video_id,
        scene_ids: s.scene_ids,
        scene_id: s.scene_ids[0],
        start_ms: s.start_ms ?? undefined,
        end_ms: s.end_ms ?? undefined,
        created_at: s.created_at,
      });
    }

    for (const r of renderJobs) {
      items.push({
        id: r.id,
        type: "render",
        title: r.title,
        video_id: r.thumbnail_video_id ?? r.video_id,
        scene_id: r.thumbnail_scene_id ?? undefined,
        created_at: r.created_at,
        status: r.status,
        output_duration_ms: r.output_duration_ms,
        output_size_bytes: r.output_size_bytes,
        render_time_ms: r.render_time_ms,
        error: r.error,
      });
    }

    return items;
  }, [savedShorts, renderJobs]);

  const selectedShorts = useMemo(
    () => savedShorts.filter((s) => selectedIds.has(s.id)),
    [savedShorts, selectedIds],
  );

  const [isDownloading, setIsDownloading] = useState(false);

  const handleClipDownload = useCallback(async () => {
    setShowExportMenu(false);
    setIsDownloading(true);
    try {
      for (const short of selectedShorts) {
        const startMs = short.start_ms ?? 0;
        const endMs = short.end_ms ?? 0;
        const name = short.title ?? `shorts_${short.video_id}`;
        if (short.video_id.startsWith("gd_") && startMs < endMs) {
          await downloadClipCloud(
            { video_id: short.video_id, clip_name: name, start_ms: startMs, end_ms: endMs },
            getAccessToken,
          );
        } else {
          const url = startMs < endMs
            ? getAgentClipUrl(short.video_id, startMs, endMs, name)
            : `http://127.0.0.1:8787/playback/file?file_id=${encodeURIComponent(short.video_id)}`;
          const a = document.createElement("a");
          a.href = url;
          a.download = name;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
        }
      }
    } catch {
      // download errors handled silently
    } finally {
      setIsDownloading(false);
    }
  }, [selectedShorts, getAccessToken]);

  const handleRenderDownload = useCallback(async (jobId: string) => {
    try {
      const token = await getAccessToken();
      const res = await fetch(`${getApiBaseUrl()}/api/shorts/render/${jobId}/download`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error("Download failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `highlight_${jobId}.mp4`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      // silent
    }
  }, [getAccessToken]);

  const exportItems: BasketItem[] = useMemo(
    () =>
      selectedShorts.map((s) => ({
        scene_id: s.scene_ids[0] ?? s.video_id,
        video_id: s.video_id,
        video_title: s.title ?? s.video_id,
        start_ms: s.start_ms ?? 0,
        end_ms: s.end_ms ?? 0,
        label: s.title ?? undefined,
      })),
    [selectedShorts],
  );

  const sorted = useMemo(() => {
    const copy = [...displayItems];
    copy.sort((a, b) => {
      const da = new Date(a.created_at).getTime();
      const db = new Date(b.created_at).getTime();
      return sortKey === "newest" ? db - da : da - db;
    });
    return copy;
  }, [displayItems, sortKey]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / ITEMS_PER_PAGE));
  const paged = useMemo(() => {
    const start = (currentPage - 1) * ITEMS_PER_PAGE;
    return sorted.slice(start, start + ITEMS_PER_PAGE);
  }, [sorted, currentPage]);

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleDelete = async (item: DisplayItem) => {
    try {
      const token = await getAccessToken();
      const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
      const endpoint = item.type === "saved"
        ? `${getApiBaseUrl()}/api/shorts/${item.id}`
        : `${getApiBaseUrl()}/api/shorts/render/${item.id}`;
      const res = await fetch(endpoint, { method: "DELETE", headers });
      if (res.ok || res.status === 204) {
        if (item.type === "saved") {
          setSavedShorts((prev) => prev.filter((s) => s.id !== item.id));
        } else {
          setRenderJobs((prev) => prev.filter((j) => j.id !== item.id));
        }
        setSelectedIds((prev) => { const next = new Set(prev); next.delete(item.id); return next; });
      }
    } catch {}
  };

  const today = new Date();
  const dateStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  const btnBase = "inline-flex h-8 w-8 items-center justify-center rounded text-sm transition-colors";

  const isRendering = (item: DisplayItem) => item.type === "render" && (item.status === "queued" || item.status === "rendering");
  const isCompleted = (item: DisplayItem) => item.type === "render" && item.status === "completed";
  const isFailed = (item: DisplayItem) => item.type === "render" && item.status === "failed";

  return (
    <div className="mx-auto max-w-6xl pt-4">
      <div className="mb-6 flex items-center gap-3 text-sm text-gray-500">
        <Link href="/" className="rounded-full p-1 hover:bg-gray-200">
          <BackArrowIcon />
        </Link>
        <span className="text-gray-700 font-medium">저장된 쇼츠</span>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold text-gray-900">저장된 쇼츠 영상</h1>
          <div className="relative" ref={exportMenuRef}>
            <button
              type="button"
              disabled={selectedIds.size === 0 || isDownloading}
              onClick={() => setShowExportMenu((v) => !v)}
              className={cn(
                "inline-flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium transition-colors",
                selectedIds.size > 0 && !isDownloading
                  ? "bg-indigo-500 text-white hover:bg-indigo-600"
                  : "bg-gray-200 text-gray-400 cursor-not-allowed",
              )}
            >
              {isDownloading ? (
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              ) : (
                <DownloadIcon />
              )}
              {isDownloading ? "다운로드 중..." : "내보내기"}
              {!isDownloading && <ChevronDownIcon />}
            </button>
            {showExportMenu && (
              <div className="absolute right-0 top-full z-20 mt-1 w-56 rounded-lg border border-gray-200 bg-white py-1 shadow-lg">
                <button
                  type="button"
                  onClick={handleClipDownload}
                  className="flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-sm text-gray-700 hover:bg-gray-50"
                >
                  <DownloadIcon />
                  클립 다운로드
                </button>
                <button
                  type="button"
                  onClick={() => { setShowExportMenu(false); setShowExportDialog(true); }}
                  className="flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-sm text-gray-700 hover:bg-gray-50"
                >
                  <FilmIcon />
                  Premiere Pro 내보내기
                </button>
              </div>
            )}
          </div>
        </div>

        <div className="mt-5 flex items-center justify-between">
          <div className="flex items-center gap-6 text-sm text-gray-500">
            <span className="inline-flex items-center gap-1.5"><VideoFileIcon />{displayItems.length} videos</span>
            <span className="inline-flex items-center gap-1.5"><FolderIcon />0 folders</span>
            <span className="inline-flex items-center gap-1.5"><CalendarIcon />{dateStr}</span>
          </div>
          <div className="relative">
            <button type="button" onClick={() => setShowSort((v) => !v)} className="inline-flex items-center gap-1.5 text-sm text-gray-600 hover:text-gray-800">
              {sortKey === "newest" ? "생성 일자 순" : "오래된 순"}
              <ChevronDownIcon />
            </button>
            {showSort && (
              <div className="absolute right-0 top-full z-10 mt-1 w-36 rounded-lg border border-gray-200 bg-white py-1 shadow-md">
                <button type="button" onClick={() => { setSortKey("newest"); setShowSort(false); }} className={cn("block w-full px-4 py-2 text-left text-sm", sortKey === "newest" ? "bg-indigo-50 text-indigo-700" : "text-gray-700 hover:bg-gray-50")}>생성 일자 순</button>
                <button type="button" onClick={() => { setSortKey("oldest"); setShowSort(false); }} className={cn("block w-full px-4 py-2 text-left text-sm", sortKey === "oldest" ? "bg-indigo-50 text-indigo-700" : "text-gray-700 hover:bg-gray-50")}>오래된 순</button>
              </div>
            )}
          </div>
        </div>

        {isLoading ? (
          <div className="mt-12 flex items-center justify-center py-16">
            <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-indigo-500" />
          </div>
        ) : paged.length > 0 ? (
          <div className="mt-6 grid grid-cols-2 gap-5 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
            {paged.map((item) => (
              <div key={item.id} className="group">
                {/* Thumbnail area */}
                <div className="relative block aspect-[4/3] w-full overflow-hidden rounded-lg bg-gray-200">
                  {item.type === "saved" && item.scene_ids ? (
                    <Link href={`/export/shorts/create?videoId=${item.video_id}&sceneIds=${item.scene_ids.join(",")}`} className="block h-full w-full">
                      <SceneThumbnail videoId={item.video_id} sceneId={item.scene_ids[0]} agentAvailable={true} className="h-full w-full" />
                    </Link>
                  ) : (
                    <div className="relative h-full w-full bg-gray-800 flex items-center justify-center">
                      {item.scene_id && item.video_id ? (
                        <SceneThumbnail videoId={item.video_id} sceneId={item.scene_id} agentAvailable={true} className="h-full w-full" />
                      ) : (
                        <svg className="h-8 w-8 text-gray-500" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" d="m15.75 10.5 4.72-4.72a.75.75 0 0 1 1.28.53v11.38a.75.75 0 0 1-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 0 0 2.25-2.25v-9a2.25 2.25 0 0 0-2.25-2.25h-9A2.25 2.25 0 0 0 2.25 7.5v9a2.25 2.25 0 0 0 2.25 2.25Z" /></svg>
                      )}

                      {/* Rendering overlay */}
                      {isRendering(item) && (
                        <div className="absolute inset-0 flex items-center justify-center bg-black/50">
                          <CircularProgress />
                        </div>
                      )}

                      {/* Completed overlay */}
                      {isCompleted(item) && (
                        <button
                          type="button"
                          onClick={() => handleRenderDownload(item.id)}
                          className="absolute inset-0 flex items-center justify-center bg-black/30 opacity-0 transition-opacity hover:opacity-100"
                        >
                          <div className="flex flex-col items-center text-white">
                            <DownloadIcon />
                            <span className="mt-1 text-xs">다운로드</span>
                          </div>
                        </button>
                      )}

                      {/* Failed overlay */}
                      {isFailed(item) && (
                        <div className="absolute inset-0 flex items-center justify-center bg-red-900/40">
                          <svg className="h-6 w-6 text-red-300" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 3.75h.008v.008H12v-.008Z" /></svg>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Selection checkbox — only for saved shorts */}
                  {item.type === "saved" && (
                    <button
                      type="button"
                      onClick={(e) => { e.preventDefault(); toggleSelect(item.id); }}
                      className="absolute right-2 top-2"
                    >
                      <CheckIcon checked={selectedIds.has(item.id)} />
                    </button>
                  )}

                  {/* Badge for render jobs */}
                  {item.type === "render" && (
                    <span className={cn(
                      "absolute left-2 top-2 rounded px-1.5 py-0.5 text-[10px] font-medium",
                      isRendering(item) && "bg-yellow-100 text-yellow-700",
                      isCompleted(item) && "bg-green-100 text-green-700",
                      isFailed(item) && "bg-red-100 text-red-700",
                    )}>
                      {isRendering(item) && "렌더링 중"}
                      {isCompleted(item) && "완료"}
                      {isFailed(item) && "실패"}
                    </span>
                  )}
                </div>

                {/* Title + actions */}
                <div className="mt-2 flex items-center justify-between">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-gray-900">
                      {item.title ?? (item.type === "render" ? "하이라이트 릴" : `쇼츠 ${item.scene_ids?.length ?? 0}장면`)}
                    </p>
                    {isCompleted(item) && item.output_size_bytes && (
                      <p className="text-xs text-gray-400">{formatFileSize(item.output_size_bytes)}</p>
                    )}
                    {isRendering(item) && (
                      <p className="text-xs text-yellow-600">렌더링 중...</p>
                    )}
                    {isFailed(item) && (
                      <p className="truncate text-xs text-red-500">{item.error ?? "렌더링 실패"}</p>
                    )}
                  </div>
                  <div className="ml-2 flex flex-shrink-0 items-center gap-2">
                    {item.type === "saved" && item.scene_ids && (
                      <Link
                        href={`/export/shorts/editor?shortId=${item.id}`}
                        className="text-xs text-indigo-500 hover:text-indigo-600 transition-colors"
                      >
                        편집
                      </Link>
                    )}
                    <button
                      type="button"
                      onClick={() => handleDelete(item)}
                      className="text-xs text-gray-400 hover:text-red-500 transition-colors"
                    >
                      삭제
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-12 flex flex-col items-center justify-center py-16 text-gray-400">
            <VideoFileIcon />
            <p className="mt-3 text-sm">저장된 쇼츠 영상이 없습니다.</p>
            <p className="mt-1 text-xs text-gray-400">영상을 선택하고 자동으로 쇼츠를 만들어 보세요.</p>
            <Link
              href="/"
              className="mt-5 inline-flex items-center gap-2 rounded-lg border border-indigo-300 bg-indigo-50 px-4 py-2 text-sm font-medium text-indigo-700 transition-colors hover:bg-indigo-100"
            >
              영상 목록으로 이동
            </Link>
          </div>
        )}

        <ExportModal
          isOpen={showExportDialog}
          onClose={() => setShowExportDialog(false)}
          overrideItems={exportItems}
        />

        <nav className="mt-8 flex items-center justify-center gap-1">
          <button type="button" disabled={currentPage === 1} onClick={() => setCurrentPage(1)} className={cn(btnBase, currentPage === 1 ? "cursor-not-allowed text-gray-300" : "text-gray-500 hover:bg-gray-100")}>&laquo;</button>
          <button type="button" disabled={currentPage === 1} onClick={() => setCurrentPage((p) => p - 1)} className={cn(btnBase, currentPage === 1 ? "cursor-not-allowed text-gray-300" : "text-gray-500 hover:bg-gray-100")}>&lsaquo;</button>
          {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
            <button key={p} type="button" onClick={() => setCurrentPage(p)} className={cn(btnBase, currentPage === p ? "bg-indigo-500 font-medium text-white" : "text-gray-600 hover:bg-gray-100")}>{p}</button>
          ))}
          <button type="button" disabled={currentPage === totalPages} onClick={() => setCurrentPage((p) => p + 1)} className={cn(btnBase, currentPage === totalPages ? "cursor-not-allowed text-gray-300" : "text-gray-500 hover:bg-gray-100")}>&rsaquo;</button>
          <button type="button" disabled={currentPage === totalPages} onClick={() => setCurrentPage(totalPages)} className={cn(btnBase, currentPage === totalPages ? "cursor-not-allowed text-gray-300" : "text-gray-500 hover:bg-gray-100")}>&raquo;</button>
        </nav>
      </div>
    </div>
  );
}
