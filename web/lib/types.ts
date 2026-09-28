export type Run = {
  id: number; disease: string; status: "queued" | "running" | "done" | "failed";
  summary: {
    signals?: number; organisations?: number; contacts?: number; contactable?: number;
    by_source?: Record<string, number>; tiers?: Record<string, number>; new_signals?: number;
    by_registry?: Record<string, number>; regions?: string[];
    fit?: Record<string, number>;
    buyers?: Record<string, number>; commercial?: Record<string, number>;
  };
  created_by: string; watch_id: number | null; created_at: string; finished_at: string | null;
  diagnostics?: Record<string, { distinct: number; iqr: number; informative: boolean }>;
  progress?: string[]; error?: string;
  params?: { regions?: string[]; query?: SearchQuery; top_contacts?: number;
    dataset?: DatasetProfile; dataset_id?: number };
};

export type SearchQuery = {
  disease: string; intervention: string; biomarker: string; data_types: string[];
  population: string; sponsor: string; supply: string[];
};

export const DATA_TYPES: [string, string][] = [
  ["genomic", "Genomic / sequencing"], ["imaging", "Imaging"], ["ehr", "EHR / longitudinal"],
  ["claims", "Claims"], ["biobank", "Biobank / samples"], ["device", "Device / wearable"],
  ["pro", "Patient-reported outcomes"], ["reports", "Radiology reports"],
];

export const ORIGINS: [string, string][] = [
  ["US", "United States"], ["EU", "Europe"], ["UK", "UK"], ["IN", "India"], ["ASIA", "Asia"],
];

export type Signal = {
  source: "publications" | "grants" | "trials" | "devices"; date: string; title: string; url: string;
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
  fit?: Fit; match_score?: number;
  buyer_type?: string; buyer_intent?: "Active buyer" | "Likely buyer" | ""; commercial_evidence?: string[];
};

export type FitRow = { need: string; text: string; evidence: string; why: string };
export type Fit = { score: number; label: "Strong" | "Partial" | "Geographic opening" | "Context only"; summary: string;
  met: FitRow[]; unmet: FitRow[]; unknown: FitRow[];
  /** The one paper, grant or trial the fit rests on. */
  anchor?: { source: string; title: string; url: string; needs: string[] } };

export type DatasetProfile = {
  name: string; partner: string; origin: string[]; diseases: string[]; data_types: string[];
  patients: number | null; disease_patients: Record<string, number>; sites: number | null;
  followup_median_years: number | null; diverse: boolean | null; prospective: boolean | null;
  population: string; coding: string[]; years: string; source: string; notes: string;
  search_focus: string[];
};
export type Dataset = { id: number; name: string; partner: string; profile: DatasetProfile;
  created_by: string; created_at: string; updated_at: string };

export type Contact = {
  org_display: string; org_key: string; person_name: string; person_role: string;
  channel: "email" | "phone" | "none"; value: string | null; why_this_person: string;
  exportable: boolean; gate_reason: string; suppressed: boolean; notes: string[];
  /** author: wrote the paper stating the need · study: contact for the trial/grant stating it ·
   *  organisation: same organisation, different work (older runs have no value). */
  relation?: "author" | "study" | "organisation"; about?: string;
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

export const BUYER_LABEL: Record<string, string> = {
  startup: "Startup / SME", pharma: "Pharma", medtech: "Large medtech", cro: "CRO / imaging core lab",
  bigtech: "Big tech", academic: "Academic", hospital: "Hospital", government: "Government",
};
export const COMMERCIAL = new Set(["startup", "pharma", "medtech", "cro", "bigtech"]);

export const RELATION_LABEL: Record<string, string> = {
  author: "Author of the stated need", study: "Contact for the work stating the need",
  organisation: "Same organisation, different work — check relevance",
};

export const SOURCE_LABEL: Record<string, string> = {
  publications: "Paper", grants: "Grant", trials: "Trial", devices: "Cleared AI device",
};

/** Which registry a signal came from, for the evidence line. */
export const REGISTRY_LABEL: Record<string, string> = {
  "ClinicalTrials.gov": "ClinicalTrials.gov", NIH: "NIH grant", CTIS: "EU trial (CTIS)",
  ISRCTN: "UK trial (ISRCTN)", CORDIS: "EU grant (Horizon)", UKRI: "UK grant (UKRI)",
  FDA: "FDA clearance", "NIH SBIR/STTR": "US startup grant (SBIR/STTR)", BIRAC: "India startup grant (BIRAC)",
};

export const MARKETS = [
  { id: "us", label: "United States", note: "NIH grants" },
  { id: "eu", label: "European Union", note: "CTIS trials, Horizon grants" },
  { id: "uk", label: "United Kingdom", note: "ISRCTN trials, UKRI and Innovate UK grants" },
  { id: "in", label: "India & Asia", note: "BIRAC startup grants; Asian companies via FDA clearances and company research" },
] as const;
