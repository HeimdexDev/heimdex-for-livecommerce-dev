"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { cn } from "@/lib/utils";

interface TooltipProps {
  content: string;
  children: React.ReactNode;
  delayMs?: number;
  className?: string;
}

export function Tooltip({
  content,
  children,
  delayMs = 150,
  className,
}: TooltipProps) {
  const [visible, setVisible] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const handleMouseEnter = useCallback(() => {
    clearTimer();
    timerRef.current = setTimeout(() => setVisible(true), delayMs);
  }, [delayMs, clearTimer]);

  const handleMouseLeave = useCallback(() => {
    clearTimer();
    setVisible(false);
  }, [clearTimer]);

  useEffect(() => clearTimer, [clearTimer]);

  return (
    <div
      className={cn("relative", className)}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {children}

      <div
        role="tooltip"
        className={cn(
          "absolute left-1/2 top-full z-50 mt-2 -translate-x-1/2 pointer-events-none transition-opacity duration-150",
          visible ? "opacity-100" : "opacity-0",
        )}
      >
        <div className="flex justify-center">
          <div className="h-2 w-2 translate-y-1 rotate-45 bg-gray-800" />
        </div>
        <div className="whitespace-nowrap rounded-lg bg-gray-800 px-3 py-2 text-xs text-white shadow-lg">
          {content}
        </div>
      </div>
    </div>
  );
}
