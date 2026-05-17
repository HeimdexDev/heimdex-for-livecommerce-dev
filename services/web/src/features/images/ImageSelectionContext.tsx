"use client";

import { createContext, useContext, type ReactNode } from "react";
import { useImageSelection, type ImageSelectionState } from "./useImageSelection";

const ImageSelectionContext = createContext<ImageSelectionState | null>(null);

export function ImageSelectionProvider({ children }: { children: ReactNode }) {
  const selection = useImageSelection();
  return (
    <ImageSelectionContext.Provider value={selection}>
      {children}
    </ImageSelectionContext.Provider>
  );
}

export function useImageSelectionContext(): ImageSelectionState | null {
  return useContext(ImageSelectionContext);
}
