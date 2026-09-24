"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/types";

type Row = { id: number; value: string; reason: string; by: string; at: string };

export default function SuppressionList() {
  const [rows, setRows] = useState<Row[]>([]);
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(() => api<Row[]>("suppression").then(setRows).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api("suppression", { method: "POST", body: JSON.stringify({ value, reason }) });
      setValue(""); setReason(""); load();
    } catch (e) { setError((e as Error).message); }
  }

  async function remove(r: Row) {
    if (!confirm(`Remove ${r.value} from the do-not-contact list?`)) return;
    await api(`suppression/${r.id}`, { method: "DELETE" });
    load();
  }

  return (
    <main className="wrap">
      <h1>Do-not-contact list</h1>
      <p className="muted">Anyone here is excluded from every search and every export, including results already stored.
        Add an email address or a full name. Honour opt-out requests the same day.</p>
      <form className="card newrun" onSubmit={add} style={{ marginTop: 18 }}>
        <label>Email or name<input value={value} onChange={(e) => setValue(e.target.value)} required minLength={3} /></label>
        <label>Reason<input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. asked not to be contacted" /></label>
        <button className="btn primary">Add</button>
      </form>
      {error && <p className="error">{error}</p>}
      <h2>{rows.length} entries</h2>
      <div className="card table-wrap">
        <table>
          <thead><tr><th>Email or name</th><th>Reason</th><th>Added</th><th /></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="mono">{r.value}</td><td className="small">{r.reason}</td>
                <td className="small muted">{new Date(r.at).toLocaleDateString()} · {r.by}</td>
                <td><button className="link small" onClick={() => remove(r)}>Remove</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <p className="muted">Nobody yet.</p>}
      </div>
    </main>
  );
}
