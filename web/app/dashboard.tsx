"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, type Run, type Watch } from "@/lib/types";

const when = (s: string | null) => (s ? new Date(s).toLocaleString() : "—");

export default function Dashboard() {
  const router = useRouter();
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [watches, setWatches] = useState<Watch[]>([]);
  const [disease, setDisease] = useState("");
  const [top, setTop] = useState(20);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [r, w] = await Promise.all([api<Run[]>("runs"), api<Watch[]>("watches")]);
      setRuns(r); setWatches(w);
    } catch (e) { setError((e as Error).message); }
  }, []);

  useEffect(() => { load(); }, [load]);
  // Keep in-flight runs fresh without the user reloading.
  useEffect(() => {
    if (!runs?.some((r) => r.status === "queued" || r.status === "running")) return;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [runs, load]);

  async function start(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const r = await api<Run>("runs", { method: "POST",
        body: JSON.stringify({ disease, top_contacts: top }) });
      router.push(`/runs/${r.id}`);
    } catch (e) { setError((e as Error).message); setBusy(false); }
  }

  async function watch(d: string) {
    try {
      await api("watches", { method: "POST", body: JSON.stringify({ disease: d, interval_days: 7 }) });
      load();
    } catch (e) { setError((e as Error).message); }
  }

  async function unwatch(id: number) {
    await api(`watches/${id}`, { method: "DELETE" });
    load();
  }

  const watched = new Set(watches.filter((w) => w.active).map((w) => w.disease.toLowerCase()));

  return (
    <main className="wrap">
      <p className="eyebrow">Demand intelligence</p>
      <h1>Who needs data in…</h1>
      <p className="muted">
        Searches papers that state a data gap, active NIH grants and live trials, ranks the organisations
        behind them, then finds contacts that were published to be contacted.
      </p>

      <form className="card newrun" onSubmit={start} style={{ marginTop: 18 }}>
        <label>Disease or indication
          <input value={disease} onChange={(e) => setDisease(e.target.value)} required minLength={3}
                 placeholder="e.g. multiple myeloma, Gaucher disease, diabetic retinopathy" />
        </label>
        <label>Resolve contacts for top
          <select value={top} onChange={(e) => setTop(Number(e.target.value))}>
            {[10, 20, 30, 45].map((n) => <option key={n} value={n}>{n} leads</option>)}
          </select>
        </label>
        <button className="btn primary" disabled={busy}>{busy ? "Starting…" : "Find demand"}</button>
      </form>
      {error && <p className="error" style={{ marginTop: 10 }}>{error}</p>}

      {watches.some((w) => w.active) && (
        <>
          <h2>Watching</h2>
          <div className="card table-wrap">
            <table>
              <thead><tr><th>Disease</th><th>Every</th><th>Last run</th><th>New signals</th><th /></tr></thead>
              <tbody>
                {watches.filter((w) => w.active).map((w) => (
                  <tr key={w.id}>
                    <td>{w.last_run ? <Link href={`/runs/${w.last_run.id}`}>{w.disease}</Link> : w.disease}</td>
                    <td>{w.interval_days} days</td>
                    <td className="small">{when(w.last_run_at)}</td>
                    <td>{w.last_run?.summary?.new_signals ?? "—"}</td>
                    <td><button className="link" onClick={() => unwatch(w.id)}>Stop</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <h2>Recent searches</h2>
      <div className="card table-wrap">
        {runs === null ? <p className="muted">Loading…</p> : runs.length === 0 ? (
          <p className="muted">No searches yet. Start with a disease above.</p>
        ) : (
          <table>
            <thead><tr><th>Disease</th><th>Status</th><th>Organisations</th><th>Tier A</th>
              <th>Contactable</th><th>Started</th><th /></tr></thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id}>
                  <td><Link href={`/runs/${r.id}`}>{r.disease}</Link>
                    {r.watch_id && <span className="badge">watch</span>}</td>
                  <td className={`s-${r.status}`}>{r.status}</td>
                  <td>{r.summary?.organisations ?? "—"}</td>
                  <td>{r.summary?.tiers?.A ?? "—"}</td>
                  <td>{r.summary?.contactable ?? "—"}</td>
                  <td className="small muted">{when(r.created_at)}<br />{r.created_by}</td>
                  <td>{!watched.has(r.disease.toLowerCase()) && r.status === "done" &&
                    <button className="link" onClick={() => watch(r.disease)}>Watch weekly</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </main>
  );
}
