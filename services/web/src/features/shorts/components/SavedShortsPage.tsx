"use client";

import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { exportToPremiere } from "@/lib/agent-export";
import { exportEdlCloud } from "@/lib/cloud-export";
import { checkAgentHealth, getAgentClipUrl } from "@/lib/agent";
import { SceneThumbnail } from "@/components/SceneThumbnail";
import { ExportDialog } from "@/features/videos/components/ExportDialog";
import type { ExportClipInput } from "@/lib/types";

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

const ITEMS_PER_PAGE = 12;

export function SavedShortsPage() {
  const { getAccessToken } = useAuth();
  const [items, setItems] = useState<SavedShort[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [sortKey, setSortKey] = useState<SortKey>("newest");
  const [currentPage, setCurrentPage] = useState(1);
  const [showSort, setShowSort] = useState(false);
  const [showExportMenu, setShowExportMenu] = useState(false);
  const [showExportDialog, setShowExportDialog] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportNotice, setExportNotice] = useState<string | null>(null);
  const [exportResult, setExportResult] = useState<{ output_path: string; clip_count: number } | null>(null);
  const [agentAvailable, setAgentAvailable] = useState(false);
  const exportMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);

    (async () => {
      try {
        const token = await getAccessToken();
        const res = await fetch("/api/shorts", {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (!res.ok) throw new Error("fetch failed");
        const data = await res.json();
        if (!cancelled) setItems(data.shorts ?? []);
      } catch {
        if (!cancelled) setItems([]);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [getAccessToken]);

  useEffect(() => {
    checkAgentHealth().then((h) => setAgentAvailable(h !== null));
  }, []);

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

  const selectedShorts = useMemo(
    () => items.filter((s) => selectedIds.has(s.id)),
    [items, selectedIds],
  );

  const handleClipDownload = useCallback(() => {
    setShowExportMenu(false);
    for (const short of selectedShorts) {
      const startMs = short.start_ms ?? 0;
      const endMs = short.end_ms ?? 0;
      const name = short.title ?? `shorts_${short.video_id}`;
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
  }, [selectedShorts]);

  const isCloudExport = useMemo(
    () => selectedShorts.length > 0 && selectedShorts.every((s) => s.video_id.startsWith("gd_")),
    [selectedShorts],
  );

  const handlePremiereExport = useCallback(
    async (config: { projectName: string; outputDir: string; frameRate: number }) => {
      setShowExportDialog(false);
      setIsExporting(true);
      setExportError(null);
      setExportNotice(null);
      setExportResult(null);
      try {
        const clips: ExportClipInput[] = selectedShorts.map((s) => ({
          video_id: s.video_id,
          scene_id: s.scene_ids[0] ?? s.video_id,
          clip_name: s.title ?? `shorts_${s.scene_ids.length}_scenes`,
          start_ms: s.start_ms ?? 0,
          end_ms: s.end_ms ?? 0,
        }));

        const allCloud = selectedShorts.every((s) => s.video_id.startsWith("gd_"));
        const allLocal = selectedShorts.every((s) => !s.video_id.startsWith("gd_"));
        const localShorts = selectedShorts.filter((s) => !s.video_id.startsWith("gd_"));
        const cloudClips = clips.filter((clip) => clip.video_id.startsWith("gd_"));
        const localClips = clips.filter((clip) => !clip.video_id.startsWith("gd_"));

        if (allCloud) {
          const result = await exportEdlCloud(
            {
              project_name: config.projectName,
              frame_rate: config.frameRate,
              clips: cloudClips,
            },
            getAccessToken,
          );
          setExportResult({ output_path: result.filename, clip_count: result.clip_count });
        } else if (allLocal) {
          const result = await exportToPremiere({
            project_name: config.projectName,
            format: "edl",
            frame_rate: config.frameRate,
            output_dir: config.outputDir,
            clips: localClips,
          });
          setExportResult({ output_path: result.output_path, clip_count: result.clip_count });
        } else {
          const cloudResult = await exportEdlCloud(
            {
              project_name: config.projectName,
              frame_rate: config.frameRate,
              clips: cloudClips,
            },
            getAccessToken,
          );

          if (agentAvailable) {
            const localResult = await exportToPremiere({
              project_name: config.projectName,
              format: "edl",
              frame_rate: config.frameRate,
              output_dir: config.outputDir,
              clips: localClips,
            });
            setExportResult({
              output_path: localResult.output_path,
              clip_count: cloudResult.clip_count + localResult.clip_count,
            });
          } else {
            const skippedLocalNames = localShorts
              .map((short, index) => short.title ?? `Local Clip ${index + 1}`)
              .join(", ");
            setExportNotice(`에이전트가 오프라인 상태여서 로컬 클립을 건너뛰었습니다: ${skippedLocalNames}`);
            setExportResult({ output_path: cloudResult.filename, clip_count: cloudResult.clip_count });
          }
        }
      } catch (err) {
        setExportError(err instanceof Error ? err.message : "내보내기에 실패했습니다");
      } finally {
        setIsExporting(false);
      }
    },
    [selectedShorts, getAccessToken, agentAvailable],
  );

  const sorted = useMemo(() => {
    const copy = [...items];
    copy.sort((a, b) => {
      const da = new Date(a.created_at).getTime();
      const db = new Date(b.created_at).getTime();
      return sortKey === "newest" ? db - da : da - db;
    });
    return copy;
  }, [items, sortKey]);

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

  const handleDelete = async (id: string) => {
    try {
      const token = await getAccessToken();
      const res = await fetch(`/api/shorts/${id}`, {
        method: "DELETE",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.ok || res.status === 204) {
        setItems((prev) => prev.filter((s) => s.id !== id));
        setSelectedIds((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
      }
    } catch {}
  };

  const today = new Date();
  const dateStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  const btnBase = "inline-flex h-8 w-8 items-center justify-center rounded text-sm transition-colors";

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
              disabled={selectedIds.size === 0 || isExporting}
              onClick={() => setShowExportMenu((v) => !v)}
              className={cn(
                "inline-flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium transition-colors",
                selectedIds.size > 0 && !isExporting
                  ? "bg-indigo-500 text-white hover:bg-indigo-600"
                  : "bg-gray-200 text-gray-400 cursor-not-allowed",
              )}
            >
              {isExporting ? (
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              ) : (
                <DownloadIcon />
              )}
              {isExporting ? "내보내는 중..." : "내보내기"}
              {!isExporting && <ChevronDownIcon />}
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
            <span className="inline-flex items-center gap-1.5"><VideoFileIcon />{items.length} videos</span>
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
            {paged.map((short) => (
              <div key={short.id} className="group">
                <Link
                  href={`/shorts/create?videoId=${short.video_id}&sceneIds=${short.scene_ids.join(",")}`}
                  className="relative block aspect-[4/3] w-full overflow-hidden rounded-lg bg-gray-200"
                >
                  <SceneThumbnail
                    videoId={short.video_id}
                    sceneId={short.scene_ids[0]}
                    agentAvailable={true}
                    className="h-full w-full"
                  />
                  <button
                    type="button"
                    onClick={(e) => { e.preventDefault(); toggleSelect(short.id); }}
                    className="absolute right-2 top-2"
                  >
                    <CheckIcon checked={selectedIds.has(short.id)} />
                  </button>
                </Link>
                <div className="mt-2 flex items-center justify-between">
                  <p className="truncate text-sm text-gray-900">{short.title ?? `쇼츠 ${short.scene_ids.length}장면`}</p>
                  <button
                    type="button"
                    onClick={() => handleDelete(short.id)}
                    className="ml-2 flex-shrink-0 text-xs text-gray-400 hover:text-red-500 transition-colors"
                  >
                    삭제
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-12 flex flex-col items-center justify-center py-16 text-gray-400">
            <VideoFileIcon />
            <p className="mt-3 text-sm">저장된 쇼츠 영상이 없습니다.</p>
            <p className="mt-1 text-xs text-gray-400">영상 장면 분석에서 쇼츠를 제작하고 저장해 보세요.</p>
          </div>
        )}

        {showExportDialog && (
          <ExportDialog
            isOpen={showExportDialog}
            onClose={() => setShowExportDialog(false)}
            onExport={(config) => void handlePremiereExport(config)}
            selectedCount={selectedIds.size}
            isExporting={isExporting}
            defaultProjectName={selectedShorts[0]?.title ?? "Heimdex Export"}
            agentAvailable={agentAvailable}
            isCloudExport={isCloudExport}
          />
        )}

        {exportResult && (
          <div className="fixed bottom-6 right-6 z-50 max-w-sm rounded-lg border border-green-200 bg-green-50 p-4 shadow-lg">
            <p className="text-sm font-medium text-green-800">내보내기 완료</p>
            <p className="mt-1 truncate text-xs text-green-600">{exportResult.output_path} ({exportResult.clip_count}개 클립)</p>
            <button type="button" onClick={() => setExportResult(null)} className="mt-2 text-xs text-green-700 underline">닫기</button>
          </div>
        )}

        {exportError && (
          <div className="fixed bottom-6 right-6 z-50 max-w-sm rounded-lg border border-red-200 bg-red-50 p-4 shadow-lg">
            <p className="text-sm font-medium text-red-800">내보내기 실패</p>
            <p className="mt-1 text-xs text-red-600">{exportError}</p>
            <button type="button" onClick={() => setExportError(null)} className="mt-2 text-xs text-red-700 underline">닫기</button>
          </div>
        )}

        {exportNotice && (
          <div className="fixed bottom-6 right-6 z-50 max-w-sm rounded-lg border border-amber-200 bg-amber-50 p-4 shadow-lg">
            <p className="text-sm font-medium text-amber-800">일부 클립만 내보냄</p>
            <p className="mt-1 text-xs text-amber-700">{exportNotice}</p>
            <button type="button" onClick={() => setExportNotice(null)} className="mt-2 text-xs text-amber-700 underline">닫기</button>
          </div>
        )}

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
