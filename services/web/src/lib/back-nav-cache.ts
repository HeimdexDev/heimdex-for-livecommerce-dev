/**
 * In-memory back-navigation snapshot store.
 *
 * Holds at most one snapshot per namespace, keyed by an opaque string
 * (typically a serialised set of filter inputs). When the key for a
 * namespace changes, the previous snapshot is dropped — a stale filter
 * combo never overwrites the current one's reads.
 *
 * Module-scoped on purpose: hard refresh / new tab should start fresh,
 * but back-nav within the SPA should preserve. sessionStorage would add
 * JSON cost + a 5MB ceiling that the browse list (hundreds of cards)
 * can blow past.
 */

interface Snapshot {
  key: string;
  data?: unknown;
  scrollY?: number;
  savedAt: number;
}

const snapshots = new Map<string, Snapshot>();

export function getSnapshot<T>(
  namespace: string,
  key: string,
): { data?: T; scrollY?: number } | null {
  const snap = snapshots.get(namespace);
  if (!snap || snap.key !== key) return null;
  return { data: snap.data as T | undefined, scrollY: snap.scrollY };
}

export function setData<T>(namespace: string, key: string, data: T): void {
  const existing = snapshots.get(namespace);
  if (existing && existing.key === key) {
    existing.data = data;
    existing.savedAt = Date.now();
    return;
  }
  snapshots.set(namespace, { key, data, savedAt: Date.now() });
}

export function setScrollY(namespace: string, key: string, scrollY: number): void {
  const existing = snapshots.get(namespace);
  if (existing && existing.key === key) {
    existing.scrollY = scrollY;
    existing.savedAt = Date.now();
    return;
  }
  snapshots.set(namespace, { key, scrollY, savedAt: Date.now() });
}

export function clearNamespace(namespace: string): void {
  snapshots.delete(namespace);
}

/** Test-only: drop everything. */
export function _resetAllSnapshots(): void {
  snapshots.clear();
}
