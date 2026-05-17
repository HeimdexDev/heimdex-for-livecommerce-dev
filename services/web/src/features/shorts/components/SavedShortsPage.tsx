"use client";

// figma: 1713:287987  (cache: .figma-cache/1713-287987_phase4_saved-shorts.api.json)
// node-name: 6-1.d 쇼츠 저장 직후 화면
// title  · figma: 1713:287992 "저장된 쇼츠 목록"  · spec: 600/18 lh=25.2 letter=-0.45 text=grayscale-800
// count  · spec: 500/12 lh=16.8 letter=-0.3 text=grayscale-500
// grid   · spec: gap-x=16 gap-y=24 → tokens gap-x-4 gap-y-6
// empty  · Q14 간이 placeholder + dev URL flag `?empty=1`

import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  Search,
  ChevronDown,
  Plus,
  Download,
  Film,
  Trash2,
  AlertCircle,
} from "lucide-react";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { downloadClipCloud } from "@/lib/cloud-export";
import { getAgentClipUrl } from "@/lib/agent";
import { getApiBaseUrl } from "@/lib/api/utils";
import { SceneThumbnail } from "@/components/SceneThumbnail";
import { ExportModal } from "@/features/basket/ExportModal";
import type { BasketItem } from "@/features/basket/useSceneBasket";
import { getRenderJobStatus, type RenderJobResponse } from "@/lib/api/highlight-reel";
import { generateRenderJobSummary } from "@/lib/api/shorts-render";
import { Pagination } from "@/components/ui/Pagination";
import { Button, Snackbar } from "@/components/ui/figma-index";

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
  status?: string;
  output_duration_ms?: number | null;
  output_size_bytes?: number | null;
  render_time_ms?: number | null;
  error?: string | null;
  summary?: string | null;
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

function formatRemaining(secs: number): string {
  if (!Number.isFinite(secs) || secs <= 0) return "잠시";
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  if (m === 0) return `${s}초`;
  return `${m}분 ${String(s).padStart(2, "0")}초`;
}

const ITEMS_PER_PAGE = 12;
const RENDER_POLL_INTERVAL = 5000;
const AVG_CLIP_SECONDS = 90;

export function SavedShortsPage() {
  const { getAccessToken } = useAuth();
  const searchParams = useSearchParams();
  // dev URL flag: ?empty=1 → 강제 빈 상태 (Q14 검증용)
  const forceEmpty = searchParams?.get("empty") === "1";
  const [savedShorts, setSavedShorts] = useState<SavedShort[]>([]);
  const [renderJobs, setRenderJobs] = useState<RenderJobResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [sortKey, setSortKey] = useState<SortKey>("newest");
  const [currentPage, setCurrentPage] = useState(1);
  const [showSort, setShowSort] = useState(false);
  const [showExportMenu, setShowExportMenu] = useState(false);
  const [showExportDialog, setShowExportDialog] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const exportMenuRef = useRef<HTMLDivElement>(null);
  const sortRef = useRef<HTMLDivElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval>>();

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
    if (!showExportMenu && !showSort) return;
    const handler = (e: MouseEvent) => {
      const t = e.target as Node;
      if (showExportMenu && exportMenuRef.current && !exportMenuRef.current.contains(t)) {
        setShowExportMenu(false);
      }
      if (showSort && sortRef.current && !sortRef.current.contains(t)) {
        setShowSort(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showExportMenu, showSort]);

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
        summary: r.summary,
      });
    }

    return items;
  }, [savedShorts, renderJobs]);

  const filtered = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return displayItems;
    return displayItems.filter((it) => (it.title ?? "").toLowerCase().includes(q));
  }, [displayItems, searchQuery]);

  const sorted = useMemo(() => {
    const copy = [...filtered];
    copy.sort((a, b) => {
      const da = new Date(a.created_at).getTime();
      const db = new Date(b.created_at).getTime();
      return sortKey === "newest" ? db - da : da - db;
    });
    return copy;
  }, [filtered, sortKey]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / ITEMS_PER_PAGE));
  const paged = useMemo(() => {
    const start = (currentPage - 1) * ITEMS_PER_PAGE;
    return sorted.slice(start, start + ITEMS_PER_PAGE);
  }, [sorted, currentPage]);

  useEffect(() => {
    if (currentPage > totalPages) setCurrentPage(1);
  }, [currentPage, totalPages]);

  const selectedShorts = useMemo(
    () => savedShorts.filter((s) => selectedIds.has(s.id)),
    [savedShorts, selectedIds],
  );

  const [exportProgress, setExportProgress] = useState<{ current: number; total: number } | null>(null);
  // TODO: mock progress wiring — once useExportBatch is exposed at app
  // level, replace the sequential loop below with the batch hook's state
  // map.
  const [summarizingIds, setSummarizingIds] = useState<Set<string>>(() => new Set());
  const [summaryErrors, setSummaryErrors] = useState<Map<string, string>>(() => new Map());

  const handleGenerateSummary = useCallback(
    async (jobId: string) => {
      setSummarizingIds((prev) => new Set(prev).add(jobId));
      setSummaryErrors((prev) => {
        const next = new Map(prev);
        next.delete(jobId);
        return next;
      });
      try {
        const result = await generateRenderJobSummary(jobId, getAccessToken);
        setRenderJobs((prev) =>
          prev.map((job) =>
            job.id === jobId ? { ...job, summary: result.summary } : job,
          ),
        );
      } catch (err) {
        setSummaryErrors((prev) => {
          const next = new Map(prev);
          next.set(jobId, err instanceof Error ? err.message : "요약 생성 실패");
          return next;
        });
      } finally {
        setSummarizingIds((prev) => {
          const next = new Set(prev);
          next.delete(jobId);
          return next;
        });
      }
    },
    [getAccessToken],
  );

  const handleClipDownload = useCallback(async () => {
    setShowExportMenu(false);
    const total = selectedShorts.length;
    if (total === 0) return;
    setExportProgress({ current: 0, total });
    try {
      let done = 0;
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
        done += 1;
        setExportProgress({ current: done, total });
      }
    } catch {
      // download errors handled silently per legacy behaviour
    } finally {
      setExportProgress(null);
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

  const isRendering = (item: DisplayItem) => item.type === "render" && (item.status === "queued" || item.status === "rendering");
  const isCompleted = (item: DisplayItem) => item.type === "render" && item.status === "completed";
  const isFailed = (item: DisplayItem) => item.type === "render" && item.status === "failed";

  const exportDisabled = selectedIds.size === 0 || exportProgress !== null;

  const exportPercent = exportProgress
    ? Math.round((exportProgress.current / Math.max(1, exportProgress.total)) * 100)
    : 0;
  const exportRemaining = exportProgress
    ? formatRemaining((exportProgress.total - exportProgress.current) * AVG_CLIP_SECONDS)
    : "";

  return (
    <div className="mx-auto max-w-[943px] pt-4 font-pretendard">
      <div className="mb-4 flex items-center gap-[10px] text-[14px] text-neutral-h-500">
        <Link href="/" className="inline-flex items-center gap-[4px] rounded-full p-1 hover:bg-neutral-h-50">
          <ArrowLeft className="h-4 w-4" />
          <span>뒤로가기</span>
        </Link>
      </div>

      <div className="rounded-card border border-grayscale-100 bg-white p-[20px] shadow-card">
        {/* Title + actions row (Figma Frame 1707484731) */}
        {/* figma: 1713:287992 · spec: 600/18 lh=25.2 letter=-0.45 text=grayscale-800 */}
        <div className="flex items-center justify-between gap-[16px]">
          <h1 className="font-pretendard text-lg font-semibold leading-[1.4] tracking-tight text-grayscale-800">
            저장된 쇼츠 목록{" "}
            <span className="text-xs font-medium leading-[1.4] tracking-tight text-grayscale-500">
              {filtered.length}개
            </span>
          </h1>
          <div className="flex items-center gap-[8px]">
            <Link href="/export/shorts/editor">
              <Button variant="secondary" size="sm" leadingIcon={<Plus className="h-4 w-4" strokeWidth={2} />}>
                새 쇼츠 생성
              </Button>
            </Link>
            <div className="relative" ref={exportMenuRef}>
              <Button
                variant="primary"
                size="sm"
                disabled={exportDisabled}
                leadingIcon={<Download className="h-4 w-4" strokeWidth={2} />}
                onClick={() => setShowExportMenu((v) => !v)}
              >
                내보내기
              </Button>
              {showExportMenu && (
                <div className="absolute right-0 top-full z-20 mt-[6px] w-[200px] rounded-card border border-grayscale-100 bg-white py-1 shadow-dialog">
                  <button
                    type="button"
                    onClick={handleClipDownload}
                    className="flex w-full items-center gap-[8px] px-[12px] py-[10px] text-left text-[13px] text-neutral-h-700 hover:bg-neutral-h-50"
                  >
                    <Download className="h-4 w-4" />
                    클립 다운로드
                  </button>
                  <button
                    type="button"
                    onClick={() => { setShowExportMenu(false); setShowExportDialog(true); }}
                    className="flex w-full items-center gap-[8px] px-[12px] py-[10px] text-left text-[13px] text-neutral-h-700 hover:bg-neutral-h-50"
                  >
                    <Film className="h-4 w-4" />
                    Premiere Pro 내보내기
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Searchbar (Figma Frame 1707484628) */}
        <div className="mt-[20px] flex h-[56px] items-center gap-[10px] rounded-card border border-grayscale-100 bg-grayscale-10 px-[20px]">
          <Search className="h-5 w-5 text-neutral-h-400" strokeWidth={1.75} />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="찾고 싶은 영상을 제목으로 검색해보세요."
            className="flex-1 bg-transparent text-[14px] tracking-[-0.35px] text-neutral-h-800 placeholder:text-neutral-h-400 focus:outline-none"
          />
        </div>

        {/* Filter row (Figma Frame 215) — sort dropdown only */}
        <div className="mt-[20px] flex items-center justify-end">
          <div className="relative" ref={sortRef}>
            <button
              type="button"
              onClick={() => setShowSort((v) => !v)}
              className="inline-flex items-center gap-[4px] text-[13px] font-medium text-neutral-h-600 hover:text-neutral-h-800"
            >
              {sortKey === "newest" ? "생성 일자 순" : "오래된 순"}
              <ChevronDown className="h-4 w-4" />
            </button>
            {showSort && (
              <div className="absolute right-0 top-full z-10 mt-[6px] w-[140px] rounded-card border border-grayscale-100 bg-white py-1 shadow-dialog">
                <button
                  type="button"
                  onClick={() => { setSortKey("newest"); setShowSort(false); }}
                  className={cn(
                    "block w-full px-[12px] py-[8px] text-left text-[13px]",
                    sortKey === "newest" ? "bg-heimdex-navy-500/10 text-heimdex-navy-500" : "text-neutral-h-700 hover:bg-neutral-h-50",
                  )}
                >
                  생성 일자 순
                </button>
                <button
                  type="button"
                  onClick={() => { setSortKey("oldest"); setShowSort(false); }}
                  className={cn(
                    "block w-full px-[12px] py-[8px] text-left text-[13px]",
                    sortKey === "oldest" ? "bg-heimdex-navy-500/10 text-heimdex-navy-500" : "text-neutral-h-700 hover:bg-neutral-h-50",
                  )}
                >
                  오래된 순
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Card grid (Figma Frame 1707484629) — 4-col wrap, 200×337 thumb */}
        {isLoading ? (
          <div className="mt-[20px] flex items-center justify-center py-16">
            <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-heimdex-navy-500" />
          </div>
        ) : !forceEmpty && paged.length > 0 ? (
          // figma: 1699:252725 — vertical list of horizontal row cards
          // (150×253 thumbnail on the left, content column on the right with
          // title, length/progress meta, caption, and a status pill).
          <div className="mt-[20px] flex flex-col gap-[16px]">
            {paged.map((item) => {
              const sceneCount = item.scene_ids?.length ?? 0;
              const statusLabel = item.type === "saved"
                ? "저장됨"
                : isRendering(item)
                  ? "대기 중"
                  : isCompleted(item)
                    ? "완료"
                    : isFailed(item)
                      ? "실패"
                      : "준비";
              const statusClass =
                item.type === "saved" || isCompleted(item)
                  ? "bg-green-h-50 text-green-h-500"
                  : isFailed(item)
                    ? "bg-red-h-50 text-red-h-500"
                    : "bg-neutral-h-100 text-neutral-h-500";
              return (
                <div
                  key={item.id}
                  className="group flex items-stretch overflow-hidden rounded-card border border-neutral-h-100 bg-white"
                >
                  {/* Thumbnail 150×253 — portrait shorts thumb */}
                  <div className="relative h-[253px] w-[150px] flex-shrink-0 overflow-hidden bg-neutral-h-100 p-2">
                    {item.type === "saved" && item.scene_ids ? (
                      <Link
                        href={`/export/shorts/editor?videoId=${item.video_id}&sceneIds=${item.scene_ids.join(",")}`}
                        className="absolute inset-0 block"
                      >
                        <SceneThumbnail
                          videoId={item.video_id}
                          sceneId={item.scene_ids[0]}
                          agentAvailable={true}
                          className="h-full w-full object-cover"
                        />
                      </Link>
                    ) : (
                      <div className="absolute inset-0 bg-neutral-h-700">
                        {item.scene_id && item.video_id ? (
                          <SceneThumbnail
                            videoId={item.video_id}
                            sceneId={item.scene_id}
                            agentAvailable={true}
                            className="h-full w-full object-cover"
                          />
                        ) : (
                          <div className="flex h-full w-full items-center justify-center">
                            <Film className="h-8 w-8 text-neutral-h-400" />
                          </div>
                        )}
                        {isRendering(item) && (
                          <div className="absolute inset-0 flex items-center justify-center bg-black/50">
                            <CircularProgress />
                          </div>
                        )}
                        {isCompleted(item) && (
                          <button
                            type="button"
                            onClick={() => handleRenderDownload(item.id)}
                            className="absolute inset-0 flex items-center justify-center bg-black/30 opacity-0 transition-opacity hover:opacity-100"
                          >
                            <div className="flex flex-col items-center text-white">
                              <Download className="h-5 w-5" />
                              <span className="mt-1 text-xs">다운로드</span>
                            </div>
                          </button>
                        )}
                        {isFailed(item) && (
                          <div className="absolute inset-0 flex items-center justify-center bg-red-h-500/30">
                            <AlertCircle className="h-6 w-6 text-red-h-400" />
                          </div>
                        )}
                      </div>
                    )}
                    {/* product tag overlay (figma 1699:252747) */}
                    {item.type === "saved" && (
                      <span className="absolute bottom-2 left-2 inline-flex items-center rounded bg-black/50 px-[4px] py-[2px] text-[8px] font-medium text-white">
                        쇼츠 · {sceneCount}장면
                      </span>
                    )}
                  </div>

                  {/* Content column */}
                  <div className="flex min-w-0 flex-1 flex-col items-end gap-[20px] self-stretch px-[12px] py-[16px]">
                    <div className="flex w-full items-start justify-between gap-[12px]">
                      <p
                        className="truncate text-[14px] font-semibold tracking-[-0.35px] text-grayscale-800"
                        title={item.title ?? undefined}
                      >
                        {item.title ?? (item.type === "render" ? "하이라이트 릴" : `쇼츠 ${sceneCount}장면`)}
                      </p>
                      <div className="flex flex-shrink-0 items-center gap-[8px]">
                        {item.type === "saved" && item.scene_ids && (
                          <Link
                            href={`/export/shorts/editor?shortId=${item.id}`}
                            className="text-[12px] font-medium text-heimdex-navy-500 hover:text-heimdex-navy-600"
                          >
                            편집
                          </Link>
                        )}
                        {item.type === "render" && isCompleted(item) && (
                          <Link
                            href={`/export/shorts/${encodeURIComponent(item.id)}/edit`}
                            className="text-[12px] font-medium text-heimdex-navy-500 hover:text-heimdex-navy-600"
                            data-testid="saved-shorts-render-edit-link"
                          >
                            편집
                          </Link>
                        )}
                        <button
                          type="button"
                          onClick={() => handleDelete(item)}
                          aria-label="삭제"
                          className="text-neutral-h-400 transition-colors hover:text-red-h-500"
                        >
                          <Trash2 className="h-4 w-4" strokeWidth={1.5} />
                        </button>
                        {item.type === "saved" && (
                          <button
                            type="button"
                            aria-label={selectedIds.has(item.id) ? "선택 해제" : "선택"}
                            onClick={() => toggleSelect(item.id)}
                            className={cn(
                              "inline-flex h-5 w-5 items-center justify-center rounded-[4px] border-2 transition-colors",
                              selectedIds.has(item.id)
                                ? "border-heimdex-navy-500 bg-heimdex-navy-500 text-white"
                                : "border-grayscale-300 bg-white hover:border-heimdex-navy-400",
                            )}
                          >
                            {selectedIds.has(item.id) && (
                              <svg className="h-3 w-3" fill="none" viewBox="0 0 12 12" stroke="currentColor" strokeWidth={2.5}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M2.5 6.5L5 9l4.5-5" />
                              </svg>
                            )}
                          </button>
                        )}
                      </div>
                    </div>

                    <div className="flex w-full gap-[10px] text-[12px] font-medium tracking-[-0.3px]">
                      <div className="flex flex-col gap-[10px] text-neutral-h-500">
                        <span>장면 수</span>
                        <span>상태</span>
                      </div>
                      <div className="flex flex-col gap-[10px] text-grayscale-800">
                        <span>{sceneCount ? `${sceneCount}개` : "—"}</span>
                        <span>{statusLabel}</span>
                      </div>
                    </div>

                    <div className="flex w-full flex-1 items-start">
                      {item.type === "render" && isCompleted(item) ? (
                        <div data-testid="saved-shorts-summary" className="flex-1">
                          {item.summary ? (
                            <p className="line-clamp-3 text-[12px] leading-[1.5] text-neutral-h-800">
                              {item.summary}
                            </p>
                          ) : summarizingIds.has(item.id) ? (
                            <p className="text-[12px] text-neutral-h-400">요약 생성 중...</p>
                          ) : (
                            <button
                              type="button"
                              onClick={() => handleGenerateSummary(item.id)}
                              className="text-[12px] text-heimdex-navy-500 transition-colors hover:text-heimdex-navy-600"
                              data-testid="saved-shorts-generate-summary"
                            >
                              요약 생성
                            </button>
                          )}
                          {summaryErrors.has(item.id) && (
                            <p className="mt-[2px] text-[12px] text-red-h-500">
                              {summaryErrors.get(item.id)}
                            </p>
                          )}
                        </div>
                      ) : (
                        <p className="line-clamp-3 flex-1 text-[12px] leading-[1.5] text-neutral-h-500">
                          {item.type === "saved"
                            ? `편집기에서 ${sceneCount}장면을 결합한 쇼츠입니다.`
                            : "렌더링 결과가 준비되면 요약이 표시됩니다."}
                        </p>
                      )}
                    </div>

                    <span className={cn("inline-flex items-center rounded-[4px] px-[6px] py-[3px] text-[12px] font-semibold", statusClass)}>
                      {statusLabel}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        ) : searchQuery && !forceEmpty ? (
          // figma: 검색 결과 없음 (간이 안내)
          <div className="mt-5 flex flex-col items-center justify-center py-16 text-grayscale-500">
            <p className="font-pretendard text-sm font-medium leading-[1.4] tracking-tight">
              검색 결과가 없습니다.
            </p>
          </div>
        ) : (
          // figma: Q14 간이 empty placeholder — saved-shorts 0건
          // 회색 박스 + "아직 저장된 쇼츠가 없어요"
          <div
            className="mt-5 flex flex-col items-center justify-center rounded-card bg-grayscale-10 py-16"
            data-testid="saved-shorts-empty"
          >
            <p className="font-pretendard text-sm font-medium leading-[1.4] tracking-tight text-grayscale-500">
              아직 저장된 쇼츠가 없어요
            </p>
          </div>
        )}

        <ExportModal
          isOpen={showExportDialog}
          onClose={() => setShowExportDialog(false)}
          overrideItems={exportItems}
        />

        <Pagination
          currentPage={currentPage}
          totalPages={totalPages}
          onPageChange={setCurrentPage}
          className="mt-[24px]"
          ariaLabel="저장된 쇼츠 페이지"
        />
      </div>

      {/* Export progress Snackbar (Figma Snackbar 364×87, top-right) */}
      {exportProgress && (
        <Snackbar
          tone="loading"
          title="쇼츠 저장 중"
          body={`${exportPercent}% · ${exportRemaining} 남음`}
          position="top-right"
          onClose={() => setExportProgress(null)}
        />
      )}
    </div>
  );
}
