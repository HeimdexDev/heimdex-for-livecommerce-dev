"use client";

import { useState, useRef, type KeyboardEvent } from "react";
import { cn } from "@/lib/utils";
import { TAG_FILTER_MAX_ITEMS, sanitizeTag } from "@/lib/types/search";

interface TagFilterInputProps {
  tags: string[];
  onChange: (tags: string[]) => void;
  placeholder?: string;
  maxItems?: number;
}

export function TagFilterInput({
  tags,
  onChange,
  placeholder = "Type and press Enter",
  maxItems = TAG_FILTER_MAX_ITEMS,
}: TagFilterInputProps) {
  const [inputValue, setInputValue] = useState("");
  const [limitHit, setLimitHit] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const addTag = (raw: string) => {
    const tag = sanitizeTag(raw);
    if (!tag) return;
    if (tags.includes(tag)) {
      setInputValue("");
      return;
    }
    if (tags.length >= maxItems) {
      setLimitHit(true);
      setTimeout(() => setLimitHit(false), 2000);
      return;
    }
    onChange([...tags, tag]);
    setInputValue("");
  };

  const removeTag = (index: number) => {
    onChange(tags.filter((_, i) => i !== index));
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      addTag(inputValue);
    } else if (e.key === "Backspace" && !inputValue && tags.length > 0) {
      removeTag(tags.length - 1);
    }
  };

  return (
    <div>
      <div
        className={cn(
          "flex flex-wrap gap-1 p-1.5 border rounded-md bg-white min-h-[34px] cursor-text",
          "focus-within:ring-1 focus-within:ring-primary-500 focus-within:border-primary-500",
          "border-gray-300",
        )}
        onClick={() => inputRef.current?.focus()}
      >
        {tags.map((tag, i) => (
          <span
            key={`${tag}-${i}`}
            className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-md text-xs font-medium bg-gray-100 text-gray-700 max-w-[160px]"
          >
            <span className="truncate">{tag}</span>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                removeTag(i);
              }}
              className="ml-0.5 text-gray-400 hover:text-gray-600 flex-shrink-0"
              aria-label={`Remove ${tag}`}
            >
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </span>
        ))}
        <input
          ref={inputRef}
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={tags.length === 0 ? placeholder : ""}
          className="flex-1 min-w-[60px] text-xs outline-none bg-transparent py-0.5 px-1 text-gray-700 placeholder-gray-400"
          data-testid="tag-filter-input"
        />
      </div>
      {limitHit && (
        <p className="text-xs text-amber-600 mt-0.5">
          Maximum {maxItems} tags allowed
        </p>
      )}
    </div>
  );
}
