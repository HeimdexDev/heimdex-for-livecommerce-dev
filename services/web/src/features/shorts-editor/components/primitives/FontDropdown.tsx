"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { resolveFontFamily } from "@/lib/fonts";

interface FontOption {
  value: string;
  label: string;
}

interface FontDropdownProps {
  value: string;
  options: ReadonlyArray<FontOption>;
  onChange: (next: string) => void;
  disabled?: boolean;
  ariaLabel?: string;
  className?: string;
}

// Custom popover dropdown used for font selection. Native <select>
// ignores option-level font-family in every major browser, so each
// option in a native dropdown rendered in the system font — operators
// couldn't visually preview which face they were picking. This
// component renders the option list as a plain button list so we can
// style each label with its own resolved family.
//
// Width: the menu uses ``absolute left-0 right-0`` against the relative
// wrapper so its width always matches the trigger — the user's
// screenshot showed a noticeably wider menu than its trigger button.
export function FontDropdown({
  value,
  options,
  onChange,
  disabled = false,
  ariaLabel,
  className,
}: FontDropdownProps) {
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (!wrapperRef.current) return;
      if (!wrapperRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const current = options.find((o) => o.value === value) ?? options[0];

  return (
    <div ref={wrapperRef} className={cn("relative", className)}>
      <button
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex w-full items-center justify-between rounded-[10px] border border-grayscale-300 bg-white px-[12px] py-[10px] text-left text-[14px] tracking-[-0.35px] text-grayscale-800",
          "focus:border-heimdex-navy-500 focus:outline-none focus:ring-1 focus:ring-heimdex-navy-500",
          "disabled:cursor-not-allowed disabled:bg-grayscale-100",
        )}
      >
        <span
          className="truncate"
          style={{ fontFamily: resolveFontFamily(current?.value) }}
        >
          {current?.label ?? value}
        </span>
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          aria-hidden="true"
          className={cn(
            "ml-2 shrink-0 transition-transform",
            open && "rotate-180",
          )}
        >
          <path
            d="M6 9l6 6 6-6"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>

      {open ? (
        <ul
          role="listbox"
          aria-label={ariaLabel}
          // ``left-0 right-0`` pins menu width to trigger width so they
          // visually match — the spec/screenshot called out the
          // mismatched menu width specifically.
          className="absolute left-0 right-0 z-30 mt-1 max-h-[260px] overflow-y-auto rounded-[10px] border border-grayscale-200 bg-white py-1 shadow-lg"
        >
          {options.map((opt) => {
            const selected = opt.value === value;
            return (
              <li key={opt.value} role="option" aria-selected={selected}>
                <button
                  type="button"
                  onClick={() => {
                    onChange(opt.value);
                    setOpen(false);
                  }}
                  className={cn(
                    "flex w-full items-center justify-between px-[12px] py-[8px] text-left text-[14px] tracking-[-0.35px]",
                    selected
                      ? "bg-grayscale-10 text-heimdex-navy-500"
                      : "text-grayscale-800 hover:bg-grayscale-10",
                  )}
                  style={{ fontFamily: resolveFontFamily(opt.value) }}
                >
                  <span className="truncate">{opt.label}</span>
                  {selected ? (
                    <svg
                      width="14"
                      height="14"
                      viewBox="0 0 24 24"
                      fill="none"
                      aria-hidden="true"
                    >
                      <path
                        d="M5 12l5 5L20 7"
                        stroke="currentColor"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  ) : null}
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
