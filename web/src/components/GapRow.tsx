import type { Neighbour } from "../lib/api";

/**
 * One neighbour: bib, three-letter country, and the gap with its trend.
 *
 * The colour polarity is inverted between the two slots so that **green always means good
 * for the tracked athlete**. Closing on the racer ahead is good; the racer behind closing
 * on you is not. That is the whole point of the display, and it is why `trend` from the API
 * describes the gap itself and the mapping to good/bad happens here.
 *
 * Every trend also carries an arrow describing *the number*: down when the gap is
 * shrinking, up when it is growing. Colour and glyph therefore say different things, which
 * is what makes the row readable in direct sun and to a red-green colourblind reader.
 */
export function GapRow({
  slot,
  neighbour,
  absenceCopy,
  historic,
}: {
  slot: "ahead" | "behind";
  neighbour: Neighbour | null;
  absenceCopy?: string;
  historic?: boolean;
}) {
  if (!neighbour) {
    return (
      <div className="flex min-h-[22vh] flex-col justify-center gap-1 px-5 py-4">
        <div className="text-ink-muted text-xs font-semibold tracking-widest uppercase">
          {slot === "ahead" ? "Ahead" : "Behind"}
        </div>
        <p className="text-ink-muted text-lg text-balance">{absenceCopy ?? "No data."}</p>
      </div>
    );
  }

  const good = slot === "ahead" ? neighbour.trend === "closing" : neighbour.trend === "growing";
  const bad = slot === "ahead" ? neighbour.trend === "growing" : neighbour.trend === "closing";

  const colour = neighbour.tied
    ? "text-neutral"
    : good
      ? "text-good"
      : bad
        ? "text-bad"
        : "text-neutral";

  const arrow =
    neighbour.trend === "closing"
      ? "\u2193"
      : neighbour.trend === "growing"
        ? "\u2191"
        : neighbour.trend === "even"
          ? "\u2192"
          : "\u00b7";

  return (
    <div
      className={`flex min-h-[22vh] flex-col justify-center gap-1 px-5 py-4 ${
        historic ? "opacity-90" : ""
      }`}
    >
      <div className="text-ink-muted flex items-center gap-2 text-xs font-semibold tracking-widest uppercase">
        <span>{slot === "ahead" ? "Ahead" : "Behind"}</span>
        {neighbour.is_new_occupant && (
          // The person in this position changed since the baseline. The gap is still a real
          // comparison, so the row stays coloured; this says the name is different.
          <span className="rounded-sm bg-white/15 px-1.5 py-0.5 text-[0.65rem] tracking-wider">
            NEW
          </span>
        )}
        {neighbour.tied && (
          <span className="rounded-sm bg-white/15 px-1.5 py-0.5 text-[0.65rem] tracking-wider">
            LEVEL
          </span>
        )}
      </div>

      <div className="flex items-baseline justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-baseline gap-2">
            {neighbour.bib && (
              <span className="text-ink-muted text-xl tabular-nums">#{neighbour.bib}</span>
            )}
            <span className="text-ink-muted text-xl font-semibold">
              {neighbour.country || "—"}
            </span>
          </div>
          <div className="truncate text-2xl font-bold">
            {neighbour.position ? `${neighbour.position}. ` : ""}
            {neighbour.last_name || neighbour.name}
          </div>
        </div>

        <div className={`text-right ${colour}`}>
          <div className="text-4xl leading-none font-black tabular-nums">
            {neighbour.gap_text}
          </div>
          <div className="mt-1 text-base font-bold whitespace-nowrap">
            <span aria-hidden="true">{arrow}</span>{" "}
            {neighbour.trend === "undefined" ? "no trend yet" : neighbour.trend}
            {neighbour.trend_delta_text && neighbour.trend !== "undefined"
              ? ` ${neighbour.trend_delta_text}`
              : ""}
          </div>
        </div>
      </div>

      {neighbour.is_stale && neighbour.measured_at && (
        // Never present an older measurement as if it were current.
        <p className="text-ink-muted text-sm font-medium text-balance">
          {slot === "ahead"
            ? "Not recorded at this checkpoint yet."
            : "Hasn't reached this checkpoint yet."}{" "}
          Gap is as of <span className="font-semibold">{neighbour.measured_at}</span>.
        </p>
      )}
      {!neighbour.is_stale && neighbour.baseline && neighbour.trend !== "undefined" && (
        <p className="text-ink-muted text-xs">vs {neighbour.baseline}</p>
      )}
    </div>
  );
}
