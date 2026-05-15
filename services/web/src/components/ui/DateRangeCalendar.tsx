"use client";

import { useState, useEffect, useRef, useMemo } from "react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const KOREAN_DAYS = ["일", "월", "화", "수", "목", "금", "토"] as const;

function getDaysInMonth(year: number, month: number): number {
  return new Date(year, month + 1, 0).getDate();
}

function getFirstDayOfWeek(year: number, month: number): number {
  return new Date(year, month, 1).getDay();
}

export function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

export function isInRange(day: Date, start: Date | null, end: Date | null): boolean {
  if (!start || !end) return false;
  const t = day.getTime();
  const s = new Date(start.getFullYear(), start.getMonth(), start.getDate()).getTime();
  const e = new Date(end.getFullYear(), end.getMonth(), end.getDate()).getTime();
  return t >= s && t <= e;
}

export function formatDateKr(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

// ---------------------------------------------------------------------------
// Icons
// ---------------------------------------------------------------------------
function ChevronLeftIcon({ className }: { className?: string }) {
  return (
    <svg className={className ?? "h-4 w-4"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
    </svg>
  );
}

function ChevronRightIcon({ className }: { className?: string }) {
  return (
    <svg className={className ?? "h-4 w-4"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// DateRangeCalendar
// ---------------------------------------------------------------------------
export interface DateRangeCalendarProps {
  startDate: Date | null;
  endDate: Date | null;
  onSelect: (start: Date, end: Date) => void;
  onClose: () => void;
}

export function DateRangeCalendar({
  startDate,
  endDate,
  onSelect,
  onClose,
}: DateRangeCalendarProps) {
  const today = useMemo(() => new Date(), []);
  const [viewYear, setViewYear] = useState(startDate?.getFullYear() ?? today.getFullYear());
  const [viewMonth, setViewMonth] = useState(startDate?.getMonth() ?? today.getMonth());
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
      <div className="mb-3 flex items-center justify-between">
        <button type="button" onClick={handlePrev} className="rounded-lg p-1 hover:bg-gray-100">
          <ChevronLeftIcon className="h-4 w-4 text-gray-500" />
        </button>
        <span className="text-sm font-semibold text-gray-900">
          {viewYear}년 {viewMonth + 1}월
        </span>
        <button type="button" onClick={handleNext} className="rounded-lg p-1 hover:bg-gray-100">
          <ChevronRightIcon className="h-4 w-4 text-gray-500" />
        </button>
      </div>

      <div className="mb-1 grid grid-cols-7 text-center text-xs font-medium text-gray-400">
        {KOREAN_DAYS.map((d) => (
          <div key={d} className="py-1">{d}</div>
        ))}
      </div>

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
