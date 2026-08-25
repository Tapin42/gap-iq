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
  onRefresh,
  refreshing,
  error,
}: {
  freshness: Freshness;
  onRefresh: () => void;
  refreshing: boolean;
  error?: string | null;
}) {
  const ages = useAges(freshness);
  const broken = freshness.contact_is_stale || freshness.degraded || Boolean(error);

  return (
    <div
      className={`flex items-center justify-between gap-3 px-4 py-2 text-xs ${
        broken ? "bg-bad/25" : "bg-white/5"
      }`}
    >
      <div className="min-w-0">
        {freshness.athlete_last_seen_checkpoint ? (
          <div className="truncate font-semibold">
            {freshness.athlete_last_seen_checkpoint}
            {ages?.athleteAge !== null && ages?.athleteAge !== undefined && (
              <span className="text-ink-muted"> · {formatAge(ages.athleteAge)}</span>
            )}
          </div>
        ) : (
          <div className="text-ink-muted truncate font-semibold">No checkpoint yet</div>
        )}

        <div className="text-ink-muted truncate">
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
        {error && <div className="text-bad truncate">Last refresh failed: {error}</div>}
      </div>

      <button
        type="button"
        onClick={onRefresh}
        disabled={refreshing}
        className="shrink-0 rounded-md bg-white/15 px-3 py-2 font-semibold disabled:opacity-50"
      >
        {refreshing ? "Refreshing…" : "Refresh"}
      </button>
    </div>
  );
}
