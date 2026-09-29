"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Fragment, Suspense, useCallback, useEffect, useState } from "react";
import { api, sendCommand, type Outreach } from "@/lib/types";
import { DraftEditor } from "../outreach-panel";

const STATUSES = ["draft", "queued", "sent", "skipped"] as const;

export default function OutreachList() {
  return <Suspense fallback={<main className="wrap"><p className="muted">Loading…</p></main>}><List /></Suspense>;
}

function List() {
  const params = useSearchParams();
  const [rows, setRows] = useState<Outreach[] | null>(null);
  const [show, setShow] = useState<Set<string>>(new Set(["draft", "queued"]));
  const [open, setOpen] = useState<number | null>(null);
  const [msg, setMsg] = useState("");

  const load = useCallback(() => api<Outreach[]>("outreach").then(setRows).catch((e) => setMsg(e.message)), []);

  // The send script opens /outreach?sent=<id> after a successful send.
  useEffect(() => {
    const sent = params.get("sent");
    (async () => {
      if (sent) {
        try {
          const r = await api<Outreach>(`outreach/${sent}`, { method: "PUT", body: JSON.stringify({ status: "sent" }) });
          setMsg(`Marked as sent: ${r.subject} → ${r.email}.`);
        } catch (e) { setMsg(`Could not mark #${sent} as sent: ${(e as Error).message}`); }
      }
      load();
    })();
  }, [params, load]);

  async function copyCommand(o: Outreach) {
    let r = o;
    if (o.status === "draft" && o.email) {
      r = await api<Outreach>(`outreach/${o.id}`, { method: "PUT", body: JSON.stringify({ status: "queued" }) });
    }
    try { await navigator.clipboard.writeText(sendCommand(r)); setMsg(`Send command for #${o.id} copied: paste it into PowerShell.`); }
    catch { setMsg("Copy failed."); }
    load();
  }
  async function setStatus(o: Outreach, status: string) {
    try { await api(`outreach/${o.id}`, { method: "PUT", body: JSON.stringify({ status }) }); load(); }
    catch (e) { setMsg((e as Error).message); }
  }
  async function remove(o: Outreach) {
    if (!confirm(`Delete the draft to ${o.org_display}?`)) return;
    await api(`outreach/${o.id}`, { method: "DELETE" }); load();
  }

  const shown = (rows ?? []).filter((o) => show.has(o.status));
  const toggle = (s: string) => setShow((x) => { const n = new Set(x); if (n.has(s)) n.delete(s); else n.add(s); return n; });

  return (
    <main className="wrap">
      <p className="eyebrow">First-touch messages</p>
      <h1>Outreach</h1>
      <p className="muted">Drafts are written from each lead&apos;s evidence. Send them yourself: copy the PowerShell
        command (asks for your mailbox password, sends on <code>y</code>, marks it sent here), open them in your email
        app, or copy the LinkedIn note. One follow-up at most; anyone who says no goes on the do-not-contact list.</p>
      {msg && <p className="small">{msg}</p>}
      <div className="filters">
        {STATUSES.map((s) => (
          <button key={s} className="chip" aria-pressed={show.has(s)} onClick={() => toggle(s)}>
            {s} ({(rows ?? []).filter((o) => o.status === s).length})</button>
        ))}
      </div>
      <div className="card table-wrap">
        {rows === null ? <p className="muted">Loading…</p> : shown.length === 0 ? (
          <p className="muted">Nothing here yet. Open a search, then use “Draft outreach” on a lead or contact.</p>
        ) : (
          <table>
            <thead><tr><th>Organisation</th><th>To</th><th>Subject</th><th>Status</th><th>Send</th><th /></tr></thead>
            <tbody>
              {shown.map((o) => (
                <Fragment key={o.id}>
                  <tr>
                    <td><strong>{o.org_display}</strong>{o.person_name && <div className="muted small">{o.person_name}</div>}
                      {o.run_id && <div className="small"><Link href={`/runs/${o.run_id}`}>search #{o.run_id}</Link></div>}</td>
                    <td className="small mono">{o.email || <span className="muted">not yet</span>}</td>
                    <td className="small">{o.subject}</td>
                    <td><span className={`badge s-${o.status}`}>{o.status}</span>
                      {o.sent_at && <div className="muted small">{new Date(o.sent_at).toLocaleDateString()}</div>}</td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {o.status !== "sent" && <button className="btn primary small" onClick={() => copyCommand(o)}>Copy send command</button>}
                    </td>
                    <td className="small" style={{ whiteSpace: "nowrap" }}>
                      <button className="link" onClick={() => setOpen(open === o.id ? null : o.id)}>{open === o.id ? "Close" : "Edit"}</button>
                      {o.status !== "sent" && <>{" · "}<button className="link" onClick={() => setStatus(o, "sent")}>Mark sent</button></>}
                      {o.status !== "skipped" && o.status !== "sent" && <>{" · "}<button className="link" onClick={() => setStatus(o, "skipped")}>Skip</button></>}
                      {" · "}<button className="link" onClick={() => remove(o)}>Delete</button>
                    </td>
                  </tr>
                  {open === o.id && (
                    <tr><td colSpan={6}><DraftEditor initial={o} onChange={() => load()} /></td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </main>
  );
}
