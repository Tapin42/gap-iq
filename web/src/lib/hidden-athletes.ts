import { useCallback, useState } from "react";

const STORAGE_PREFIX = "gap-iq:hidden-athletes:";

function storageKey(edition: string): string {
  return `${STORAGE_PREFIX}${edition}`;
}

export function loadHiddenSlugs(edition: string): Set<string> {
  try {
    const raw = localStorage.getItem(storageKey(edition));
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((item): item is string => typeof item === "string"));
  } catch {
    return new Set();
  }
}

export function saveHiddenSlugs(edition: string, slugs: Set<string>): void {
  try {
    localStorage.setItem(storageKey(edition), JSON.stringify([...slugs]));
  } catch {
    // Private browsing or quota exceeded — in-memory state still works this session.
  }
}

export function useHiddenAthletes(edition: string | undefined): {
  hiddenSlugs: Set<string>;
  hide: (slug: string) => void;
  unhide: (slug: string) => void;
  isHidden: (slug: string) => boolean;
} {
  const editionKey = edition ?? "";
  const [store, setStore] = useState(() => ({
    editionKey,
    slugs: edition ? loadHiddenSlugs(edition) : new Set<string>(),
  }));

  if (store.editionKey !== editionKey) {
    setStore({
      editionKey,
      slugs: edition ? loadHiddenSlugs(edition) : new Set(),
    });
  }

  const hiddenSlugs = store.slugs;

  const hide = useCallback(
    (slug: string) => {
      if (!edition) return;
      setStore((prev) => {
        const next = new Set(prev.slugs);
        next.add(slug);
        saveHiddenSlugs(edition, next);
        return { editionKey: prev.editionKey, slugs: next };
      });
    },
    [edition],
  );

  const unhide = useCallback(
    (slug: string) => {
      if (!edition) return;
      setStore((prev) => {
        const next = new Set(prev.slugs);
        next.delete(slug);
        saveHiddenSlugs(edition, next);
        return { editionKey: prev.editionKey, slugs: next };
      });
    },
    [edition],
  );

  const isHidden = useCallback((slug: string) => hiddenSlugs.has(slug), [hiddenSlugs]);

  return { hiddenSlugs, hide, unhide, isHidden };
}
