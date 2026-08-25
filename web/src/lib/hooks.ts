import { useCallback, useEffect, useRef, useState } from "react";

import type { Freshness } from "./api";

/**
 * Poll only while the page is actually being looked at.
 *
 * Plain polling gated on visibility beats a push connection here. The underlying data
 * changes on the order of ten minutes -- timing mats are minutes to tens of minutes apart --
 * so a stream buys almost no latency while adding failure modes that matter on a phone at
 * a race: proxy idle timeouts, carriers that buffer an event stream into something
 * connected but frozen, and iOS suspending the page on screen lock. A fetch that either
 * returns or visibly fails is far easier to reason about, and refetching on wake is exactly
 * the behaviour we want.
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
): {
  data: T | null;
  error: string | null;
  loading: boolean;
  refresh: () => Promise<void>;
  refreshing: boolean;
} {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const load = useCallback(async (manual: boolean) => {
    if (manual) setRefreshing(true);
    try {
      const next = await fetcherRef.current();
      setData(next);
      setError(null);
    } catch (cause) {
      // Keep the last good payload on screen rather than blanking it. Stale data that is
      // labelled stale is more useful than nothing; the freshness line does the honesty.
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setLoading(false);
      if (manual) setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    let timer: number | undefined;

    const tick = () => {
      if (document.visibilityState === "visible") void load(false);
      timer = window.setTimeout(tick, intervalMs);
    };

    void load(false);
    timer = window.setTimeout(tick, intervalMs);

    // Fetch immediately on wake, so a phone coming out of a pocket is never showing a
    // value from before it was locked.
    const onVisible = () => {
      if (document.visibilityState === "visible") void load(false);
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      if (timer) window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [load, intervalMs]);

  return { data, error, loading, refresh: () => load(true), refreshing };
}

/** Re-render on a timer so relative ages tick up without a network request. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now() / 1000), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs]);
  return now;
}

/**
 * Ages are computed here, not on the server.
 *
 * The server sends absolute epochs precisely so this can happen client-side: a
 * server-rendered "12s ago" freezes at serialisation time, and a tab that sleeps for an
 * hour would keep displaying it, which is the single most misleading thing this app could
 * do. `skewSeconds` corrects for a client clock that disagrees with the server's.
 */
export function useAges(freshness: Freshness | undefined) {
  const now = useNow(1000);
  if (!freshness) return null;

  const skewSeconds = now - freshness.server_time;
  const age = (at: number | null | undefined) =>
    at === null || at === undefined ? null : Math.max(0, now - at - skewSeconds);

  return {
    contactAge: age(freshness.last_upstream_contact_at),
    changeAge: age(freshness.last_data_change_at),
    athleteAge: age(freshness.athlete_last_seen_at),
  };
}

export function formatAge(seconds: number | null): string {
  if (seconds === null) return "never";
  if (seconds < 45) return `${Math.round(seconds)}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m ago`;
}
