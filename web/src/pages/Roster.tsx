import { useCallback, useState } from "react";
import { Link } from "react-router-dom";

import { FreshnessBar } from "../components/FreshnessBar";
import { api, type RosterResponse, type RosterRow } from "../lib/api";
import { usePolling } from "../lib/hooks";

// Slower than the dashboard: the roster is a scanning view, and the whole list comes from
// one upstream request per sweep anyway.
const POLL_MS = 60_000;

export function Roster() {
  const { data, error, loading, refresh, refreshing } = usePolling<RosterResponse>(
    api.roster,
    POLL_MS,
  );
  const [busy, setBusy] = useState<string | null>(null);

  const onRefresh = useCallback(async () => {
    await api.refresh().catch(() => undefined);
    await refresh();
  }, [refresh]);

  const toggleScope = useCallback(
    async (row: RosterRow) => {
      setBusy(row.athlete_slug);
      try {
        await api.setScope(row.athlete_slug, row.scope === "agegroup" ? "overall" : "agegroup");
        await refresh();
      } finally {
        setBusy(null);
      }
    },
    [refresh],
  );

  const remove = useCallback(
    async (row: RosterRow) => {
      setBusy(row.athlete_slug);
      try {
        await api.remove(row.athlete_slug);
        await refresh();
      } finally {
        setBusy(null);
      }
    },
    [refresh],
  );

  if (loading && !data) {
    return (
      <div className="flex min-h-full items-center justify-center">
        <p className="text-ink-muted">Loading roster…</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex min-h-full flex-col items-center justify-center px-8 text-center">
        <p className="text-bad text-lg font-semibold">Couldn't load the roster.</p>
        <p className="text-ink-muted mt-2">{error}</p>
        <button
          type="button"
          onClick={onRefresh}
          className="mt-4 rounded-md bg-white/15 px-4 py-2 font-semibold"
        >
          Try again
        </button>
      </div>
    );
  }

  return (
    <div className="flex min-h-full flex-col">
      <header className="px-4 pt-4 pb-2">
        <h1 className="text-2xl font-black tracking-tight">Gap IQ</h1>
        <p className="text-ink-muted text-sm">
          {data.athletes.length} tracked · tap an athlete for their gaps
        </p>
      </header>

      <FreshnessBar
        freshness={data.freshness}
        onRefresh={onRefresh}
        refreshing={refreshing}
        error={error}
      />

      {data.athletes.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center px-8 text-center">
          <p className="text-lg font-semibold">Nobody on the roster</p>
          <p className="text-ink-muted mt-2 text-balance">
            Add an athlete to start tracking their position and gaps.
          </p>
        </div>
      ) : (
        <ul className="divide-y divide-white/10">
          {data.athletes.map((row) => (
            <li key={row.athlete_slug} className="px-4 py-3">
              <div className="flex items-start gap-3">
                <Link to={`/athlete/${row.athlete_slug}`} className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2">
                    <span className="text-2xl font-black tabular-nums">
                      {row.position ?? "—"}
                    </span>
                    <span className="truncate text-lg font-bold">
                      {row.last_name || row.name}
                    </span>
                    {row.bib && (
                      <span className="text-ink-muted shrink-0 text-sm tabular-nums">
                        #{row.bib}
                      </span>
                    )}
                  </div>
                  <div className="text-ink-muted truncate text-sm">
                    {row.checkpoint ? (
                      <>
                        {row.checkpoint}
                        {row.elapsed_text && <> · {row.elapsed_text}</>}
                      </>
                    ) : (
                      <>{row.progress || statusCopy(row.status)}</>
                    )}
                  </div>
                  <div className="mt-1 flex gap-4 text-sm font-semibold">
                    <NeighbourChip slot="ahead" row={row} />
                    <NeighbourChip slot="behind" row={row} />
                  </div>
                </Link>

                <div className="flex shrink-0 flex-col items-end gap-1">
                  <button
                    type="button"
                    onClick={() => toggleScope(row)}
                    disabled={row.scope_locked || busy === row.athlete_slug}
                    title={
                      row.scope_locked
                        ? "Elite has no age groups, so there is nothing to switch"
                        : "Switch between age-group and overall position"
                    }
                    className="min-h-[40px] min-w-[92px] rounded-md bg-white/20 px-3 py-2 text-sm font-semibold disabled:opacity-40"
                  >
                    {row.scope === "agegroup" ? "Age group" : "Overall"}
                  </button>
                  <button
                    type="button"
                    onClick={() => remove(row)}
                    disabled={busy === row.athlete_slug}
                    className="text-ink-muted min-h-[40px] px-3 py-2 text-sm disabled:opacity-40"
                  >
                    Remove
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function statusCopy(status: string): string {
  switch (status) {
    case "not_started":
      return "Not started";
    case "withdrawn":
      return "No longer on course";
    case "finished":
      return "Finished";
    default:
      return "Racing";
  }
}

function NeighbourChip({ slot, row }: { slot: "ahead" | "behind"; row: RosterRow }) {
  const neighbour = slot === "ahead" ? row.ahead : row.behind;
  if (!neighbour) return <span className="text-ink-muted">{slot === "ahead" ? "leading" : "—"}</span>;

  // Same polarity rule as the dashboard: green is good for our athlete in both rows.
  const good = slot === "ahead" ? neighbour.trend === "closing" : neighbour.trend === "growing";
  const bad = slot === "ahead" ? neighbour.trend === "growing" : neighbour.trend === "closing";
  const colour = good ? "text-good" : bad ? "text-bad" : "text-neutral";
  const arrow = slot === "ahead" ? "\u25b2" : "\u25bc";

  return (
    <span className={`${colour} tabular-nums`}>
      <span aria-hidden="true">{arrow}</span> {neighbour.gap_text}
      {neighbour.is_stale && <span className="text-ink-muted"> (old)</span>}
    </span>
  );
}
