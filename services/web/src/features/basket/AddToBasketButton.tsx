"use client";

import { cn } from "@/lib/utils";
import { SceneResult } from "@/lib/types/search";
import { useSceneBasket } from "./useSceneBasket";

interface AddToBasketButtonProps {
  scene: SceneResult;
}

export function AddToBasketButton({ scene }: AddToBasketButtonProps) {
  const { addItem, removeItem, isInBasket } = useSceneBasket();

  if (scene.content_type === "image") return null;

  const inBasket = isInBasket(scene.scene_id);

  const handleToggle = () => {
    if (inBasket) {
      removeItem(scene.scene_id);
      return;
    }

    addItem({
      scene_id: scene.scene_id,
      video_id: scene.video_id,
      video_title: scene.video_title ?? "",
      start_ms: scene.start_ms,
      end_ms: scene.end_ms,
    });
  };

  return (
    <button
      type="button"
      onClick={handleToggle}
      className={cn(
        "text-sm flex items-center gap-1 px-2 py-1 rounded-md border",
        inBasket
          ? "text-primary-600 bg-primary-50 border-primary-200"
          : "text-gray-500 hover:bg-gray-50 border-gray-200"
      )}
    >
      {inBasket ? (
        <>
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
          담김
        </>
      ) : (
        <>
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          담기
        </>
      )}
    </button>
  );
}
