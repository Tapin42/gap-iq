import type { Meta } from "../lib/api";

function formatRemaining(seconds: number | null): string | null {
  if (seconds === null) return null;
  if (seconds < 90) return `~${seconds}s left in replay`;
  const minutes = Math.round(seconds / 60);
  return `~${minutes} min left in replay`;
}

/** Persistent chrome so replay mode cannot be mistaken for a live race. */
export function ReplayBanner({ meta }: { meta: Meta }) {
  if (meta.mode !== "replay" || !meta.replay) return null;

  const { event, replay } = meta;
  const remaining = formatRemaining(replay.remaining_wall_seconds);
  const speedLabel = replay.frozen ? "frozen" : `${replay.speed}×`;

  return (
    <div
      role="status"
      className="bg-replay text-replay-ink border-replay-accent border-b-2 px-4 py-2.5 text-sm font-semibold"
    >
      <div className="truncate text-base font-black tracking-wide uppercase">
        Replay — not live data
      </div>
      <div className="truncate">
        {event.label} · virtual {replay.elapsed_text} · {speedLabel}
        {remaining ? ` · ${remaining}` : null}
      </div>
    </div>
  );
}
