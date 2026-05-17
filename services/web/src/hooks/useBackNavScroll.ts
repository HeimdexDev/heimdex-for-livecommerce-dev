import { useEffect, useLayoutEffect, useRef } from "react";
import { getSnapshot, setScrollY } from "@/lib/back-nav-cache";

/**
 * Save and restore window scroll position keyed by `(namespace, key)`.
 *
 * Listens for scroll events while mounted (throttled) and writes the
 * latest scrollY into the back-nav cache. On mount — once `ready` is
 * true — reads the cached scrollY for the current key and applies it.
 *
 * Decoupled from any specific data hook: anything that wants
 * back-nav scroll restore can call this with its own namespace + key.
 * The caller is responsible for flipping `ready` once content is
 * laid out (otherwise we'd scroll past the end of an empty page).
 */
export function useBackNavScroll(
  namespace: string,
  key: string,
  ready: boolean,
): void {
  const restoredForKey = useRef<string | null>(null);

  useLayoutEffect(() => {
    if (typeof window === "undefined") return;
    if (!ready) return;
    if (restoredForKey.current === key) return;
    const snap = getSnapshot<unknown>(namespace, key);
    if (snap?.scrollY != null && snap.scrollY > 0) {
      window.scrollTo(0, snap.scrollY);
    }
    restoredForKey.current = key;
  }, [namespace, key, ready]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    let rafHandle: number | null = null;
    const onScroll = () => {
      if (rafHandle !== null) return;
      rafHandle = window.requestAnimationFrame(() => {
        rafHandle = null;
        setScrollY(namespace, key, window.scrollY);
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      if (rafHandle !== null) window.cancelAnimationFrame(rafHandle);
      window.removeEventListener("scroll", onScroll);
    };
  }, [namespace, key]);
}
