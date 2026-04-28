"use client";

import { cn } from "@/lib/utils";

interface DropdownOption<T extends string | number> {
  value: T;
  label: string;
}

interface DropdownProps<T extends string | number> {
  value: T;
  options: ReadonlyArray<DropdownOption<T>>;
  onChange: (next: T) => void;
  disabled?: boolean;
  ariaLabel?: string;
  className?: string;
}

/**
 * Native `<select>` styled to match the design system. Uses generic value
 * type so callers get type-narrowed onChange — TextAlign, FontFamily, etc.
 *
 * No fancy animation / portal / virtualized list — the redesigns' three
 * dropdowns (font family, alignment, line-spacing) are tiny lists where
 * native is fine and a11y comes free.
 */
export function Dropdown<T extends string | number>({
  value,
  options,
  onChange,
  disabled = false,
  ariaLabel,
  className,
}: DropdownProps<T>) {
  return (
    <select
      value={String(value)}
      onChange={(e) => {
        const raw = e.target.value;
        // Match the original option's type — numeric options stay numeric.
        const opt = options.find((o) => String(o.value) === raw);
        if (opt) onChange(opt.value);
      }}
      disabled={disabled}
      aria-label={ariaLabel}
      className={cn(
        "rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:cursor-not-allowed disabled:bg-gray-50",
        className,
      )}
    >
      {options.map((o) => (
        <option key={String(o.value)} value={String(o.value)}>
          {o.label}
        </option>
      ))}
    </select>
  );
}
