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
  leftActions: ReactNode | null;
  setLeftActions: (node: ReactNode | null) => void;
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
  const [leftActions, setLeftActionsState] = useState<ReactNode | null>(null);
  const [back, setBackState] = useState<TopHeaderBackSlot | null>(null);

  const setActions = useCallback((node: ReactNode | null) => {
    setActionsState(node);
  }, []);

  const setLeftActions = useCallback((node: ReactNode | null) => {
    setLeftActionsState(node);
  }, []);

  const setBack = useCallback((slot: TopHeaderBackSlot | null) => {
    setBackState(slot);
  }, []);

  const value = useMemo(
    () => ({ actions, setActions, leftActions, setLeftActions, back, setBack }),
    [actions, setActions, leftActions, setLeftActions, back, setBack],
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

// Mounts `node` next to the back slot on the TopHeader's left side, used by
// editor-style routes that need title/metadata alongside the back button.
// Cleared on unmount.
export function useTopHeaderLeftActions(node: ReactNode | null): void {
  const ctx = useContext(TopHeaderActionsContext);

  useEffect(() => {
    if (!ctx) return;
    ctx.setLeftActions(node);
    return () => {
      ctx.setLeftActions(null);
    };
  }, [ctx, node]);
}
