"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";

import { MagicWandIcon } from "./icons";
import {
  AutoShortsAvailabilityProvider,
  useAutoShortsAvailability,
} from "./AutoShortsAvailabilityContext";

interface AutoShortsCTAProps {
  videoId: string;
  /**
   * When true, the CTA renders even while the availability probe is
   * still loading. Useful on pages where we prefer to show the button
   * immediately and let the auto-shorts page handle the disabled case.
   * Default: false (hidden until probe succeeds).
   */
  renderWhileProbing?: boolean;
  /**
   * When set, the CTA renders as a button that fires this callback
   * instead of navigating. The video detail page uses this to switch
   * the inline view-mode to ``auto-shorts`` (URL becomes
   * ``?view=auto-shorts``) so the wizard renders next to the player
   * rather than on a standalone route. When unset, falls back to the
   * legacy /export/shorts/auto/wizard/{videoId}/criteria deep link.
   */
  onClick?: () => void;
  className?: string;
}

function CTAInner({
  videoId,
  renderWhileProbing = false,
  onClick,
  className,
}: AutoShortsCTAProps) {
  const { availability, isLoading } = useAutoShortsAvailability();

  if (availability === "disabled") return null;
  if (isLoading && !renderWhileProbing) return null;

  const sharedClassName = cn(
    "inline-flex items-center gap-2 rounded-lg border border-indigo-300 bg-indigo-50 px-3 py-2 text-sm font-medium text-indigo-700 transition-colors hover:bg-indigo-100",
    className,
  );

  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={sharedClassName}>
        <MagicWandIcon className="h-4 w-4" />
        AI 쇼츠 생성
      </button>
    );
  }

  // Legacy fallback: deep link to the standalone wizard route. Kept
  // for direct callers that don't supply onClick. The video detail
  // page provides onClick so users land on the inline experience.
  return (
    <Link
      href={`/export/shorts/auto/wizard/${encodeURIComponent(videoId)}/criteria`}
      className={sharedClassName}
    >
      <MagicWandIcon className="h-4 w-4" />
      AI 쇼츠 생성
    </Link>
  );
}

/**
 * Self-contained CTA. Safe to drop into any page — includes its own
 * availability provider so callers don't have to wrap the route.
 * Internally the provider is idempotent; nesting doesn't cause extra
 * probes (each instance probes once).
 */
export function AutoShortsCTA(props: AutoShortsCTAProps) {
  return (
    <AutoShortsAvailabilityProvider>
      <CTAInner {...props} />
    </AutoShortsAvailabilityProvider>
  );
}
