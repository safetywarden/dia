"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, DATA_TYPES, MARKETS, ORIGINS, type Run } from "@/lib/types";

function toggle(list: string[], v: string, on: boolean) {
  return on ? [...list, v] : list.filter((x) => x !== v);
}

/** One box for the everyday search; "More filters" for drug, biomarker, data
 *  type, population, company, where the offered data comes from, and markets. */
export default function SearchForm() {
  const router = useRouter();
  const [f, setF] = useState({ disease: "", intervention: "", biomarker: "", population: "", sponsor: "" });
  const [dataTypes, setDataTypes] = useState<string[]>([]);
  const [supply, setSupply] = useState<string[]>([]);          // empty = worldwide
  const [markets, setMarkets] = useState<string[]>(MARKETS.map((m) => m.id));
  const [top, setTop] = useState(20);
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  const hasTopic = [f.disease, f.intervention, f.biomarker, f.sponsor].some((v) => v.trim().length >= 2);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!hasTopic) { setError("Enter a disease, drug, biomarker or company."); setMore(true); return; }
    setBusy(true); setError("");
    try {
      const r = await api<Run>("runs", { method: "POST", body: JSON.stringify({
        ...f, data_types: dataTypes, supply, regions: markets, top_contacts: top }) });
      router.push(`/runs/${r.id}`);
    } catch (err) { setError((err as Error).message); setBusy(false); }
  }

  return (
    <form className="card search" onSubmit={submit} style={{ marginTop: 18 }}>
      <div className="search-main">
        <label>Disease or indication
          <input value={f.disease} onChange={set("disease")}
                 placeholder="e.g. glaucoma, asthma, myasthenia gravis" />
        </label>
        <button className="btn primary" disabled={busy || markets.length === 0}>{busy ? "Starting…" : "Find demand"}</button>
      </div>
      <button type="button" className="link small" onClick={() => setMore(!more)} aria-expanded={more}>
        {more ? "Fewer filters" : "More filters — drug, biomarker, data type, population, company"}
      </button>

      {more && (
        <div className="search-more">
          <div className="grid2">
            <label>Drug or intervention<input value={f.intervention} onChange={set("intervention")} placeholder="e.g. semaglutide, anti-VEGF, CAR-T" /></label>
            <label>Biomarker or gene<input value={f.biomarker} onChange={set("biomarker")} placeholder="e.g. EGFR, APOE4, HbA1c" /></label>
            <label>Population<input value={f.population} onChange={set("population")} placeholder="e.g. paediatric, South Asian, elderly" /></label>
            <label>Company or institution<input value={f.sponsor} onChange={set("sponsor")} placeholder="e.g. Novartis, Mayo Clinic" /></label>
          </div>

          <fieldset className="checks">
            <legend>Data type they need <span className="muted">(optional — narrows to papers and trials that mention it)</span></legend>
            {DATA_TYPES.map(([id, label]) => (
              <label key={id} className="check">
                <input type="checkbox" checked={dataTypes.includes(id)}
                       onChange={(e) => setDataTypes(toggle(dataTypes, id, e.target.checked))} />{label}
              </label>
            ))}
          </fieldset>

          <fieldset className="checks">
            <legend>Data we would offer comes from <span className="muted">(none ticked = worldwide)</span></legend>
            {ORIGINS.map(([id, label]) => (
              <label key={id} className="check">
                <input type="checkbox" checked={supply.includes(id)}
                       onChange={(e) => setSupply(toggle(supply, id, e.target.checked))} />{label}
              </label>
            ))}
          </fieldset>

          <fieldset className="checks">
            <legend>Search registries in</legend>
            {MARKETS.map((m) => (
              <label key={m.id} className="check" title={m.note}>
                <input type="checkbox" checked={markets.includes(m.id)}
                       onChange={(e) => setMarkets(toggle(markets, m.id, e.target.checked))} />{m.label}
              </label>
            ))}
            <span className="muted small">Papers and ClinicalTrials.gov are always searched worldwide · India (CTRI) pending access</span>
          </fieldset>

          <label style={{ maxWidth: 240 }}>Resolve contacts for top
            <select value={top} onChange={(e) => setTop(Number(e.target.value))}>
              {[10, 20, 30, 45].map((n) => <option key={n} value={n}>{n} leads</option>)}
            </select>
          </label>
        </div>
      )}
      {error && <p className="error">{error}</p>}
    </form>
  );
}
