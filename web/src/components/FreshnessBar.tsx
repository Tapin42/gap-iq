import type { Freshness } from "../lib/api";
import { formatAge, useAges } from "../lib/hooks";

/**
 * How current the data is -- stated as checkpoint age first, fetch age second.
 *
 * On the Zofingen bike leg consecutive mats are 35-53 minutes apart, so no polling interval
 * can make a displayed gap younger than the last mat an athlete crossed. Leading with
 * "updated 12s ago" would therefore be true about the fetch and deeply misleading about the
 * race, which is why the checkpoint is the headline and the fetch is the footnote.
 */
export function FreshnessBar({
  freshness,
  headline,
  onRefresh,
  refreshing,
  error,
}: {
  freshness: Freshness;
  /** Roster uses event phase; athlete dashboard uses per-athlete checkpoint from freshness. */
  headline?: string;
  onRefresh: () => void;
  refreshing: boolean;
  error?: string | null;
}) {
  const ages = useAges(freshness);
  const broken = freshness.contact_is_stale || freshness.degraded || Boolean(error);

  return (
    <div
      className={`flex items-center justify-between gap-3 px-4 py-3 text-sm ${
        broken ? "bg-bad/30" : "bg-white/10"
      }`}
    >
      <div className="min-w-0">
        {/* Deliberately the most legible line here. If a supporter cannot read how old the
            data is at a glance, the honesty this bar exists for is wasted. */}
        {headline ? (
          <div className="truncate text-base font-bold">{headline}</div>
        ) : freshness.athlete_last_seen_checkpoint ? (
          <div className="truncate text-base font-bold">
            {freshness.athlete_last_seen_checkpoint}
            {ages?.athleteAge !== null && ages?.athleteAge !== undefined && (
              <span className="font-semibold"> · {formatAge(ages.athleteAge)}</span>
            )}
          </div>
        ) : (
          <div className="truncate text-base font-bold">No checkpoint yet</div>
        )}

        <div className="truncate text-ink-muted">
          {!freshness.polling.allowed ? (
            // Idle by design is not the same as broken, and must not look like it.
            <>Idle — {freshness.polling.reason}</>
          ) : freshness.degraded ? (
            <>Upstream unavailable — {freshness.degraded_reason || "retrying is paused"}</>
          ) : freshness.contact_is_stale ? (
            <>Server hasn't reached the timing feed — last contact {formatAge(ages?.contactAge ?? null)}</>
          ) : (
            <>
              Checked {formatAge(ages?.contactAge ?? null)}
              {freshness.next_expected_checkpoint && <> · next: {freshness.next_expected_checkpoint}</>}
            </>
          )}
        </div>
        {error && <div className="text-bad truncate font-semibold">Last refresh failed: {error}</div>}
      </div>

      <button
        type="button"
        onClick={onRefresh}
        disabled={refreshing}
        className="min-h-[44px] shrink-0 rounded-md bg-white/20 px-4 py-2 font-semibold disabled:opacity-50"
      >
        {refreshing ? "Refreshing…" : "Refresh"}
      </button>
    </div>
  );
}
