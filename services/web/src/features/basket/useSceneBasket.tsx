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

const STORAGE_KEY = "heimdex_basket";

export interface BasketItem {
  scene_id: string;
  video_id: string;
  video_title: string;
  start_ms: number;
  end_ms: number;
  label?: string;
  thumbnail_url?: string;
  keyword_tags?: string[];
  transcript_raw?: string;
}

interface SceneBasketContextValue {
  items: BasketItem[];
  addItem: (item: BasketItem) => void;
  removeItem: (sceneId: string) => void;
  reorderItems: (fromIndex: number, toIndex: number) => void;
  clearBasket: () => void;
  isInBasket: (sceneId: string) => boolean;
  totalDurationMs: number;
  itemCount: number;
}

const SceneBasketContext = createContext<SceneBasketContextValue | null>(null);

export function SceneBasketProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<BasketItem[]>([]);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as BasketItem[];
        if (Array.isArray(parsed)) {
          setItems(parsed);
        }
      }
    } catch {
      setItems([]);
    } finally {
      setHydrated(true);
    }
  }, []);

  useEffect(() => {
    if (!hydrated) {
      return;
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
  }, [items, hydrated]);

  const addItem = useCallback((item: BasketItem) => {
    setItems((prev) => {
      if (prev.some((existing) => existing.scene_id === item.scene_id)) {
        return prev;
      }
      return [...prev, item];
    });
  }, []);

  const removeItem = useCallback((sceneId: string) => {
    setItems((prev) => prev.filter((item) => item.scene_id !== sceneId));
  }, []);

  const reorderItems = useCallback((fromIndex: number, toIndex: number) => {
    setItems((prev) => {
      if (
        fromIndex < 0 ||
        toIndex < 0 ||
        fromIndex >= prev.length ||
        toIndex >= prev.length ||
        fromIndex === toIndex
      ) {
        return prev;
      }

      const next = [...prev];
      const [moved] = next.splice(fromIndex, 1);
      next.splice(toIndex, 0, moved);
      return next;
    });
  }, []);

  const clearBasket = useCallback(() => {
    setItems([]);
  }, []);

  const isInBasket = useCallback(
    (sceneId: string) => items.some((item) => item.scene_id === sceneId),
    [items]
  );

  const totalDurationMs = useMemo(
    () => items.reduce((sum, item) => sum + Math.max(0, item.end_ms - item.start_ms), 0),
    [items]
  );

  const value = useMemo<SceneBasketContextValue>(
    () => ({
      items,
      addItem,
      removeItem,
      reorderItems,
      clearBasket,
      isInBasket,
      totalDurationMs,
      itemCount: items.length,
    }),
    [items, addItem, removeItem, reorderItems, clearBasket, isInBasket, totalDurationMs]
  );

  return <SceneBasketContext.Provider value={value}>{children}</SceneBasketContext.Provider>;
}

export function useSceneBasket(): SceneBasketContextValue {
  const context = useContext(SceneBasketContext);
  if (!context) {
    throw new Error("useSceneBasket must be used within a SceneBasketProvider");
  }
  return context;
}
