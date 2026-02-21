"use client";

import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { getVideos, getVideoStats } from "@/lib/api/videos";
import { searchScenes } from "@/lib/api/search";
import { SceneThumbnail } from "@/components/SceneThumbnail";
import type { VideoSummary, VideoStats, SceneResult } from "@/lib/types";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const PAGE_SIZE = 16;
const KOREAN_DAYS = ["일", "월", "화", "수", "목", "금", "토"] as const;

// ---------------------------------------------------------------------------
// Icons
// ---------------------------------------------------------------------------
function SearchIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={1.5}
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"
      />
    </svg>
  );
}

function VideoIcon() {
  return (
    <svg
      className="h-5 w-5 text-gray-400"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={1.5}
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M15.75 10.5l4.72-4.72a.75.75 0 011.28.53v11.38a.75.75 0 01-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 002.25-2.25v-9a2.25 2.25 0 00-2.25-2.25h-9A2.25 2.25 0 002.25 7.5v9a2.25 2.25 0 002.25 2.25z"
      />
    </svg>
  );
}

function FolderIcon() {
  return (
    <svg
      className="h-5 w-5 text-gray-400"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={1.5}
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z"
      />
    </svg>
  );
}

function ClockIcon() {
  return (
    <svg
      className="h-5 w-5 text-gray-400"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={1.5}
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z"
      />
    </svg>
  );
}

function CalendarIcon() {
  return (
    <svg
      className="h-4 w-4 text-gray-400"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={1.5}
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5"
      />
    </svg>
  );
}

function EmptyStateIcon() {
  return (
    <svg
      className="h-16 w-16 text-gray-300"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={1}
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M3.75 21h16.5A2.25 2.25 0 0022.5 18.75V5.25A2.25 2.25 0 0020.25 3H3.75A2.25 2.25 0 001.5 5.25v13.5A2.25 2.25 0 003.75 21z"
      />
    </svg>
  );
}

function ChevronDownIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className ?? "h-4 w-4"}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M19.5 8.25l-7.5 7.5-7.5-7.5"
      />
    </svg>
  );
}

function ChevronLeftIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className ?? "h-4 w-4"}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M15.75 19.5L8.25 12l7.5-7.5"
      />
    </svg>
  );
}

function ChevronRightIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className ?? "h-4 w-4"}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M8.25 4.5l7.5 7.5-7.5 7.5"
      />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function formatDateKr(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

function isInRange(day: Date, start: Date | null, end: Date | null): boolean {
  if (!start || !end) return false;
  const t = day.getTime();
  const s = new Date(
    start.getFullYear(),
    start.getMonth(),
    start.getDate(),
  ).getTime();
  const e = new Date(
    end.getFullYear(),
    end.getMonth(),
    end.getDate(),
  ).getTime();
  return t >= s && t <= e;
}

function getDaysInMonth(year: number, month: number): number {
  return new Date(year, month + 1, 0).getDate();
}

function getFirstDayOfWeek(year: number, month: number): number {
  return new Date(year, month, 1).getDay();
}

// ---------------------------------------------------------------------------
// DateRangeCalendar
// ---------------------------------------------------------------------------
interface DateRangeCalendarProps {
  startDate: Date | null;
  endDate: Date | null;
  onSelect: (start: Date, end: Date) => void;
  onClose: () => void;
}

function DateRangeCalendar({
  startDate,
  endDate,
  onSelect,
  onClose,
}: DateRangeCalendarProps) {
  const today = useMemo(() => new Date(), []);
  const [viewYear, setViewYear] = useState(
    startDate?.getFullYear() ?? today.getFullYear(),
  );
  const [viewMonth, setViewMonth] = useState(
    startDate?.getMonth() ?? today.getMonth(),
  );
  const [selStart, setSelStart] = useState<Date | null>(startDate);
  const [selEnd, setSelEnd] = useState<Date | null>(endDate);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handle(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [onClose]);

  const daysInMonth = getDaysInMonth(viewYear, viewMonth);
  const firstDay = getFirstDayOfWeek(viewYear, viewMonth);

  function handlePrev() {
    if (viewMonth === 0) {
      setViewYear((y) => y - 1);
      setViewMonth(11);
    } else {
      setViewMonth((m) => m - 1);
    }
  }

  function handleNext() {
    if (viewMonth === 11) {
      setViewYear((y) => y + 1);
      setViewMonth(0);
    } else {
      setViewMonth((m) => m + 1);
    }
  }

  function handleDayClick(day: number) {
    const clicked = new Date(viewYear, viewMonth, day);
    if (!selStart || (selStart && selEnd)) {
      setSelStart(clicked);
      setSelEnd(null);
    } else {
      if (clicked.getTime() < selStart.getTime()) {
        setSelEnd(selStart);
        setSelStart(clicked);
        onSelect(clicked, selStart);
      } else {
        setSelEnd(clicked);
        onSelect(selStart, clicked);
      }
    }
  }

  const cells: (number | null)[] = [];
  for (let i = 0; i < firstDay; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);

  return (
    <div
      ref={ref}
      className="absolute right-0 top-full z-50 mt-2 w-[300px] rounded-xl border border-gray-200 bg-white p-4 shadow-lg"
    >
      {/* header */}
      <div className="mb-3 flex items-center justify-between">
        <button
          type="button"
          onClick={handlePrev}
          className="rounded-lg p-1 hover:bg-gray-100"
        >
          <ChevronLeftIcon className="h-4 w-4 text-gray-500" />
        </button>
        <span className="text-sm font-semibold text-gray-900">
          {viewYear}년 {viewMonth + 1}월
        </span>
        <button
          type="button"
          onClick={handleNext}
          className="rounded-lg p-1 hover:bg-gray-100"
        >
          <ChevronRightIcon className="h-4 w-4 text-gray-500" />
        </button>
      </div>

      {/* day headers */}
      <div className="mb-1 grid grid-cols-7 text-center text-xs font-medium text-gray-400">
        {KOREAN_DAYS.map((d) => (
          <div key={d} className="py-1">
            {d}
          </div>
        ))}
      </div>

      {/* days grid */}
      <div className="grid grid-cols-7 text-center text-sm">
        {cells.map((day, i) => {
          if (day === null) {
            return <div key={`empty-${i}`} className="py-1.5" />;
          }
          const date = new Date(viewYear, viewMonth, day);
          const isToday = isSameDay(date, today);
          const isStart = selStart ? isSameDay(date, selStart) : false;
          const isEnd = selEnd ? isSameDay(date, selEnd) : false;
          const inRange = isInRange(date, selStart, selEnd);

          return (
            <button
              key={day}
              type="button"
              onClick={() => handleDayClick(day)}
              className={cn(
                "relative py-1.5 transition-colors",
                inRange && !isStart && !isEnd && "bg-indigo-50",
                isStart && "rounded-l-full bg-indigo-500 text-white",
                isEnd && "rounded-r-full bg-indigo-500 text-white",
                !isStart && !isEnd && !inRange && "hover:bg-gray-100",
                isToday && !isStart && !isEnd && "font-bold text-indigo-600",
              )}
            >
              {day}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SortDropdown
// ---------------------------------------------------------------------------
type SortOption = "latest" | "oldest";

interface SortDropdownProps {
  value: SortOption;
  onChange: (v: SortOption) => void;
}

const SORT_LABELS: Record<SortOption, string> = {
  latest: "생성 일자순",
  oldest: "총 비디오 수",
};

function SortDropdown({ value, onChange }: SortDropdownProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handle(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
      >
        {SORT_LABELS[value]}
        <ChevronDownIcon className="h-4 w-4" />
      </button>
      {open && (
        <div className="absolute right-0 top-full z-40 mt-1 w-36 rounded-lg border border-gray-200 bg-white py-1 shadow-lg">
          {(Object.keys(SORT_LABELS) as SortOption[]).map((opt) => (
            <button
              key={opt}
              type="button"
              onClick={() => {
                onChange(opt);
                setOpen(false);
              }}
              className={cn(
                "w-full px-3 py-2 text-left text-sm transition-colors hover:bg-gray-50",
                value === opt
                  ? "font-medium text-indigo-600"
                  : "text-gray-700",
              )}
            >
              {SORT_LABELS[opt]}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pagination
// ---------------------------------------------------------------------------
interface PaginationProps {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

function Pagination({
  currentPage,
  totalPages,
  onPageChange,
}: PaginationProps) {
  if (totalPages <= 1) return null;

  const pages = useMemo(() => {
    const result: (number | "ellipsis")[] = [];
    const maxVisible = 5;

    if (totalPages <= maxVisible + 2) {
      for (let i = 1; i <= totalPages; i++) result.push(i);
    } else {
      // always show first page
      result.push(1);

      let start = Math.max(2, currentPage - 1);
      let end = Math.min(totalPages - 1, currentPage + 1);

      // adjust window
      if (currentPage <= 3) {
        start = 2;
        end = Math.min(maxVisible, totalPages - 1);
      } else if (currentPage >= totalPages - 2) {
        start = Math.max(2, totalPages - maxVisible + 1);
        end = totalPages - 1;
      }

      if (start > 2) result.push("ellipsis");
      for (let i = start; i <= end; i++) result.push(i);
      if (end < totalPages - 1) result.push("ellipsis");

      // always show last page
      result.push(totalPages);
    }
    return result;
  }, [currentPage, totalPages]);

  const btnBase =
    "inline-flex h-8 w-8 items-center justify-center rounded text-sm transition-colors";

  return (
    <nav className="mt-8 flex items-center justify-center gap-1">
      {/* first */}
      <button
        type="button"
        disabled={currentPage === 1}
        onClick={() => onPageChange(1)}
        className={cn(
          btnBase,
          currentPage === 1
            ? "cursor-not-allowed text-gray-300"
            : "text-gray-500 hover:bg-gray-100",
        )}
        aria-label="처음"
      >
        &laquo;
      </button>
      {/* prev */}
      <button
        type="button"
        disabled={currentPage === 1}
        onClick={() => onPageChange(currentPage - 1)}
        className={cn(
          btnBase,
          currentPage === 1
            ? "cursor-not-allowed text-gray-300"
            : "text-gray-500 hover:bg-gray-100",
        )}
        aria-label="이전"
      >
        &lsaquo;
      </button>

      {pages.map((p, i) =>
        p === "ellipsis" ? (
          <span
            key={`ell-${i}`}
            className="inline-flex h-8 w-8 items-center justify-center text-sm text-gray-400"
          >
            &hellip;
          </span>
        ) : (
          <button
            key={p}
            type="button"
            onClick={() => onPageChange(p)}
            className={cn(
              btnBase,
              currentPage === p
                ? "bg-indigo-500 font-medium text-white"
                : "text-gray-600 hover:bg-gray-100",
            )}
          >
            {p}
          </button>
        ),
      )}

      {/* next */}
      <button
        type="button"
        disabled={currentPage === totalPages}
        onClick={() => onPageChange(currentPage + 1)}
        className={cn(
          btnBase,
          currentPage === totalPages
            ? "cursor-not-allowed text-gray-300"
            : "text-gray-500 hover:bg-gray-100",
        )}
        aria-label="다음"
      >
        &rsaquo;
      </button>
      {/* last */}
      <button
        type="button"
        disabled={currentPage === totalPages}
        onClick={() => onPageChange(totalPages)}
        className={cn(
          btnBase,
          currentPage === totalPages
            ? "cursor-not-allowed text-gray-300"
            : "text-gray-500 hover:bg-gray-100",
        )}
        aria-label="마지막"
      >
        &raquo;
      </button>
    </nav>
  );
}

// ---------------------------------------------------------------------------
// VideoCard
// ---------------------------------------------------------------------------
function VideoCard({ video }: { video: VideoSummary }) {
  const title = video.video_title || "제목 없음";
  return (
    <Link href={`/videos/${video.video_id}`} className="group cursor-pointer block">
      <SceneThumbnail
        videoId={video.video_id}
        sceneId={video.source_type === "gdrive" ? `${video.video_id}_scene_000` : undefined}
        agentAvailable={true}
        className="aspect-video w-full rounded-lg"
        sourceType={video.source_type}
      />
      <p className="mt-2 truncate text-sm font-medium text-gray-800 group-hover:text-indigo-600">
        {title}
      </p>
    </Link>
  );
}

function SceneCard({ scene }: { scene: SceneResult }) {
  const title = scene.video_title || "제목 없음";
  const startSec = Math.round(scene.start_ms / 1000);
  const min = Math.floor(startSec / 60);
  const sec = startSec % 60;
  const timestamp = `${min}:${String(sec).padStart(2, "0")}`;

  return (
    <Link href={`/videos/${scene.video_id}`} className="group cursor-pointer block">
      <div className="relative aspect-video w-full overflow-hidden rounded-lg">
        <SceneThumbnail
          videoId={scene.video_id}
          sceneId={scene.scene_id}
          agentAvailable={true}
          className="w-full h-full"
          sourceType={scene.source_type}
        />
        <span className="absolute bottom-1.5 right-1.5 rounded bg-black/70 px-1.5 py-0.5 text-xs text-white">
          {timestamp}
        </span>
      </div>
      <p className="mt-2 truncate text-sm font-medium text-gray-800 group-hover:text-indigo-600">
        {title}
      </p>
      {scene.snippet && (
        <p className="mt-0.5 line-clamp-2 text-xs text-gray-500">
          {scene.snippet}
        </p>
      )}
    </Link>
  );
}

// ---------------------------------------------------------------------------
// DashboardContent (main export)
// ---------------------------------------------------------------------------
export default function DashboardContent() {
  const { getAccessToken } = useAuth();

  const [videos, setVideos] = useState<VideoSummary[]>([]);
  const [totalVideos, setTotalVideos] = useState(0);
  const [stats, setStats] = useState<VideoStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [sortBy, setSortBy] = useState<SortOption>("latest");
  const [currentPage, setCurrentPage] = useState(1);
  const [dateStart, setDateStart] = useState<Date | null>(() => {
    const d = new Date();
    d.setDate(d.getDate() - 7);
    return d;
  });
  const [dateEnd, setDateEnd] = useState<Date | null>(() => new Date());
  const [showCalendar, setShowCalendar] = useState(false);

  const [searchResults, setSearchResults] = useState<SceneResult[] | null>(null);
  const [activeQuery, setActiveQuery] = useState("");
  const isSearchMode = searchResults !== null;

  const fetchData = useCallback(async () => {
    setIsLoading(true);
    setNextCursor(null);
    try {
      const tokenGetter = () => getAccessToken();
      const [videosRes, statsRes] = await Promise.all([
        getVideos(
          {
            sort: sortBy,
            page_size: 20,
            date_from: dateStart ? formatDateKr(dateStart) : undefined,
            date_to: dateEnd ? formatDateKr(dateEnd) : undefined,
          },
          tokenGetter,
        ),
        getVideoStats(tokenGetter),
      ]);
      setVideos(videosRes.videos);
      setTotalVideos(videosRes.total);
      setNextCursor(videosRes.next_cursor);
      setStats(statsRes);
    } catch {
      setVideos([]);
      setTotalVideos(0);
      setNextCursor(null);
    } finally {
      setIsLoading(false);
    }
  }, [getAccessToken, sortBy, dateStart, dateEnd]);

  const loadMore = useCallback(async () => {
    if (!nextCursor || isLoadingMore) return;
    setIsLoadingMore(true);
    try {
      const tokenGetter = () => getAccessToken();
      const videosRes = await getVideos(
        {
          sort: sortBy,
          page_size: 20,
          date_from: dateStart ? formatDateKr(dateStart) : undefined,
          date_to: dateEnd ? formatDateKr(dateEnd) : undefined,
          after: nextCursor,
        },
        tokenGetter,
      );
      setVideos((prev) => [...prev, ...videosRes.videos]);
      setTotalVideos(videosRes.total);
      setNextCursor(videosRes.next_cursor);
    } catch {
      // Keep existing videos, just stop loading more
    } finally {
      setIsLoadingMore(false);
    }
  }, [getAccessToken, nextCursor, isLoadingMore, sortBy, dateStart, dateEnd]);

  useEffect(() => {
    if (!isSearchMode) {
      fetchData();
    }
  }, [fetchData, isSearchMode]);

  const searchTotalPages = Math.max(1, Math.ceil((searchResults?.length ?? 0) / PAGE_SIZE));

  const totalPages = isSearchMode ? searchTotalPages : 1;

  const paginatedScenes = useMemo(() => {
    if (!searchResults) return [];
    const start = (currentPage - 1) * PAGE_SIZE;
    return searchResults.slice(start, start + PAGE_SIZE);
  }, [searchResults, currentPage]);

  useEffect(() => {
    setCurrentPage(1);
  }, [sortBy]);

  const handleSearch = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      const q = query.trim();
      if (!q) return;

      setIsLoading(true);
      setCurrentPage(1);
      try {
        const tokenGetter = () => getAccessToken();
        const res = await searchScenes(
          { q, alpha: 0.5, filters: {} },
          tokenGetter,
        );
        setSearchResults(res.results);
        setActiveQuery(q);
      } catch {
        setSearchResults([]);
        setActiveQuery(q);
      } finally {
        setIsLoading(false);
      }
    },
    [query, getAccessToken],
  );

  const handleClearSearch = useCallback(() => {
    setSearchResults(null);
    setActiveQuery("");
    setQuery("");
    setCurrentPage(1);
  }, []);

  const handleDateSelect = useCallback((start: Date, end: Date) => {
    setDateStart(start);
    setDateEnd(end);
    setShowCalendar(false);
    setCurrentPage(1);
  }, []);

  const videoCount = isSearchMode ? (searchResults?.length ?? 0) : totalVideos;
  const libraryCount = stats?.total_libraries ?? 0;
  const hasResults = isSearchMode
    ? (searchResults?.length ?? 0) > 0
    : videos.length > 0;

  const dateLabel = useMemo(() => {
    if (!dateStart || !dateEnd) return "";
    return `${formatDateKr(dateStart)} | ${formatDateKr(dateEnd)}`;
  }, [dateStart, dateEnd]);

  return (
    <div className="mx-auto max-w-5xl pt-4">
      {/* Search section */}
      <div className="rounded-xl bg-white p-6 shadow-sm">
        <h2 className="mb-5 text-lg font-bold text-gray-900">
          전체 아카이브 내 검색
        </h2>

        <form onSubmit={handleSearch} className="flex items-center gap-3">
          <div className="relative flex-1">
            <SearchIcon className="absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="전체 아카이브에서 검색하고 싶은 영상을 찾아보세요"
              className="w-full rounded-lg border border-gray-200 bg-gray-50 py-3 pl-12 pr-4 text-sm text-gray-900 placeholder:text-gray-400 focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
            />
          </div>
          <button
            type="submit"
            disabled={isLoading || !query.trim()}
            className={cn(
              "rounded-lg px-6 py-3 text-sm font-medium transition-colors",
              query.trim()
                ? "bg-indigo-500 text-white hover:bg-indigo-600"
                : "cursor-not-allowed bg-gray-200 text-gray-400",
            )}
          >
            검색
          </button>
        </form>
      </div>

      {/* Results section */}
      <div className="mt-4 rounded-xl bg-white p-6 shadow-sm">
        {/* Title + date range */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-bold text-gray-900">
              {isSearchMode ? `"${activeQuery}" 검색 결과` : "검색된 영상"}
            </h2>
            {isSearchMode && (
              <button
                type="button"
                onClick={handleClearSearch}
                className="rounded-md bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-600 transition-colors hover:bg-gray-200"
              >
                초기화
              </button>
            )}
          </div>
          {!isSearchMode && (
            <div className="relative">
              <button
                type="button"
                onClick={() => setShowCalendar((v) => !v)}
                className="flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-600 transition-colors hover:border-gray-300"
              >
                <CalendarIcon />
                <span>{dateLabel}</span>
              </button>
              {showCalendar && (
                <DateRangeCalendar
                  startDate={dateStart}
                  endDate={dateEnd}
                  onSelect={handleDateSelect}
                  onClose={() => setShowCalendar(false)}
                />
              )}
            </div>
          )}
        </div>

        {/* Info banner */}
        {hasResults && !isSearchMode && (
          <p className="mt-2 text-sm text-gray-500">
            <Link
              href="/settings/people"
              className="text-indigo-500 underline-offset-2 hover:text-indigo-600 hover:underline"
            >
              인물 라벨 관리
            </Link>
            에서 특정 인물을 선택하여 검색 결과를 필터링할 수 있습니다.
          </p>
        )}

        {/* Stats + Sort */}
        <div className="mt-4 flex items-center justify-between border-b border-gray-100 pb-4">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-1.5 text-sm text-gray-600">
              <VideoIcon />
              <span>
                {isSearchMode
                  ? `${videoCount} scenes`
                  : `${videoCount} videos`}
              </span>
            </div>
            {!isSearchMode && (
              <>
                <div className="flex items-center gap-1.5 text-sm text-gray-600">
                  <FolderIcon />
                  <span>{libraryCount} folders</span>
                </div>
                <div className="flex items-center gap-1.5 text-sm text-gray-600">
                  <ClockIcon />
                  <span>
                    {(stats?.latest_capture_time || stats?.latest_ingest_time)
                      ? new Date(
                          stats.latest_capture_time || stats.latest_ingest_time!,
                        ).toLocaleDateString("ko-KR")
                      : "N/A"}
                  </span>
                </div>
              </>
            )}
          </div>
          {!isSearchMode && (
            <SortDropdown value={sortBy} onChange={setSortBy} />
          )}
        </div>

        {/* Loading */}
        {isLoading && (
          <div className="flex items-center justify-center py-20">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-300 border-t-indigo-500" />
          </div>
        )}

        {/* Empty state */}
        {!isLoading && !hasResults && (
          <div className="flex flex-col items-center py-20">
            <EmptyStateIcon />
            <h3 className="mt-6 text-lg font-bold text-gray-900">
              {isSearchMode
                ? "검색 결과가 없습니다."
                : "검색할 영상이 없습니다."}
            </h3>
            <p className="mt-2 text-sm text-gray-500">
              {isSearchMode
                ? "다른 검색어로 시도해주세요."
                : "파일 동기화부터 진행해주세요."}
            </p>
            {isSearchMode ? (
              <button
                type="button"
                onClick={handleClearSearch}
                className="mt-6 inline-flex items-center gap-1.5 rounded-lg bg-indigo-500 px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-indigo-600"
              >
                전체 영상으로 돌아가기
              </button>
            ) : (
              <Link
                href="/sync"
                className="mt-6 inline-flex items-center gap-1.5 rounded-lg bg-indigo-500 px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-indigo-600"
              >
                파일 동기화로 이동
                <ChevronRightIcon className="h-4 w-4" />
              </Link>
            )}
          </div>
        )}

        {/* Results grid */}
        {!isLoading && hasResults && (
          <>
            <div className="mt-6 grid grid-cols-2 gap-5 sm:grid-cols-3 lg:grid-cols-4">
              {isSearchMode
                ? paginatedScenes.map((scene) => (
                    <SceneCard key={scene.scene_id} scene={scene} />
                  ))
                : videos.map((video) => (
                    <VideoCard key={video.video_id} video={video} />
                  ))}
            </div>

            {isSearchMode ? (
              <Pagination
                currentPage={currentPage}
                totalPages={totalPages}
                onPageChange={setCurrentPage}
              />
            ) : nextCursor ? (
              <div className="mt-8 flex justify-center">
                <button
                  type="button"
                  onClick={loadMore}
                  disabled={isLoadingMore}
                  className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-6 py-3 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {isLoadingMore ? (
                    <>
                      <div className="h-4 w-4 animate-spin rounded-full border-2 border-gray-300 border-t-indigo-500" />
                      불러오는 중...
                    </>
                  ) : (
                    <>
                      더 보기
                      <span className="text-xs text-gray-400">
                        ({videos.length} / {totalVideos})
                      </span>
                    </>
                  )}
                </button>
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
