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
  className?: string;
}

function CTAInner({
  videoId,
  renderWhileProbing = false,
  className,
}: AutoShortsCTAProps) {
  const { availability, isLoading } = useAutoShortsAvailability();

  if (availability === "disabled") return null;
  if (isLoading && !renderWhileProbing) return null;

  return (
    <Link
      href={`/export/shorts/auto?videoId=${encodeURIComponent(videoId)}`}
      className={cn(
        "inline-flex items-center gap-2 rounded-lg border border-indigo-300 bg-indigo-50 px-3 py-2 text-sm font-medium text-indigo-700 transition-colors hover:bg-indigo-100",
        className,
      )}
    >
      <MagicWandIcon className="h-4 w-4" />
      자동으로 쇼츠 만들기
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
