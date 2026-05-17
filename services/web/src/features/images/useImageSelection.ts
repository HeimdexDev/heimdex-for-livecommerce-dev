"use client";

import { useState, useCallback, useMemo } from "react";

const MAX_SELECTION = 50;

export interface SelectedImage {
  sceneId: string;
  videoId: string;
  videoTitle: string | null;
}

export interface ImageSelectionState {
  selected: Map<string, SelectedImage>;
  toggle: (image: SelectedImage) => void;
  clear: () => void;
  isSelected: (sceneId: string) => boolean;
  count: number;
  canSelect: boolean;
  selectedItems: SelectedImage[];
}

export function useImageSelection(): ImageSelectionState {
  const [selected, setSelected] = useState<Map<string, SelectedImage>>(
    () => new Map()
  );

  const toggle = useCallback((image: SelectedImage) => {
    setSelected((prev) => {
      const next = new Map(prev);
      if (next.has(image.sceneId)) {
        next.delete(image.sceneId);
      } else if (next.size < MAX_SELECTION) {
        next.set(image.sceneId, image);
      }
      return next;
    });
  }, []);

  const clear = useCallback(() => {
    setSelected(new Map());
  }, []);

  const isSelected = useCallback(
    (sceneId: string) => selected.has(sceneId),
    [selected]
  );

  const count = selected.size;
  const canSelect = count < MAX_SELECTION;
  const selectedItems = useMemo(() => Array.from(selected.values()), [selected]);

  return { selected, toggle, clear, isSelected, count, canSelect, selectedItems };
}
