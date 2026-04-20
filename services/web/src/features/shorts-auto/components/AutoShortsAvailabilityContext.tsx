"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { useAuth } from "@/lib/auth";
import { probeAutoShortsAvailability } from "@/lib/api/shorts-auto";

type Availability = "unknown" | "available" | "disabled";

interface Ctx {
  availability: Availability;
  isLoading: boolean;
}

const AutoShortsAvailabilityContext = createContext<Ctx>({
  availability: "unknown",
  isLoading: true,
});

/**
 * Probes /api/shorts/auto-select once per session to decide whether to
 * render entry-point CTAs. The probe uses a deliberately invalid body
 * so the backend short-circuits on 422/404 without consuming rate-limit
 * budget. See `probeAutoShortsAvailability` for semantics.
 *
 * Mount this provider near the app root (or on each page that renders
 * an auto-shorts CTA). Multiple providers on the same tree are
 * harmless — each probes once.
 */
export function AutoShortsAvailabilityProvider({ children }: { children: ReactNode }) {
  const { getAccessToken } = useAuth();
  const [availability, setAvailability] = useState<Availability>("unknown");
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    probeAutoShortsAvailability(getAccessToken)
      .then((ok) => {
        if (cancelled) return;
        setAvailability(ok ? "available" : "disabled");
      })
      .catch(() => {
        // Treat probe failure as "available" — don't hide CTAs on
        // transient errors; real requests will surface the issue.
        if (cancelled) return;
        setAvailability("available");
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [getAccessToken]);

  const value = useMemo(() => ({ availability, isLoading }), [availability, isLoading]);

  return (
    <AutoShortsAvailabilityContext.Provider value={value}>
      {children}
    </AutoShortsAvailabilityContext.Provider>
  );
}

export function useAutoShortsAvailability(): Ctx {
  return useContext(AutoShortsAvailabilityContext);
}
