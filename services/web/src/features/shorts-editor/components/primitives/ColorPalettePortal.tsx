"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

interface Props {
  anchorRef: React.RefObject<HTMLElement>;
  onClose: () => void;
  children: React.ReactNode;
  // "anchored" pins the popover to the trigger's right edge (legacy).
  // "centered" centers the popover inside the editor right wrapper —
  // preferred for the 2026-05-18 redesign so the palette opens in the
  // middle of the right wrapper regardless of which control was clicked.
  mode?: "anchored" | "centered";
}

const POPOVER_WIDTH = 260;
const POPOVER_MAX_HEIGHT = 640;
const GAP = 8;
const VIEWPORT_MARGIN = 8;

interface Pos {
  top: number;
  left: number;
}

/**
 * Portal wrapper for the color palette popover.
 *
 * Two positioning modes:
 *   anchored — pin right edge to the trigger's right edge (drop below /
 *     flip above when there isn't room). Used by callers that still want
 *     the popover visually attached to its trigger.
 *   centered — center the popover inside the editor right wrapper
 *     (``[data-editor-right-panel]``). Falls back to viewport-center when
 *     the wrapper isn't found.
 *
 * Either way the popover is portalled to document.body so the
 * surrounding ``overflow-y-auto`` scroll surfaces can't clip it.
 */
export function ColorPalettePortal({
  anchorRef,
  onClose,
  children,
  mode = "centered",
}: Props) {
  const popoverRef = useRef<HTMLDivElement>(null);
  const [mounted, setMounted] = useState(false);
  const [pos, setPos] = useState<Pos>({ top: -9999, left: -9999 });

  useEffect(() => {
    setMounted(true);
  }, []);

  const recompute = () => {
    const viewportH = window.innerHeight;
    const viewportW = window.innerWidth;
    const popoverH = popoverRef.current?.offsetHeight ?? POPOVER_MAX_HEIGHT;

    let top: number;
    let left: number;

    if (mode === "centered") {
      // Center on the editor right wrapper if we can find it; otherwise
      // fall back to viewport center. Using the wrapper rect keeps the
      // palette visually associated with the panel that owns it.
      const wrapper = document.querySelector<HTMLElement>(
        "[data-editor-right-panel]",
      );
      const rect = wrapper?.getBoundingClientRect();
      if (rect && rect.width > 0) {
        left = rect.left + rect.width / 2 - POPOVER_WIDTH / 2;
        top = rect.top + rect.height / 2 - popoverH / 2;
      } else {
        left = viewportW / 2 - POPOVER_WIDTH / 2;
        top = viewportH / 2 - popoverH / 2;
      }
    } else {
      const anchor = anchorRef.current;
      if (!anchor) return;
      const r = anchor.getBoundingClientRect();
      top = r.bottom + GAP;
      left = r.right - POPOVER_WIDTH;
      const spaceBelow = viewportH - r.bottom - GAP;
      const spaceAbove = r.top - GAP;
      if (spaceBelow < popoverH && spaceAbove > spaceBelow) {
        top = r.top - popoverH - GAP;
      }
    }

    if (left < VIEWPORT_MARGIN) left = VIEWPORT_MARGIN;
    if (left + POPOVER_WIDTH > viewportW - VIEWPORT_MARGIN) {
      left = viewportW - POPOVER_WIDTH - VIEWPORT_MARGIN;
    }
    if (top < VIEWPORT_MARGIN) top = VIEWPORT_MARGIN;
    if (top + popoverH > viewportH - VIEWPORT_MARGIN) {
      top = Math.max(VIEWPORT_MARGIN, viewportH - popoverH - VIEWPORT_MARGIN);
    }

    setPos({ top, left });
  };

  useLayoutEffect(() => {
    recompute();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mounted]);

  useEffect(() => {
    const onChange = () => recompute();
    window.addEventListener("resize", onChange);
    window.addEventListener("scroll", onChange, true);
    return () => {
      window.removeEventListener("resize", onChange);
      window.removeEventListener("scroll", onChange, true);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    function handle(e: MouseEvent) {
      const target = e.target as Node;
      if (popoverRef.current && popoverRef.current.contains(target)) return;
      if (anchorRef.current && anchorRef.current.contains(target)) return;
      onClose();
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [anchorRef, onClose]);

  if (!mounted) return null;

  return createPortal(
    <div
      ref={popoverRef}
      style={{ position: "fixed", top: pos.top, left: pos.left, zIndex: 50 }}
    >
      {children}
    </div>,
    document.body,
  );
}
