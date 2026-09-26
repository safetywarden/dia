export type Run = {
  id: number; disease: string; status: "queued" | "running" | "done" | "failed";
  summary: {
    signals?: number; organisations?: number; contacts?: number; contactable?: number;
    by_source?: Record<string, number>; tiers?: Record<string, number>; new_signals?: number;
    by_registry?: Record<string, number>; regions?: string[];
  };
  created_by: string; watch_id: number | null; created_at: string; finished_at: string | null;
  diagnostics?: Record<string, { distinct: number; iqr: number; informative: boolean }>;
  progress?: string[]; error?: string;
};

export type Signal = {
  source: "publications" | "grants" | "trials"; date: string; title: string; url: string;
  snippet: string; person: string; person_role: string; country: string;
  needs: Record<string, string>; extra: Record<string, unknown>;
};

export type Lead = {
  rank: number; is_new: boolean; org_key: string; org_display: string; org_type: string;
  country: string; score: number; tier: "A" | "B" | "C"; sources: string[];
  needs: Record<string, string>; evidence: Record<string, string>;
  dimensions: Record<string, { score: number; informative: boolean; weight: number }>;
  rationale: string[]; named_people: { name: string; role: string; source_url: string }[];
  opening_angle: string; signals: Signal[];
};

export type Contact = {
  org_display: string; org_key: string; person_name: string; person_role: string;
  channel: "email" | "phone" | "none"; value: string | null; why_this_person: string;
  exportable: boolean; gate_reason: string; suppressed: boolean; notes: string[];
  provenance: {
    source_url: string; source_type: string; lawful_basis: string; retrieved_at: string;
    verbatim_snippet: string; jurisdiction: string; publisher: string; country: string;
    jurisdiction_source: string;
  };
};

export type Watch = {
  id: number; disease: string; interval_days: number; active: boolean;
  last_run_at: string | null; signals_tracked: number; last_run: Run | null;
};

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/dia/${path}`, { cache: "no-store", ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } });
  if (res.status === 401) { window.location.href = "/login"; throw new Error("signed out"); }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`);
  }
  return (res.status === 204 ? null : res.json()) as T;
}

export const SOURCE_LABEL: Record<string, string> = {
  publications: "Paper", grants: "Grant", trials: "Trial",
};

/** Which registry a signal came from, for the evidence line. */
export const REGISTRY_LABEL: Record<string, string> = {
  "ClinicalTrials.gov": "ClinicalTrials.gov", NIH: "NIH grant", CTIS: "EU trial (CTIS)",
  ISRCTN: "UK trial (ISRCTN)", CORDIS: "EU grant (Horizon)", UKRI: "UK grant (UKRI)",
};

export const MARKETS = [
  { id: "us", label: "United States", note: "NIH grants" },
  { id: "eu", label: "European Union", note: "CTIS trials, Horizon grants" },
  { id: "uk", label: "United Kingdom", note: "ISRCTN trials, UKRI grants" },
] as const;
