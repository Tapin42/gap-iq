import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { FreshnessBar } from "../components/FreshnessBar";
import { GapRow } from "../components/GapRow";
import { api, type AthleteDetail } from "../lib/api";
import { usePolling } from "../lib/hooks";

// Faster than the roster: this is the screen someone is staring at while an athlete is on
// course. The upstream sweep is the real limit on freshness; this just makes sure the
// client is never the reason a change is late.
const POLL_MS = 15_000;

// If a supporter wanders into history and puts the phone down, return them to live rather
// than leaving an old checkpoint on screen indefinitely.
const HISTORY_IDLE_RETURN_MS = 120_000;

export function Dashboard() {
  const { slug = "" } = useParams();
  const [checkpointIndex, setCheckpointIndex] = useState<number | undefined>(undefined);
  const [prevSlug, setPrevSlug] = useState(slug);
  if (prevSlug !== slug) {
    setPrevSlug(slug);
    setCheckpointIndex(undefined);
  }

  const fetcher = useCallback(
    () => api.athlete(slug, checkpointIndex),
    [slug, checkpointIndex],
  );
  const { data, error, loading, refresh, refreshing } = usePolling<AthleteDetail>(
    fetcher,
    POLL_MS,
    [slug, checkpointIndex],
  );

  // An athlete who withdrew or has not started is not "in history" -- there is no earlier
  // checkpoint being viewed -- so they must not get the history chrome.
  const onCourse = data ? data.on_course !== false : true;
  const showingHistory = data ? onCourse && data.is_live_checkpoint === false : false;
  const wantsHistory = checkpointIndex !== undefined;
  const navigating = Boolean(
    data?.has_data &&
      onCourse &&
      (wantsHistory !== showingHistory ||
        (wantsHistory && checkpointIndex !== data.checkpoint?.index)),
  );
  const historicView = wantsHistory || (showingHistory && !navigating);

  useEffect(() => {
    if (!showingHistory) return;
    const timer = window.setTimeout(() => setCheckpointIndex(undefined), HISTORY_IDLE_RETURN_MS);
    return () => window.clearTimeout(timer);
  }, [showingHistory, checkpointIndex]);

  const onRefresh = useCallback(async () => {
    await api.refresh().catch(() => undefined);
    await refresh();
  }, [refresh]);

  if (loading && !data) {
    return <Shell><Centered>Loading…</Centered></Shell>;
  }

  if (!data) {
    return (
      <Shell>
        <Centered>
          <p className="text-bad text-lg font-semibold">Couldn't load this athlete.</p>
          <p className="text-ink-muted mt-2">{error}</p>
          <button
            type="button"
            onClick={onRefresh}
            className="mt-4 rounded-md bg-white/15 px-4 py-2 font-semibold"
          >
            Try again
          </button>
        </Centered>
      </Shell>
    );
  }

  const { athlete } = data;
  const checkpoints = data.checkpoints ?? [];
  const index = data.checkpoint?.index ?? null;

  const activeIndex = checkpointIndex ?? index;
  const checkpointLabel =
    (wantsHistory
      ? checkpoints.find((cp) => cp.index === checkpointIndex)?.label
      : undefined) ??
    data.checkpoint?.label;

  const step = (delta: number) => {
    if (activeIndex === null) return;
    const next = Math.min(Math.max(activeIndex + delta, 0), checkpoints.length - 1);
    setCheckpointIndex(next);
  };

  return (
    <Shell historic={historicView}>
      {/* Header: who this is, and where they are. */}
      <header className="flex items-start justify-between gap-3 px-4 pt-3 pb-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Link to="/" className="text-ink-muted shrink-0 text-sm font-semibold">
              ‹ Roster
            </Link>
          </div>
          <h1 className="truncate text-lg font-bold">{athlete.name}</h1>
          <p className="text-ink-muted truncate text-sm">
            {athlete.bib && <>#{athlete.bib} · </>}
            {athlete.country || "—"}
            {data.division?.label && <> · {data.division.label}</>}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-ink-muted text-xs tracking-widest uppercase">Elapsed</div>
          <div className="text-xl font-bold tabular-nums">{data.elapsed_text ?? "—"}</div>
        </div>
      </header>

      {historicView && (
        // History has to be unmistakable. Mistaking an old checkpoint for the current one
        // is the exact failure this app exists to prevent, so it gets its own background,
        // a persistent banner, and a single always-visible way back.
        <div className="bg-surface-history flex items-center justify-between gap-3 px-4 py-2">
          <div className="min-w-0">
            <div className="text-xs font-black tracking-widest uppercase">Earlier checkpoint</div>
            <div className="truncate text-sm font-semibold">{checkpointLabel ?? "—"}</div>
          </div>
          <button
            type="button"
            onClick={() => setCheckpointIndex(undefined)}
            className="shrink-0 rounded-md bg-black/40 px-3 py-2 text-sm font-bold"
          >
            Back to live
          </button>
        </div>
      )}

      {!data.has_data || !onCourse ? (
        <Centered>
          {data.status === "withdrawn" ? (
            <>
              <p className="text-xl font-semibold">No longer on course</p>
              <p className="text-ink-muted mt-2 text-balance">
                {athlete.last_name || athlete.name} has withdrawn. The timing feed removes a
                withdrawn athlete's splits, so there is no position or gap to show.
              </p>
            </>
          ) : (
            <>
              <p className="text-xl font-semibold">Not started yet</p>
              <p className="text-ink-muted mt-2 text-balance">
                No timing data for {athlete.last_name || athlete.name} yet. This screen fills
                in at the first checkpoint.
              </p>
            </>
          )}
        </Centered>
      ) : (
        <main className="relative flex flex-1 flex-col divide-y divide-white/15">
          <GapRow
            slot="ahead"
            neighbour={data.ahead ?? null}
            absenceCopy={data.absence?.ahead}
            historic={historicView}
          />

          {/* The centre row: position and family name together, at the largest size on the
              screen. The name is here rather than only in the header because supporters
              transcribe it onto whiteboards, and because when several tracked athletes go
              past at once it has to be instantly clear which one these numbers describe. */}
          <button
            type="button"
            onClick={() => step(-1)}
            disabled={navigating || activeIndex === null || activeIndex <= 0}
            className="bg-surface-raised flex min-h-[26vh] flex-col items-center justify-center gap-1 px-4 py-6 text-center disabled:opacity-100"
          >
            <div className="text-[clamp(3rem,18vw,7rem)] leading-[0.95] font-black tracking-tight">
              {data.position ?? "—"}. {athlete.last_name || athlete.name}
            </div>
            <div className="text-ink-muted text-sm">
              {data.field_size ? `of ${data.field_size} in ${data.division?.label ?? "division"}` : ""}
              {data.checkpoint?.is_finish && " · finished"}
            </div>
            {activeIndex !== null && activeIndex > 0 && !historicView && (
              <div className="text-ink-muted mt-1 text-xs">tap for the previous checkpoint</div>
            )}
          </button>

          <GapRow
            slot="behind"
            neighbour={data.behind ?? null}
            absenceCopy={data.absence?.behind}
            historic={historicView}
          />

          {navigating && (
            <div className="absolute inset-0 flex items-center justify-center bg-black/45 px-8 text-center">
              <p className="text-lg font-semibold">Loading checkpoint…</p>
            </div>
          )}
        </main>
      )}

      {(data.withdrawal_notes ?? []).length > 0 && (
        // A place gained because a rival stopped racing is not a place gained by racing.
        <div className="bg-white/10 px-4 py-2 text-sm">
          {data.withdrawal_notes!.map((note) => (
            <p key={note}>Moved up — {note}.</p>
          ))}
        </div>
      )}

      {historicView && activeIndex !== null && (
        <div className="flex items-center justify-between gap-2 px-4 py-2">
          <button
            type="button"
            onClick={() => step(-1)}
            disabled={navigating || activeIndex <= 0}
            className="rounded-md bg-white/15 px-4 py-3 font-semibold disabled:opacity-40"
          >
            ‹ Earlier
          </button>
          <span className="text-ink-muted text-xs">
            {activeIndex + 1} of {checkpoints.length}
          </span>
          <button
            type="button"
            onClick={() => step(1)}
            disabled={navigating || activeIndex >= checkpoints.length - 1}
            className="rounded-md bg-white/15 px-4 py-3 font-semibold disabled:opacity-40"
          >
            Later ›
          </button>
        </div>
      )}

      <FreshnessBar
        freshness={data.freshness}
        onRefresh={onRefresh}
        refreshing={refreshing}
        error={error}
      />
    </Shell>
  );
}

function Shell({ children, historic }: { children: React.ReactNode; historic?: boolean }) {
  return (
    <div
      className={`flex min-h-full flex-col ${historic ? "bg-surface-history/25" : "bg-surface"}`}
    >
      {children}
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-8 text-center">
      {children}
    </div>
  );
}
