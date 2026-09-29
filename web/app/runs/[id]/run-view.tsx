"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { DraftPanel } from "../../outreach-panel";
import { api, BUYER_LABEL, COMMERCIAL, REGISTRY_LABEL, RELATION_LABEL, SOURCE_LABEL, type Contact, type Lead, type Run } from "@/lib/types";

type Tab = "leads" | "contacts" | "method";
const DIM_LABEL: Record<string, string> = {
  signal_convergence: "Convergence", stated_need_fit: "Stated need", budget_signal: "Budget",
  recency: "Recency", geographic_opening: "Geographic gap", reachability: "Named people",
};
const BASIS_LABEL: Record<string, string> = {
  DPDP_3C_II_PUBLIC: "Made public by the person for contact (DPDP §3(c)(ii) standard)",
  GDPR_LEGITIMATE_INTEREST: "Legitimate interest (GDPR Art. 6(1)(f))",
  STATUTORY_PUBLICATION: "Published under a legal obligation",
  CONSENT: "Consent",
};
const NEED_LABEL: Record<string, string> = {
  diverse_population: "Needs under-represented population data",
  external_validation: "Needs an external validation cohort",
  single_centre: "Limited to a single centre",
  generalisability: "Needs generalisable evidence",
  small_sample: "Needs a larger cohort",
  real_world_data: "Needs real-world data",
  longitudinal_gap: "Needs longer follow-up",
  retrospective_only: "Limited to retrospective data",
  data_genomic: "Needs genomic / sequencing data",
  data_imaging: "Needs imaging data",
  data_ehr: "Needs longitudinal EHR data",
  data_claims: "Needs claims / administrative data",
  data_biobank: "Needs biobank samples",
  data_device: "Needs wearable / monitoring data",
  data_pro: "Needs patient-reported outcomes",
  data_reports: "Needs paired radiology reports",
  data_ultrasound: "Needs ultrasound / echo data",
  data_ecg: "Needs ECG / EKG data",
};

export default function RunView({ id }: { id: number }) {
  const [run, setRun] = useState<Run | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [tab, setTab] = useState<Tab>("leads");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await api<Run>(`runs/${id}`);
      setRun(r);
      if (r.status === "done") {
        const [l, c] = await Promise.all([api<Lead[]>(`runs/${id}/leads`),
                                          api<Contact[]>(`runs/${id}/contacts`)]);
        setLeads(l); setContacts(c);
      }
    } catch (e) { setError((e as Error).message); }
  }, [id]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!run || run.status === "done" || run.status === "failed") return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [run, load]);

  if (error) return <main className="wrap"><p className="error">{error}</p></main>;
  if (!run) return <main className="wrap"><p className="muted">Loading…</p></main>;

  const s = run.summary ?? {};
  const byOrg = contacts.reduce<Record<string, number>>((m, c) => {
    if (c.exportable) m[c.org_key] = (m[c.org_key] ?? 0) + 1;
    return m;
  }, {});

  return (
    <main className="wrap">
      <p className="small"><Link href="/">← All searches</Link></p>
      <h1>{run.params?.dataset ? run.disease : `Who needs ${run.disease} data`}</h1>
      <p className="muted small">
        Search #{run.id} · started by {run.created_by} · {new Date(run.created_at).toLocaleString()} ·{" "}
        {s.regions && <>markets {s.regions.map((x) => x.toUpperCase()).join(", ")} ·{" "}</>}
        <span className={`s-${run.status}`}>{run.status}</span>
      </p>

      {(run.status === "queued" || run.status === "running") && (
        <div className="card" style={{ marginTop: 16 }}>
          <p style={{ marginTop: 0 }}><strong>{run.status === "queued" ? "Queued…" : "Searching public registries…"}</strong>{" "}
            <span className="muted small">This usually takes 2–5 minutes.</span></p>
          <pre className="log">{(run.progress ?? []).slice(-12).join("\n")}</pre>
        </div>
      )}
      {run.status === "failed" && <div className="card"><p className="error">This search failed: {run.error}</p></div>}

      {run.status === "done" && (
        <>
          <div className="tiles">
            <Tile n={s.organisations} l="Organisations" />
            {s.commercial && <Tile n={(s.commercial["Active buyer"] ?? 0) + (s.commercial["Likely buyer"] ?? 0)} l="Commercial buyers" />}
            {s.fit && <><Tile n={s.fit.Strong} l="Strong fit" /><Tile n={s.fit.Partial} l="Partial fit" />
              <Tile n={s.fit["Geographic opening"]} l="Geographic opening" /></>}
            <Tile n={s.tiers?.A} l="Tier A" />
            <Tile n={s.tiers?.B} l="Tier B" />
            <Tile n={s.signals} l="Signals" />
            <Tile n={s.contactable} l="Contactable" />
            {s.new_signals !== undefined && <Tile n={s.new_signals} l="New since last run" />}
          </div>
          <div className="tabs" role="tablist">
            {(["leads", "contacts", "method"] as Tab[]).map((t) => (
              <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
                {t === "leads" ? `Leads (${leads.length})` : t === "contacts"
                  ? `Contacts (${contacts.filter((c) => c.exportable).length})` : "How scored"}
              </button>
            ))}
          </div>
          {run.params?.dataset && tab === "leads" && <DatasetCard p={run.params.dataset} />}
          {tab === "leads" && <Leads runId={id} isMatch={!!run.params?.dataset} leads={leads} contactsByOrg={byOrg} onContacts={() => setTab("contacts")} />}
          {tab === "contacts" && <Contacts runId={id} contacts={contacts} reload={load} />}
          {tab === "method" && <Method run={run} />}
        </>
      )}
    </main>
  );
}

function Tile({ n, l }: { n?: number; l: string }) {
  return <div className="tile"><div className="n">{n ?? "—"}</div><div className="l">{l}</div></div>;
}

function Leads({ runId, leads, contactsByOrg, onContacts, isMatch = false }:
  { runId: number; leads: Lead[]; contactsByOrg: Record<string, number>; onContacts: () => void; isMatch?: boolean }) {
  // A buyer match is ranked by fit, so show every tier but only real fits by default.
  const [tiers, setTiers] = useState<Set<string>>(new Set(isMatch ? ["A", "B", "C"] : ["A", "B"]));
  const [fitOnly, setFitOnly] = useState(isMatch);
  const [type, setType] = useState("all");
  const [stated, setStated] = useState(false);
  const [newOnly, setNewOnly] = useState(false);
  const [q, setQ] = useState("");
  const anyNew = leads.some((l) => l.is_new);
  const isBuyer = (l: Lead) => COMMERCIAL.has(l.buyer_type ?? "") && !!l.buyer_intent;
  const nBuyers = leads.filter(isBuyer).length;
  // Companies pay for data; researchers mostly state the need. Show buyers first when there are any.
  // Leads arrive after the first render, so the default is decided from them, not at mount.
  const [picked, setView] = useState<"buyers" | "research" | "all" | null>(null);
  const view = picked ?? (nBuyers ? "buyers" : "all");
  const INTENT = { "Active buyer": 0, "Likely buyer": 1, "": 2 } as const;

  const shown = useMemo(() => leads.filter((l) =>
    (view === "buyers" ? isBuyer(l) : view === "research" ? !isBuyer(l) && tiers.has(l.tier) : tiers.has(l.tier))
    && (type === "all" || (l.buyer_type ?? l.org_type) === type)
    && (!fitOnly || (l.fit && l.fit.label !== "Context only"))
    && (!stated || Object.keys(l.evidence).some((k) => k in NEED_LABEL))
    && (!newOnly || l.is_new)
    && (!q || l.org_display.toLowerCase().includes(q.toLowerCase())))
    .sort((a, b) => view === "buyers" ? INTENT[a.buyer_intent ?? ""] - INTENT[b.buyer_intent ?? ""] : 0),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [leads, tiers, type, stated, newOnly, q, fitOnly, view]);

  const toggle = (t: string) => setTiers((s) => {
    const n = new Set(s); if (n.has(t)) n.delete(t); else n.add(t); return n;
  });

  return (
    <>
      <div className="filters">
        <button className="chip" aria-pressed={view === "buyers"} onClick={() => setView("buyers")}>Commercial buyers ({nBuyers})</button>
        <button className="chip" aria-pressed={view === "research"} onClick={() => setView("research")}>Research demand</button>
        <button className="chip" aria-pressed={view === "all"} onClick={() => setView("all")}>All</button>
        <span className="muted small">·</span>
        {view !== "buyers" && ["A", "B", "C"].map((t) => (
          <button key={t} className="chip" aria-pressed={tiers.has(t)} onClick={() => toggle(t)}>Tier {t}</button>
        ))}
        {isMatch && <button className="chip" aria-pressed={fitOnly} onClick={() => setFitOnly(!fitOnly)}>Hide context-only</button>}
        <button className="chip" aria-pressed={stated} onClick={() => setStated(!stated)}>Stated a data gap</button>
        {anyNew && <button className="chip" aria-pressed={newOnly} onClick={() => setNewOnly(!newOnly)}>New only</button>}
        <select value={type} onChange={(e) => setType(e.target.value)} style={{ width: "auto" }}>
          <option value="all">All types</option>
          {Object.entries(BUYER_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <input placeholder="Filter by name" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 200 }} />
        <span className="muted small">{shown.length} shown</span>
      </div>
      {shown.map((l) => <LeadCard key={l.org_key} runId={runId} lead={l} contacts={contactsByOrg[l.org_key] ?? 0} onContacts={onContacts} />)}
      {shown.length === 0 && <p className="muted">No leads match these filters.</p>}
    </>
  );
}

function LeadCard({ runId, lead: l, contacts, onContacts }: { runId: number; lead: Lead; contacts: number; onContacts: () => void }) {
  const [drafting, setDrafting] = useState(false);
  // One quote per sentence, listing every need it evidences.
  const stated = Object.entries(l.evidence).filter(([k]) => k in NEED_LABEL)
    .reduce<[string, string][]>((acc, [k, text]) => {
      const hit = acc.find(([, t]) => t === text);
      if (hit) hit[0] += ` · ${NEED_LABEL[k]}`; else acc.push([NEED_LABEL[k], text]);
      return acc;
    }, []);
  return (
    <article className="card lead">
      <div className="lead-head">
        <div>
          <h3>{l.org_display} <span className={`pill t${l.tier}`}>Tier {l.tier}</span>
            {l.buyer_intent && <span className={`pill ${l.buyer_intent === "Active buyer" ? "tA" : "tB"}`}>{l.buyer_intent}</span>}
            {l.is_new && <span className="badge new">new</span>}</h3>
          <div className="muted small">
            #{l.rank} · {BUYER_LABEL[l.buyer_type ?? ""] ?? l.org_type}{l.country && ` · ${l.country}`} · seen in{" "}
            {l.sources.map((s) => SOURCE_LABEL[s] ?? s).join(", ")}
            {contacts > 0 && <> · <button className="link" onClick={onContacts}>{contacts} contactable</button></>}
          </div>
        </div>
        <div className="score">{l.score.toFixed(0)}<small>of 100</small></div>
      </div>

      <div className="dims">
        {Object.entries(l.dimensions).map(([d, v]) => v.informative ? (
          <span key={d} title={`weight ${(v.weight * 100).toFixed(0)}%`}>
            {DIM_LABEL[d] ?? d}<span className="bar"><i style={{ width: `${v.score * 100}%` }} /></span>
          </span>
        ) : v.score > 0 ? (
          <span key={d} className="badge" title="Flag only: this dimension does not separate leads in this search, so it is not scored">
            {DIM_LABEL[d] ?? d}
          </span>
        ) : null)}
      </div>

      {(l.commercial_evidence ?? []).length > 0 && (
        <ul className="small commercial">
          {l.commercial_evidence!.map((e) => <li key={e}>{e}</li>)}
        </ul>
      )}
      {stated.map(([labels, text]) => (
        <blockquote key={text}><strong>{labels}</strong>“{text}”</blockquote>
      ))}

      <details>
        <summary>Evidence ({l.signals.length})</summary>
        {l.signals.slice(0, 12).map((s) => (
          <p key={s.url} className="ev">
            <strong>{REGISTRY_LABEL[String(s.extra?.registry ?? "")] ?? SOURCE_LABEL[s.source]}</strong> · {s.date || "undated"} ·{" "}
            <a href={s.url} target="_blank" rel="noopener noreferrer">{s.title}</a> — {s.snippet}
          </p>
        ))}
        {l.named_people.length > 0 && (
          <p className="ev">Publicly named: {l.named_people.slice(0, 8).map((p) => `${p.name} (${p.role})`).join("; ")}.
            No contact details inferred.</p>
        )}
      </details>
      {l.fit && <FitBlock fit={l.fit} />}
      <div className="angle"><strong>Opening angle.</strong> {l.opening_angle}
        {!drafting && <> <button className="btn small" onClick={() => setDrafting(true)}>Draft outreach</button></>}</div>
      {drafting && <DraftPanel runId={runId} orgKey={l.org_key} orgName={l.org_display} onClose={() => setDrafting(false)} />}
    </article>
  );
}

const FIT_CLASS: Record<string, string> = { Strong: "tA", Partial: "tB", "Geographic opening": "tB", "Context only": "tC" };

function FitBlock({ fit }: { fit: NonNullable<Lead["fit"]> }) {
  return (
    <div className="fit">
      <div><span className={`pill ${FIT_CLASS[fit.label]}`}>{fit.label === "Geographic opening" ? fit.label : `${fit.label} fit`}</span>{" "}
        <span className="muted small">{fit.summary} by this dataset</span></div>
      {fit.anchor && (
        <p className="small" style={{ margin: "6px 0 0" }}>Rests on: <a href={fit.anchor.url} target="_blank"
          rel="noopener noreferrer">{fit.anchor.title}</a></p>
      )}
      <ul>
        {fit.met.map((r) => <li key={r.need} className="met">✓ Needs {r.text} — <strong>{r.why}</strong></li>)}
        {fit.unmet.map((r) => <li key={r.need} className="unmet">✗ Needs {r.text} — {r.why}</li>)}
        {fit.unknown.map((r) => <li key={r.need} className="unknown">? Needs {r.text} — {r.why}</li>)}
      </ul>
    </div>
  );
}

function DatasetCard({ p }: { p: NonNullable<NonNullable<Run["params"]>["dataset"]> }) {
  const facts = [
    p.origin.length ? `from ${p.origin.join(", ")}` : "worldwide",
    p.data_types.length ? p.data_types.join(", ") : "",
    p.patients != null ? `${p.patients.toLocaleString()} patients` : "",
    p.sites != null ? `${p.sites} sites` : "",
    p.followup_median_years != null ? `median follow-up ${p.followup_median_years} y` : "",
  ].filter(Boolean);
  return (
    <div className="gate" style={{ marginBottom: 14 }}>
      <div><strong>{p.name}</strong>{p.partner && <span className="muted"> · {p.partner}</span>}
        <div className="muted small">{p.diseases.join(", ")} · {facts.join(" · ")}</div></div>
      <a className="small" href="/datasets">Edit profile</a>
    </div>
  );
}

function Contacts({ runId, contacts, reload }: { runId: number; contacts: Contact[]; reload: () => void }) {
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [draftFor, setDraftFor] = useState<number | null>(null);
  const ok = contacts.filter((c) => c.exportable);
  const blocked = contacts.filter((c) => !c.exportable);

  async function exportCsv() {
    setBusy(true); setMsg("");
    try {
      const res = await fetch(`/api/dia/runs/${runId}/contacts.csv`, { cache: "no-store" });
      if (!res.ok) throw new Error(`Export failed (${res.status})`);
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? "contacts.csv";
      a.click();
      URL.revokeObjectURL(a.href);
      setMsg(`Exported ${res.headers.get("x-exported-rows")} records. ${res.headers.get("x-excluded-rows")} ` +
             `were held back by the lawful-basis gate or the do-not-contact list. This export is logged.`);
    } catch (e) { setMsg((e as Error).message); }
    setBusy(false);
  }

  async function suppress(c: Contact) {
    const value = c.value ?? c.person_name;
    if (!confirm(`Add ${value} to the do-not-contact list? It will be excluded from every search and export.`)) return;
    await api("suppression", { method: "POST", body: JSON.stringify({ value, reason: "added from results" }) });
    reload();
  }

  return (
    <>
      <div className="gate">
        <div>
          <strong className="ok">{ok.length} contactable</strong> · <span className="muted">{blocked.length} named but not contactable</span>
          <div className="muted small">Only details published to be contacted — corresponding-author emails and registry
            study contacts. Nothing guessed, no social platforms, no bought lists.</div>
        </div>
        <button className="btn primary" onClick={exportCsv} disabled={busy || ok.length === 0}>
          {busy ? "Exporting…" : "Export CSV"}</button>
      </div>
      {msg && <p className="small">{msg}</p>}

      <div className="card table-wrap">
        <table>
          <thead><tr><th>Person</th><th>Contact</th><th>Where it was published</th><th>Basis</th><th /></tr></thead>
          <tbody>
            {ok.map((c, i) => (
              <tr key={i}>
                <td><strong>{c.person_name}</strong><div className="muted small">{c.person_role} · {c.org_display}</div>
                  {c.relation && <div className={`small rel-${c.relation}`}>{RELATION_LABEL[c.relation]}</div>}
                  {c.about && <div className="muted small">Re: {c.about}</div>}</td>
                <td className="mono">{c.value}<div className="muted small">{c.channel}</div></td>
                <td className="small">
                  <a href={c.provenance.source_url} target="_blank" rel="noopener noreferrer">{c.provenance.publisher || "source"}</a>
                  <details><summary>Published text</summary><q>{c.provenance.verbatim_snippet}</q></details>
                </td>
                <td className="small">
                  <span title={c.provenance.lawful_basis}>{BASIS_LABEL[c.provenance.lawful_basis] ?? c.provenance.lawful_basis}</span>
                  <div className="muted">{c.provenance.jurisdiction}{c.provenance.country && ` (${c.provenance.country}`}
                    {c.provenance.jurisdiction_source && `, from ${c.provenance.jurisdiction_source}`}{c.provenance.country && ")"}</div>
                </td>
                <td className="small" style={{ whiteSpace: "nowrap" }}>
                  <button className="link" onClick={() => setDraftFor(draftFor === i ? null : i)}>Draft email</button>{" · "}
                  <button className="link" onClick={() => suppress(c)}>Do not contact</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        {ok.length === 0 && <p className="muted">No published contacts were found for these leads.</p>}
      </div>
      {draftFor !== null && ok[draftFor] && (
        <DraftPanel key={draftFor} runId={runId} orgKey={ok[draftFor].org_key} orgName={ok[draftFor].org_display}
          person={/^(corresponding author|company contact)/i.test(ok[draftFor].person_name) ? "" : ok[draftFor].person_name}
          email={ok[draftFor].value ?? ""} foundAt={`${ok[draftFor].provenance.publisher}: ${ok[draftFor].provenance.source_url}`}
          onClose={() => setDraftFor(null)} />
      )}

      {blocked.length > 0 && (
        <>
          <h2>Named, but no published contact</h2>
          <p className="muted small">Publicly identified, but they did not publish an address. Approach through the
            institution&apos;s own published research-office channel. Do not guess an address.</p>
          <div className="card table-wrap">
            <table>
              <thead><tr><th>Person</th><th>Organisation</th><th>Why not contactable</th></tr></thead>
              <tbody>
                {blocked.slice(0, 100).map((c, i) => (
                  <tr key={i}>
                    <td>{c.person_name}<div className="muted small">{c.person_role}</div></td>
                    <td className="small">{c.org_display}</td>
                    <td className="small muted">{c.gate_reason} · <a href={c.provenance.source_url} target="_blank" rel="noopener noreferrer">source</a></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}

function Method({ run }: { run: Run }) {
  return (
    <div className="card">
      <p style={{ marginTop: 0 }}>Each dimension is checked for whether it actually separates organisations in this search.
        A dimension that does not is shown as a flag and <strong>left out of the score</strong> — no constant is dressed
        up as a measurement. Scores are absolute, not rescaled so the top lead reads 100.</p>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Dimension</th><th>Distinct values</th><th>Spread (IQR)</th><th>Used in score</th></tr></thead>
          <tbody>
            {Object.entries(run.diagnostics ?? {}).map(([d, v]) => (
              <tr key={d}><td>{DIM_LABEL[d] ?? d}</td><td>{v.distinct}</td><td>{v.iqr.toFixed(2)}</td>
                <td className={v.informative ? "ok" : "muted"}>{v.informative ? "Yes" : "No — flag only"}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">Sources: Europe PMC (stated limitations in abstracts), NIH RePORTER (active funded
        projects), ClinicalTrials.gov (active studies and their country footprint). No patient data is used.</p>
    </div>
  );
}
