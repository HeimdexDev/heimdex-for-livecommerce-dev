"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { useAuth } from "@/lib/auth";
import { fetchAutoShortsAvailability } from "@/lib/api/shorts-auto";

type Availability = "unknown" | "available" | "disabled";

interface Ctx {
  availability: Availability;
  llmEnabled: boolean;
  isLoading: boolean;
}

const AutoShortsAvailabilityContext = createContext<Ctx>({
  availability: "unknown",
  llmEnabled: false,
  isLoading: true,
});

/**
 * Probes /api/shorts/auto-availability once per session to decide whether
 * to render entry-point CTAs and whether to show the AI-mode toggle.
 *
 * Two flags, one probe:
 *   - `availability` drives CTA visibility (feature master switch)
 *   - `llmEnabled`   drives AI-mode toggle visibility (LLM rollout flag)
 *
 * Treats probe failure as "available, llm off" — don't hide CTAs on
 * transient errors, but don't claim the AI path exists when we can't
 * confirm it. Multiple providers on the same tree are harmless.
 */
export function AutoShortsAvailabilityProvider({ children }: { children: ReactNode }) {
  const { getAccessToken } = useAuth();
  const [availability, setAvailability] = useState<Availability>("unknown");
  const [llmEnabled, setLlmEnabled] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetchAutoShortsAvailability(getAccessToken)
      .then((result) => {
        if (cancelled) return;
        setAvailability(result.enabled ? "available" : "disabled");
        setLlmEnabled(result.llm_enabled);
      })
      .catch(() => {
        if (cancelled) return;
        setAvailability("available");
        setLlmEnabled(false);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [getAccessToken]);

  const value = useMemo(
    () => ({ availability, llmEnabled, isLoading }),
    [availability, llmEnabled, isLoading],
  );

  return (
    <AutoShortsAvailabilityContext.Provider value={value}>
      {children}
    </AutoShortsAvailabilityContext.Provider>
  );
}

export function useAutoShortsAvailability(): Ctx {
  return useContext(AutoShortsAvailabilityContext);
}
