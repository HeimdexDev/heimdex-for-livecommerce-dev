"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export interface TopHeaderBackSlot {
  label: string;
  onClick: () => void;
}

interface TopHeaderActionsContextValue {
  actions: ReactNode | null;
  setActions: (node: ReactNode | null) => void;
  back: TopHeaderBackSlot | null;
  setBack: (slot: TopHeaderBackSlot | null) => void;
}

export const TopHeaderActionsContext =
  createContext<TopHeaderActionsContextValue | null>(null);

interface ProviderProps {
  children: ReactNode;
}

export function TopHeaderActionsProvider({ children }: ProviderProps) {
  const [actions, setActionsState] = useState<ReactNode | null>(null);
  const [back, setBackState] = useState<TopHeaderBackSlot | null>(null);

  const setActions = useCallback((node: ReactNode | null) => {
    setActionsState(node);
  }, []);

  const setBack = useCallback((slot: TopHeaderBackSlot | null) => {
    setBackState(slot);
  }, []);

  const value = useMemo(
    () => ({ actions, setActions, back, setBack }),
    [actions, setActions, back, setBack],
  );

  return (
    <TopHeaderActionsContext.Provider value={value}>
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

// Mounts a back-button slot (label + onClick) into the TopHeader's leftmost
// area. Cleared on unmount.
export function useTopHeaderBack(slot: TopHeaderBackSlot | null): void {
  const ctx = useContext(TopHeaderActionsContext);

  useEffect(() => {
    if (!ctx) return;
    ctx.setBack(slot);
    return () => {
      ctx.setBack(null);
    };
  }, [ctx, slot]);
}
