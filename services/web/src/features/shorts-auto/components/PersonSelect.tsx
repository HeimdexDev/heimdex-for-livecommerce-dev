"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import { getPeople } from "@/lib/api/people";
import { getFaceThumbnailUrl } from "@/lib/agent";
import { cn } from "@/lib/utils";
import { PersonIcon } from "@/components/icons";
import type { PersonResponse } from "@/lib/types";

interface PersonSelectProps {
  value: string | null;
  onChange: (personClusterId: string | null) => void;
  disabled?: boolean;
}

/**
 * Searchable combobox that lazy-loads the org's people list from
 * /api/people on first open. NOT a fork of
 * `features/people/PersonPickerDropdown` — that component expects a
 * pre-fetched list with `excludeIds` semantics for video-linking.
 *
 * Keyboard nav: ArrowDown/ArrowUp/Enter/Escape, with roving aria-activedescendant.
 */
export function PersonSelect({ value, onChange, disabled = false }: PersonSelectProps) {
  const { getAccessToken } = useAuth();
  const [isOpen, setIsOpen] = useState(false);
  const [people, setPeople] = useState<PersonResponse[] | null>(null);
  const [loadError, setLoadError] = useState<Error | null>(null);
  const [search, setSearch] = useState("");
  const [activeIndex, setActiveIndex] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const listboxRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Lazy fetch on first open
  useEffect(() => {
    if (!isOpen || people !== null || loadError !== null) return;
    let cancelled = false;
    getPeople(getAccessToken)
      .then((res) => {
        if (!cancelled) setPeople(res.people ?? []);
      })
      .catch((err) => {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err : new Error(String(err)));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen, people, loadError, getAccessToken]);

  // Click outside + Escape close
  useEffect(() => {
    if (!isOpen) return;
    const onMouse = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsOpen(false);
    };
    document.addEventListener("mousedown", onMouse);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onMouse);
      document.removeEventListener("keydown", onKey);
    };
  }, [isOpen]);

  // Focus input on open
  useEffect(() => {
    if (isOpen) inputRef.current?.focus();
  }, [isOpen]);

  const filtered = useMemo(() => {
    if (!people) return [];
    const q = search.trim().toLowerCase();
    if (!q) return people;
    return people.filter((p) => (p.label ?? "").toLowerCase().includes(q));
  }, [people, search]);

  const selectedPerson = useMemo(
    () => (value && people ? people.find((p) => p.person_cluster_id === value) ?? null : null),
    [value, people],
  );

  const handleSelect = useCallback(
    (person: PersonResponse) => {
      onChange(person.person_cluster_id);
      setIsOpen(false);
      setSearch("");
      setActiveIndex(-1);
    },
    [onChange],
  );

  const handleRetry = useCallback(() => {
    // Clearing loadError + people triggers the fetch effect on next render.
    setLoadError(null);
    setPeople(null);
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIndex((i) => Math.min(i + 1, filtered.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIndex((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        const target = filtered[activeIndex];
        if (target) handleSelect(target);
      } else if (e.key === "Home") {
        setActiveIndex(0);
      } else if (e.key === "End") {
        setActiveIndex(filtered.length - 1);
      }
    },
    [filtered, activeIndex, handleSelect],
  );

  const activeOptionId =
    activeIndex >= 0 && filtered[activeIndex]
      ? `auto-shorts-person-option-${filtered[activeIndex].person_cluster_id}`
      : undefined;

  return (
    <div ref={containerRef} className="relative w-full">
      <button
        type="button"
        role="combobox"
        aria-expanded={isOpen}
        aria-controls="auto-shorts-person-listbox"
        aria-haspopup="listbox"
        disabled={disabled}
        onClick={() => setIsOpen((o) => !o)}
        className={cn(
          "flex w-full items-center justify-between gap-2 rounded-lg border px-3 py-2 text-left text-sm",
          "focus:border-indigo-400 focus:outline-none focus:ring-2 focus:ring-indigo-500",
          disabled ? "cursor-not-allowed border-gray-200 bg-gray-50 text-gray-400" : "border-gray-300 bg-white text-gray-900",
        )}
      >
        <span className="flex min-w-0 items-center gap-2">
          {selectedPerson ? (
            <PersonPickerThumb person={selectedPerson} />
          ) : (
            <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-gray-100">
              <PersonIcon className="h-4 w-4 text-gray-400" />
            </span>
          )}
          <span className={cn("truncate", selectedPerson ? "text-gray-900" : "text-gray-400")}>
            {selectedPerson ? selectedPerson.label ?? "이름 없음" : "인물을 선택해 주세요"}
          </span>
        </span>
        <svg aria-hidden="true" className="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
        </svg>
      </button>

      {isOpen && (
        <div
          className="absolute left-0 right-0 top-full z-50 mt-1 rounded-lg border border-gray-200 bg-white shadow-xl"
        >
          <div className="border-b border-gray-100 p-2">
            <input
              ref={inputRef}
              type="text"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setActiveIndex(-1);
              }}
              onKeyDown={handleKeyDown}
              placeholder="인물 검색..."
              aria-autocomplete="list"
              aria-controls="auto-shorts-person-listbox"
              aria-activedescendant={activeOptionId}
              className="w-full rounded-md border border-gray-200 px-3 py-1.5 text-sm focus:border-indigo-300 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>
          <div
            ref={listboxRef}
            id="auto-shorts-person-listbox"
            role="listbox"
            className="max-h-60 overflow-y-auto p-1"
          >
            {people === null && loadError === null ? (
              <p className="px-3 py-4 text-center text-sm text-gray-400">불러오는 중...</p>
            ) : loadError ? (
              <div className="flex flex-col items-center gap-2 px-3 py-4 text-center">
                <p className="text-sm text-red-500">인물 목록을 불러오지 못했습니다.</p>
                <button
                  type="button"
                  onClick={handleRetry}
                  className="rounded-md border border-gray-300 bg-white px-3 py-1 text-xs text-gray-700 transition-colors hover:bg-gray-50"
                >
                  다시 시도
                </button>
              </div>
            ) : filtered.length === 0 ? (
              <p className="px-3 py-4 text-center text-sm text-gray-400">
                {search ? "검색 결과가 없습니다" : "등록된 인물이 없습니다"}
              </p>
            ) : (
              filtered.map((p, i) => (
                <PersonOption
                  key={p.person_cluster_id}
                  person={p}
                  active={i === activeIndex}
                  selected={p.person_cluster_id === value}
                  onSelect={() => handleSelect(p)}
                />
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function PersonPickerThumb({ person }: { person: PersonResponse }) {
  const [err, setErr] = useState(false);
  const url = getFaceThumbnailUrl(person.person_cluster_id);
  if (err) {
    return (
      <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-gray-100">
        <PersonIcon className="h-4 w-4 text-gray-400" />
      </span>
    );
  }
  return (
    <img
      src={url}
      alt=""
      aria-hidden="true"
      className="h-6 w-6 flex-shrink-0 rounded-full object-cover"
      onError={() => setErr(true)}
    />
  );
}

function PersonOption({
  person,
  active,
  selected,
  onSelect,
}: {
  person: PersonResponse;
  active: boolean;
  selected: boolean;
  onSelect: () => void;
}) {
  const [imgError, setImgError] = useState(false);
  const url = getFaceThumbnailUrl(person.person_cluster_id);

  return (
    <button
      type="button"
      role="option"
      id={`auto-shorts-person-option-${person.person_cluster_id}`}
      aria-selected={selected}
      onClick={onSelect}
      className={cn(
        "flex w-full items-center gap-3 rounded-md px-3 py-2 text-left transition-colors",
        active && "bg-indigo-50",
        selected && !active && "bg-indigo-50/40",
        "hover:bg-gray-50",
      )}
    >
      {!imgError ? (
        <img
          src={url}
          alt=""
          aria-hidden="true"
          className="h-8 w-8 flex-shrink-0 rounded-full object-cover"
          onError={() => setImgError(true)}
        />
      ) : (
        <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-gray-100">
          <PersonIcon className="h-5 w-5 text-gray-400" />
        </div>
      )}
      <div className="min-w-0 flex-1">
        <span className={cn("block truncate text-sm", person.label ? "text-gray-900" : "text-gray-400")}>
          {person.label ?? "이름 없음"}
        </span>
        {person.face_count > 0 && (
          <span className="text-xs text-gray-400">{person.face_count}개 장면</span>
        )}
      </div>
    </button>
  );
}
