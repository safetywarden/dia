"use client";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, DATA_TYPES, MARKETS, ORIGINS, type Dataset, type DatasetProfile, type Run } from "@/lib/types";

const EMPTY: DatasetProfile = {
  name: "", partner: "", origin: [], diseases: [], data_types: [], patients: null, disease_patients: {},
  sites: null, followup_median_years: null, diverse: null, prospective: null, population: "",
  coding: [], years: "", source: "manual", notes: "",
};

const num = (v: string) => (v.trim() === "" ? null : Number(v));
const tri = (v: boolean | null) => (v === null ? "" : v ? "yes" : "no");
const untri = (v: string) => (v === "" ? null : v === "yes");

export default function Datasets() {
  const router = useRouter();
  const [rows, setRows] = useState<Dataset[] | null>(null);
  const [editing, setEditing] = useState<{ id?: number; p: DatasetProfile } | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => api<Dataset[]>("datasets").then(setRows).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);

  async function findBuyers(d: Dataset) {
    setError("");
    try {
      const r = await api<Run>(`datasets/${d.id}/match`, { method: "POST",
        body: JSON.stringify({ regions: MARKETS.map((m) => m.id), top_contacts: 20 }) });
      router.push(`/runs/${r.id}`);
    } catch (e) { setError((e as Error).message); }
  }

  async function remove(d: Dataset) {
    if (!confirm(`Delete the profile "${d.name}"? Past buyer searches are kept.`)) return;
    await api(`datasets/${d.id}`, { method: "DELETE" });
    load();
  }

  return (
    <main className="wrap">
      <p className="eyebrow">Who needs this dataset?</p>
      <h1>Datasets</h1>
      <p className="muted">Describe a dataset BCONZ can supply. DIA finds organisations whose own papers, grants and trials
        say they need it, and checks each stated need against what the dataset actually contains.</p>

      <div className="row" style={{ margin: "16px 0" }}>
        <button className="btn primary" onClick={() => setEditing({ p: { ...EMPTY } })}>New dataset</button>
        <HarmImport onProfile={(p) => setEditing({ p })} onError={setError} />
      </div>
      {error && <p className="error">{error}</p>}

      {editing && <ProfileForm initial={editing.p} id={editing.id}
                               onDone={() => { setEditing(null); load(); }} onCancel={() => setEditing(null)} />}

      <div className="card table-wrap" style={{ marginTop: 16 }}>
        {rows === null ? <p className="muted">Loading…</p> : rows.length === 0 ? (
          <p className="muted">No datasets yet. Add one, or build it from a HARM readiness report.</p>
        ) : (
          <table>
            <thead><tr><th>Dataset</th><th>From</th><th>Diseases</th><th>Data</th><th>Patients</th><th /></tr></thead>
            <tbody>
              {rows.map((d) => (
                <tr key={d.id}>
                  <td><strong>{d.name}</strong><div className="muted small">{d.partner}{d.profile.source === "harm" && " · from HARM"}</div></td>
                  <td className="small">{d.profile.origin.join(", ") || "worldwide"}</td>
                  <td className="small">{d.profile.diseases.join(", ")}</td>
                  <td className="small">{d.profile.data_types.join(", ") || "—"}</td>
                  <td className="small">{d.profile.patients?.toLocaleString() ?? "—"}</td>
                  <td className="small" style={{ whiteSpace: "nowrap" }}>
                    <button className="btn primary" onClick={() => findBuyers(d)}>Find buyers</button>{" "}
                    <button className="link" onClick={() => setEditing({ id: d.id, p: d.profile })}>Edit</button>{" · "}
                    <button className="link" onClick={() => remove(d)}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </main>
  );
}

function HarmImport({ onProfile, onError }: { onProfile: (p: DatasetProfile) => void; onError: (m: string) => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [diseases, setDiseases] = useState("");
  const [origin, setOrigin] = useState("US");
  const [file, setFile] = useState<File | null>(null);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    try {
      const report = JSON.parse(await file.text());
      const p = await api<DatasetProfile>("datasets/from-harm", { method: "POST", body: JSON.stringify({
        name, origin: origin ? [origin] : [], diseases: diseases.split(",").map((s) => s.trim()).filter(Boolean), report }) });
      onProfile(p); setOpen(false);
    } catch (err) { onError(`Could not read that report: ${(err as Error).message}`); }
  }

  if (!open) return <button className="btn" onClick={() => setOpen(true)}>From HARM report…</button>;
  return (
    <form className="card grid2" onSubmit={run} style={{ flex: 1 }}>
      <label>Dataset name<input value={name} onChange={(e) => setName(e.target.value)} required minLength={2} /></label>
      <label>Diseases (comma-separated)<input value={diseases} onChange={(e) => setDiseases(e.target.value)} required
             placeholder="glaucoma, diabetic retinopathy" /></label>
      <label>Data comes from<select value={origin} onChange={(e) => setOrigin(e.target.value)}>
        {ORIGINS.map(([id, l]) => <option key={id} value={id}>{l}</option>)}</select></label>
      <label>readiness_report.json<input type="file" accept=".json,application/json" required
             onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label>
      <p className="muted small" style={{ gridColumn: "1 / -1", margin: 0 }}>
        Only aggregate counts are read (patients, follow-up, data domains, cohort counts). You review and save the profile;
        the report itself is not stored.</p>
      <div className="row"><button className="btn primary">Build profile</button>
        <button type="button" className="link" onClick={() => setOpen(false)}>Cancel</button></div>
    </form>
  );
}

function ProfileForm({ initial, id, onDone, onCancel }:
  { initial: DatasetProfile; id?: number; onDone: () => void; onCancel: () => void }) {
  const [p, setP] = useState<DatasetProfile>(initial);
  const [diseases, setDiseases] = useState(initial.diseases.join(", "));
  const [error, setError] = useState("");
  const set = <K extends keyof DatasetProfile>(k: K, v: DatasetProfile[K]) => setP({ ...p, [k]: v });
  const toggle = (k: "origin" | "data_types", v: string, on: boolean) =>
    set(k, on ? [...p[k], v] : p[k].filter((x) => x !== v));

  async function save(e: React.FormEvent) {
    e.preventDefault(); setError("");
    const body = { ...p, diseases: diseases.split(",").map((s) => s.trim()).filter(Boolean) };
    try {
      await api(id ? `datasets/${id}` : "datasets", { method: id ? "PUT" : "POST", body: JSON.stringify(body) });
      onDone();
    } catch (err) { setError((err as Error).message); }
  }

  return (
    <form className="card search" onSubmit={save} style={{ marginTop: 12 }}>
      <h2 style={{ margin: 0 }}>{id ? "Edit dataset" : "New dataset"}{p.source === "harm" && <span className="badge">from HARM</span>}</h2>
      <div className="grid2">
        <label>Name<input value={p.name} onChange={(e) => set("name", e.target.value)} required minLength={2} /></label>
        <label>Supplying partner<input value={p.partner} onChange={(e) => set("partner", e.target.value)} /></label>
        <label style={{ gridColumn: "1 / -1" }}>Diseases (comma-separated)
          <input value={diseases} onChange={(e) => setDiseases(e.target.value)} required placeholder="glaucoma, diabetic retinopathy" /></label>
        <label>Patients<input type="number" min={0} value={p.patients ?? ""} onChange={(e) => set("patients", num(e.target.value))} /></label>
        <label>Sites<input type="number" min={0} value={p.sites ?? ""} onChange={(e) => set("sites", num(e.target.value))} /></label>
        <label>Median follow-up (years)<input type="number" min={0} step={0.1} value={p.followup_median_years ?? ""}
               onChange={(e) => set("followup_median_years", num(e.target.value))} /></label>
        <label>Years covered<input value={p.years} onChange={(e) => set("years", e.target.value)} placeholder="2015–2024" /></label>
        <label>Diverse / under-represented population?
          <select value={tri(p.diverse)} onChange={(e) => set("diverse", untri(e.target.value))}>
            <option value="">Not known</option><option value="yes">Yes</option><option value="no">No</option></select></label>
        <label>Prospectively collected?
          <select value={tri(p.prospective)} onChange={(e) => set("prospective", untri(e.target.value))}>
            <option value="">Not known</option><option value="yes">Yes</option><option value="no">No (retrospective)</option></select></label>
        <label style={{ gridColumn: "1 / -1" }}>Population description
          <input value={p.population} onChange={(e) => set("population", e.target.value)}
                 placeholder="e.g. US commercial and Medicare, 38% non-white" /></label>
      </div>
      <fieldset className="checks"><legend>Data comes from</legend>
        {ORIGINS.map(([v, l]) => <label key={v} className="check"><input type="checkbox" checked={p.origin.includes(v)}
          onChange={(e) => toggle("origin", v, e.target.checked)} />{l}</label>)}</fieldset>
      <fieldset className="checks"><legend>Data types included</legend>
        {DATA_TYPES.map(([v, l]) => <label key={v} className="check"><input type="checkbox" checked={p.data_types.includes(v)}
          onChange={(e) => toggle("data_types", v, e.target.checked)} />{l}</label>)}</fieldset>
      <p className="muted small" style={{ margin: 0 }}>Leave anything you don&apos;t know blank — it is shown as
        &quot;not known&quot; against each buyer&apos;s needs and never counted as a match.</p>
      {error && <p className="error">{error}</p>}
      <div className="row"><button className="btn primary">Save</button>
        <button type="button" className="link" onClick={onCancel}>Cancel</button></div>
    </form>
  );
}
