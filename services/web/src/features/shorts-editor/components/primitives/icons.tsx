/**
 * SVG icons for the V2 panel toolbars.
 *
 * Hand-rolled to avoid pulling in a full icon library for ~10 icons.
 * All have stroke-based geometry so they inherit `currentColor`.
 */

const ICON_PROPS = {
  className: "h-4 w-4",
  fill: "none",
  viewBox: "0 0 24 24",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export function PlusIcon({ className }: { className?: string }) {
  return (
    <svg {...ICON_PROPS} className={className ?? ICON_PROPS.className}>
      <path d="M12 5v14m-7-7h14" />
    </svg>
  );
}

export function TrashIcon({ className }: { className?: string }) {
  return (
    <svg {...ICON_PROPS} className={className ?? ICON_PROPS.className}>
      <path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6h14z" />
    </svg>
  );
}

export function BoldIcon({ className }: { className?: string }) {
  return (
    <svg {...ICON_PROPS} className={className ?? ICON_PROPS.className}>
      <path d="M7 4h6a4 4 0 010 8H7zM7 12h7a4 4 0 010 8H7z" />
    </svg>
  );
}

export function ItalicIcon({ className }: { className?: string }) {
  return (
    <svg {...ICON_PROPS} className={className ?? ICON_PROPS.className}>
      <path d="M19 4h-9M14 20H5M15 4L9 20" />
    </svg>
  );
}

export function UnderlineIcon({ className }: { className?: string }) {
  return (
    <svg {...ICON_PROPS} className={className ?? ICON_PROPS.className}>
      <path d="M6 4v8a6 6 0 0012 0V4M5 20h14" />
    </svg>
  );
}

export function AlignLeftIcon({ className }: { className?: string }) {
  return (
    <svg {...ICON_PROPS} className={className ?? ICON_PROPS.className}>
      <path d="M3 6h18M3 12h12M3 18h18" />
    </svg>
  );
}

export function AlignCenterIcon({ className }: { className?: string }) {
  return (
    <svg {...ICON_PROPS} className={className ?? ICON_PROPS.className}>
      <path d="M3 6h18M6 12h12M3 18h18" />
    </svg>
  );
}

export function AlignRightIcon({ className }: { className?: string }) {
  return (
    <svg {...ICON_PROPS} className={className ?? ICON_PROPS.className}>
      <path d="M3 6h18M9 12h12M3 18h18" />
    </svg>
  );
}

export function LineSpacingIcon({ className }: { className?: string }) {
  return (
    <svg {...ICON_PROPS} className={className ?? ICON_PROPS.className}>
      <path d="M5 4l-2 2m2-2l2 2m-2-2v16m0 0l-2-2m2 2l2-2M11 6h10M11 12h10M11 18h10" />
    </svg>
  );
}

export function LayerStackIcon({ className }: { className?: string }) {
  return (
    <svg {...ICON_PROPS} className={className ?? ICON_PROPS.className}>
      <path d="M12 2L2 7l10 5 10-5-10-5z" />
      <path d="M2 17l10 5 10-5M2 12l10 5 10-5" />
    </svg>
  );
}

export function PaintBucketIcon({ className }: { className?: string }) {
  // figma 1602:40067 — lucide/paint-bucket. The earlier path was actually
  // lucide/eraser (the diagonal-stroke shape staging users saw). Swapped
  // for the canonical paint-bucket: tilted body + dripping paint drop.
  return (
    <svg {...ICON_PROPS} className={className ?? ICON_PROPS.className}>
      <path d="m19 11-8-8-8.6 8.6a2 2 0 0 0 0 2.8l5.2 5.2c.8.8 2 .8 2.8 0L19 11Z" />
      <path d="m5 2 5 5" />
      <path d="M2 13h15" />
      <path d="M22 20a2 2 0 1 1-4 0c0-1.6 1.7-2.4 2-4 .3 1.6 2 2.4 2 4Z" />
    </svg>
  );
}

// Canvas-level alignment trigger — centers the overlay vertically (default)
// or horizontally (when `rotated` is true). The default shape is a
// horizontal bar between two stacked boxes; `rotated` applies a -90deg
// transform so the same path doubles as the horizontal-center icon. The
// adjacent chevron-down (in TextToolbar) toggles `rotated`, mirroring the
// text-align cycle UX.
export function CanvasAlignCenterIcon({
  className,
  rotated = false,
}: { className?: string; rotated?: boolean }) {
  return (
    <svg
      {...ICON_PROPS}
      className={className ?? ICON_PROPS.className}
      style={rotated ? { transform: "rotate(-90deg)" } : undefined}
    >
      <rect x="6" y="3.5" width="12" height="6" rx="1" />
      <line x1="3" y1="12" x2="21" y2="12" />
      <rect x="6" y="14.5" width="12" height="6" rx="1" />
    </svg>
  );
}

export function ImageIcon({ className }: { className?: string }) {
  return (
    <svg {...ICON_PROPS} className={className ?? ICON_PROPS.className}>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <circle cx="9" cy="9" r="2" />
      <path d="M21 15l-5-5L5 21" />
    </svg>
  );
}

export function ChevronDownIcon({ className }: { className?: string }) {
  return (
    <svg {...ICON_PROPS} className={className ?? "h-3 w-3"}>
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}
