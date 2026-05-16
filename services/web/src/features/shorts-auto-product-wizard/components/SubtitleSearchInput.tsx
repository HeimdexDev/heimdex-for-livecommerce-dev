// ============================================================================
// Search input above the 자막 tab's cue list. Mirrors the existing
// ``SubtitleEditorRow`` IME-safe composition handling (Decision #3) so a
// Korean operator typing 한국어 doesn't trigger filters mid-syllable.
// ============================================================================

"use client";

import { useCallback, useState, type ChangeEvent } from "react";

import { cn } from "@/lib/utils";

interface Props {
  /** Committed query string (post-composition). Parent owns it. */
  query: string;
  /** Fires only after IME composition is complete (or for non-IME input). */
  onQueryChange: (query: string) => void;
  className?: string;
  placeholder?: string;
}

export function SubtitleSearchInput({
  query,
  onQueryChange,
  className,
  placeholder = "찾고 싶은 자막을 검색하세요.",
}: Props) {
  const [localValue, setLocalValue] = useState(query);
  const [isComposing, setIsComposing] = useState(false);

  // Keep local state in sync if parent resets the query (e.g. clip switch).
  // Compare strings, not refs, so the user's typed-but-not-committed state
  // doesn't get clobbered every render.
  if (!isComposing && query !== localValue) {
    // Read-render-only guard above; safe to setState here. React 18 batches
    // this with the render so no infinite-loop risk.
    setLocalValue(query);
  }

  const handleChange = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      const next = e.target.value;
      setLocalValue(next);
      if (!isComposing) onQueryChange(next);
    },
    [isComposing, onQueryChange],
  );

  const handleCompositionEnd = useCallback(
    (e: { currentTarget: HTMLInputElement }) => {
      setIsComposing(false);
      onQueryChange(e.currentTarget.value);
    },
    [onQueryChange],
  );

  const handleClear = useCallback(() => {
    setLocalValue("");
    onQueryChange("");
  }, [onQueryChange]);

  return (
    <div
      className={cn("relative", className)}
      data-testid="subtitle-search-input-container"
    >
      <input
        type="search"
        value={localValue}
        placeholder={placeholder}
        onChange={handleChange}
        onCompositionStart={() => setIsComposing(true)}
        onCompositionEnd={handleCompositionEnd}
        className="w-full rounded-md border border-gray-200 bg-gray-50 px-3 py-2 pr-8 text-sm text-gray-900 placeholder-gray-400 focus:border-indigo-400 focus:bg-white focus:outline-none focus:ring-1 focus:ring-indigo-400"
        data-testid="subtitle-search-input"
      />
      {localValue.length > 0 ? (
        <button
          type="button"
          onClick={handleClear}
          aria-label="검색 지우기"
          className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full bg-gray-200 px-2 py-0.5 text-xs text-gray-600 hover:bg-gray-300"
          data-testid="subtitle-search-input-clear"
        >
          ✕
        </button>
      ) : null}
    </div>
  );
}
