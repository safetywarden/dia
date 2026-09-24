"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, SOURCE_LABEL, type Contact, type Lead, type Run } from "@/lib/types";

type Tab = "leads" | "contacts" | "method";
const DIM_LABEL: Record<string, string> = {
  signal_convergence: "Convergence", stated_need_fit: "Stated need", budget_signal: "Budget",
  recency: "Recency", geographic_opening: "No India sites", reachability: "Named people",
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
      <h1>Who needs {run.disease} data</h1>
      <p className="muted small">
        Search #{run.id} · started by {run.created_by} · {new Date(run.created_at).toLocaleString()} ·{" "}
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
          {tab === "leads" && <Leads leads={leads} contactsByOrg={byOrg} onContacts={() => setTab("contacts")} />}
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

function Leads({ leads, contactsByOrg, onContacts }:
  { leads: Lead[]; contactsByOrg: Record<string, number>; onContacts: () => void }) {
  const [tiers, setTiers] = useState<Set<string>>(new Set(["A", "B"]));
  const [type, setType] = useState("all");
  const [stated, setStated] = useState(false);
  const [newOnly, setNewOnly] = useState(false);
  const [q, setQ] = useState("");
  const anyNew = leads.some((l) => l.is_new);

  const shown = useMemo(() => leads.filter((l) =>
    tiers.has(l.tier) && (type === "all" || l.org_type === type)
    && (!stated || Object.keys(l.evidence).some((k) => k in NEED_LABEL))
    && (!newOnly || l.is_new)
    && (!q || l.org_display.toLowerCase().includes(q.toLowerCase()))), [leads, tiers, type, stated, newOnly, q]);

  const toggle = (t: string) => setTiers((s) => {
    const n = new Set(s); if (n.has(t)) n.delete(t); else n.add(t); return n;
  });

  return (
    <>
      <div className="filters">
        {["A", "B", "C"].map((t) => (
          <button key={t} className="chip" aria-pressed={tiers.has(t)} onClick={() => toggle(t)}>Tier {t}</button>
        ))}
        <button className="chip" aria-pressed={stated} onClick={() => setStated(!stated)}>Stated a data gap</button>
        {anyNew && <button className="chip" aria-pressed={newOnly} onClick={() => setNewOnly(!newOnly)}>New only</button>}
        <select value={type} onChange={(e) => setType(e.target.value)} style={{ width: "auto" }}>
          <option value="all">All types</option><option value="industry">Industry</option>
          <option value="academic">Academic</option><option value="hospital">Hospital</option>
          <option value="government">Government</option>
        </select>
        <input placeholder="Filter by name" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 200 }} />
        <span className="muted small">{shown.length} shown</span>
      </div>
      {shown.map((l) => <LeadCard key={l.org_key} lead={l} contacts={contactsByOrg[l.org_key] ?? 0} onContacts={onContacts} />)}
      {shown.length === 0 && <p className="muted">No leads match these filters.</p>}
    </>
  );
}

function LeadCard({ lead: l, contacts, onContacts }: { lead: Lead; contacts: number; onContacts: () => void }) {
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
            {l.is_new && <span className="badge new">new</span>}</h3>
          <div className="muted small">
            #{l.rank} · {l.org_type}{l.country && ` · ${l.country}`} · seen in{" "}
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

      {stated.map(([labels, text]) => (
        <blockquote key={text}><strong>{labels}</strong>“{text}”</blockquote>
      ))}

      <details>
        <summary>Evidence ({l.signals.length})</summary>
        {l.signals.slice(0, 12).map((s) => (
          <p key={s.url} className="ev">
            <strong>{SOURCE_LABEL[s.source]}</strong> · {s.date || "undated"} ·{" "}
            <a href={s.url} target="_blank" rel="noopener noreferrer">{s.title}</a> — {s.snippet}
          </p>
        ))}
        {l.named_people.length > 0 && (
          <p className="ev">Publicly named: {l.named_people.slice(0, 8).map((p) => `${p.name} (${p.role})`).join("; ")}.
            No contact details inferred.</p>
        )}
      </details>
      <div className="angle"><strong>Opening angle.</strong> {l.opening_angle}</div>
    </article>
  );
}

function Contacts({ runId, contacts, reload }: { runId: number; contacts: Contact[]; reload: () => void }) {
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const ok = contacts.filter((c) => c.exportable);
  const blocked = contacts.filter((c) => !c.exportable);

  async function exportCsv() {
    setBusy(true); setMsg("");
    try {
      const res = await fetch(`/api/atlas/runs/${runId}/contacts.csv`, { cache: "no-store" });
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
                <td><strong>{c.person_name}</strong><div className="muted small">{c.person_role} · {c.org_display}</div></td>
                <td className="mono">{c.value}<div className="muted small">{c.channel}</div></td>
                <td className="small">
                  <a href={c.provenance.source_url} target="_blank" rel="noopener noreferrer">{c.provenance.publisher || "source"}</a>
                  <details><summary>Published text</summary><q>{c.provenance.verbatim_snippet}</q></details>
                </td>
                <td className="small">
                  {c.provenance.lawful_basis.replaceAll("_", " ")}
                  <div className="muted">{c.provenance.jurisdiction}{c.provenance.country && ` (${c.provenance.country}`}
                    {c.provenance.jurisdiction_source && `, from ${c.provenance.jurisdiction_source}`}{c.provenance.country && ")"}</div>
                </td>
                <td><button className="link small" onClick={() => suppress(c)}>Do not contact</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        {ok.length === 0 && <p className="muted">No published contacts were found for these leads.</p>}
      </div>

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
