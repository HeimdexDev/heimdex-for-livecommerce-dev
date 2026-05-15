"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

interface TopHeaderActionsContextValue {
  actions: ReactNode | null;
  setActions: (node: ReactNode | null) => void;
}

export const TopHeaderActionsContext =
  createContext<TopHeaderActionsContextValue | null>(null);

interface ProviderProps {
  children: ReactNode;
}

export function TopHeaderActionsProvider({ children }: ProviderProps) {
  const [actions, setActionsState] = useState<ReactNode | null>(null);

  const setActions = useCallback((node: ReactNode | null) => {
    setActionsState(node);
  }, []);

  return (
    <TopHeaderActionsContext.Provider value={{ actions, setActions }}>
      {children}
    </TopHeaderActionsContext.Provider>
  );
}

// Mounts `node` into the TopHeader's actions slot for the lifetime of the
// caller component. Cleared on unmount so route-specific menus don't leak
// into other pages.
export function useTopHeaderActions(node: ReactNode | null): void {
  const ctx = useContext(TopHeaderActionsContext);

  useEffect(() => {
    if (!ctx) return;
    ctx.setActions(node);
    return () => {
      ctx.setActions(null);
    };
  }, [ctx, node]);
}
