// Types mirror the FastAPI payloads in app/api.py.

export type Trend = "closing" | "growing" | "even" | "undefined";

export interface Neighbour {
  slot: "ahead" | "behind";
  name: string;
  last_name: string;
  bib: string;
  country: string;
  position: number | null;
  gap_tenths: number;
  gap_text: string;
  trend: Trend;
  trend_delta_tenths: number | null;
  trend_delta_text: string | null;
  rate_tenths_per_minute: number | null;
  is_new_occupant: boolean;
  tied: boolean;
  is_stale: boolean;
  checkpoints_back: number;
  measured_at: string | null;
  baseline: string | null;
}

export interface Freshness {
  server_time: number;
  sweep_interval_seconds: number;
  last_upstream_contact_at: number | null;
  last_data_change_at: number | null;
  athlete_last_seen_at: number | null;
  athlete_last_seen_checkpoint: string;
  next_expected_checkpoint: string;
  contact_is_stale: boolean;
  polling: { allowed: boolean; reason: string };
  degraded: boolean;
  degraded_reason: string;
  notes: string[];
}

export interface AthleteSummary {
  athlete_slug: string;
  name: string;
  last_name: string;
  bib: string;
  country: string;
  contest: string;
  scope: string;
  scope_locked: boolean;
  division_slug: string;
}

export interface RosterRow extends AthleteSummary {
  status: string;
  position: number | null;
  field_size: number | null;
  checkpoint: string | null;
  elapsed_text: string | null;
  progress: string;
  ahead: Neighbour | null;
  behind: Neighbour | null;
}

export type RacePhase = "waiting" | "not_started" | "in_progress" | "completed";

export interface RaceSummary {
  phase: RacePhase;
  label: string;
  leading_checkpoint?: string;
}

export interface RosterResponse {
  athletes: RosterRow[];
  race: RaceSummary;
  freshness: Freshness;
  scope_options: string[];
}

export interface AthleteDetail {
  athlete: AthleteSummary;
  status: string;
  has_data: boolean;
  position?: number | null;
  position_context?: "provisional_lead" | "lone_at_mat" | "confirmed";
  field_size?: number;
  division?: { id: string; label: string; scope: string };
  checkpoint?: { id: string; label: string; index: number | null; count: number; is_finish: boolean };
  is_live_checkpoint?: boolean;
  on_course?: boolean;
  elapsed_text?: string | null;
  baseline?: string | null;
  ahead?: Neighbour | null;
  behind?: Neighbour | null;
  absence?: { ahead?: string; behind?: string };
  withdrawal_notes?: string[];
  checkpoints?: { index: number; id: string; label: string }[];
  freshness: Freshness;
}

export interface Meta {
  event: { label: string; edition: string; provider: string };
  polling: { allowed: boolean; reason: string };
  trend_policy: string;
  has_data: boolean;
  roster_count: number;
  freshness: Freshness;
}

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // Non-JSON error body; the status text is the best we have.
    }
    throw new ApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

export const api = {
  meta: () => request<Meta>("/api/meta"),
  roster: () => request<RosterResponse>("/api/roster"),
  athlete: (slug: string, checkpointIndex?: number) =>
    request<AthleteDetail>(
      `/api/athlete/${encodeURIComponent(slug)}` +
        (checkpointIndex === undefined ? "" : `?checkpoint_index=${checkpointIndex}`),
    ),
  refresh: () => request<{ ok: boolean; freshness: Freshness }>("/api/refresh", { method: "POST" }),
  setScope: (slug: string, scope: string) =>
    request<AthleteSummary>(`/api/roster/${encodeURIComponent(slug)}/scope`, {
      method: "PUT",
      body: JSON.stringify({ scope }),
    }),
  remove: (slug: string) =>
    request<{ removed: string }>(`/api/roster/${encodeURIComponent(slug)}`, { method: "DELETE" }),
};
