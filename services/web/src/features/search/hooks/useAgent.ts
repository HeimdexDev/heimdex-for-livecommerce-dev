"use client";

import { useState, useEffect, useCallback } from "react";
import { checkAgentHealth, AgentHealth } from "@/lib/agent";

export function useAgent(pollIntervalMs = 30_000) {
  const [isAvailable, setIsAvailable] = useState(false);
  const [health, setHealth] = useState<AgentHealth | null>(null);
  const [isChecking, setIsChecking] = useState(true);

  const check = useCallback(async () => {
    setIsChecking(true);
    const result = await checkAgentHealth();
    setHealth(result);
    setIsAvailable(result !== null);
    setIsChecking(false);
  }, []);

  useEffect(() => {
    check();
    const interval = setInterval(check, pollIntervalMs);
    return () => clearInterval(interval);
  }, [check, pollIntervalMs]);

  return { isAvailable, health, isChecking, recheck: check };
}
