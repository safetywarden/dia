"use client";
import { useState } from "react";
import { api, linkedinSearch, mailtoLink, sendCommand, type Outreach } from "@/lib/types";

/** Draft a first message to one lead. The user supplies the address they
 *  found (and where); DIA writes the email and a LinkedIn note. Nothing is
 *  sent from here: the user sends from their own mailbox or the send script. */
export function DraftPanel({ runId, orgKey, orgName, person = "", email = "", foundAt = "", onClose }:
  { runId: number; orgKey: string; orgName: string; person?: string; email?: string; foundAt?: string;
    onClose: () => void }) {
  const [name, setName] = useState(person);
  const [addr, setAddr] = useState(email);
  const [where, setWhere] = useState(foundAt);
  const [draft, setDraft] = useState<Outreach | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function write(e: React.FormEvent) {
    e.preventDefault(); setError(""); setBusy(true);
    try {
      setDraft(await api<Outreach>(`runs/${runId}/outreach`, { method: "POST",
        body: JSON.stringify({ org_key: orgKey, person_name: name, email: addr, found_at: where }) }));
    } catch (err) { setError((err as Error).message); }
    setBusy(false);
  }

  return (
    <div className="card draft">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>Outreach to {orgName}</strong>
        <button className="link small" onClick={onClose}>Close</button>
      </div>
      {!draft ? (
        <form className="grid2" onSubmit={write}>
          <label>Person (optional)<input value={name} onChange={(e) => setName(e.target.value)}
                 placeholder="Leave blank to write to the team" /></label>
          <label>Email you found (optional)<input type="email" value={addr} onChange={(e) => setAddr(e.target.value)}
                 placeholder="name@company.com" /></label>
          <label style={{ gridColumn: "1 / -1" }}>Where you found it
            <input value={where} onChange={(e) => setWhere(e.target.value)} required={!!addr}
                   placeholder="e.g. company.com/contact, or the paper's corresponding-author line" />
            <span className="muted small">The email tells the recipient where their address came from. Don&apos;t
              guess addresses (firstname.lastname@…): use one the person or company published.</span></label>
          {error && <p className="error" style={{ gridColumn: "1 / -1" }}>{error}</p>}
          <div className="row"><button className="btn primary" disabled={busy}>{busy ? "Writing…" : "Write draft"}</button></div>
        </form>
      ) : <DraftEditor initial={draft} onChange={setDraft} />}
    </div>
  );
}

export function DraftEditor({ initial, onChange }: { initial: Outreach; onChange?: (o: Outreach) => void }) {
  const [o, setO] = useState(initial);
  const [msg, setMsg] = useState(initial.warning ?? "");
  const [dirty, setDirty] = useState(false);
  const set = (k: keyof Outreach, v: string) => { setO({ ...o, [k]: v }); setDirty(true); };

  async function save(extra: Partial<Outreach> = {}): Promise<Outreach | null> {
    try {
      const r = await api<Outreach>(`outreach/${o.id}`, { method: "PUT", body: JSON.stringify({
        person_name: o.person_name, email: o.email, found_at: o.found_at, subject: o.subject,
        body: o.body, linkedin: o.linkedin, ...extra }) });
      setO(r); setDirty(false); onChange?.(r);
      setMsg(r.warning || "Saved.");
      return r;
    } catch (e) { setMsg((e as Error).message); return null; }
  }
  async function copy(text: string, what: string) {
    try { await navigator.clipboard.writeText(text); setMsg(`${what} copied.`); }
    catch { setMsg("Copy failed: select the text and copy it by hand."); }
  }
  async function copyCommand() {
    const r = dirty || o.status === "draft" ? await save({ status: o.email ? "queued" : o.status }) : o;
    if (!r) return;
    await copy(sendCommand(r), "PowerShell send command");
    setMsg("Command copied. Paste it into PowerShell and press Enter: it shows the email, asks for your "
           + "password, sends only when you type y, then marks it sent here.");
  }

  return (
    <div className="draft-edit">
      <div className="grid2">
        <label>To<input type="email" value={o.email} onChange={(e) => set("email", e.target.value)}
               placeholder="add the address, or the send script will ask for it" /></label>
        <label>Where it was found<input value={o.found_at} onChange={(e) => set("found_at", e.target.value)} /></label>
      </div>
      <label>Subject<input value={o.subject} onChange={(e) => set("subject", e.target.value)} /></label>
      <label>Email<textarea rows={14} value={o.body} onChange={(e) => set("body", e.target.value)} /></label>
      <label>LinkedIn note <span className="muted small">({o.linkedin.length}/300; send it yourself on LinkedIn)</span>
        <textarea rows={3} maxLength={300} value={o.linkedin} onChange={(e) => set("linkedin", e.target.value)} /></label>
      <div className="row wrap">
        <button className="btn primary" onClick={copyCommand}>Copy send command</button>
        {o.email && <a className="btn" href={mailtoLink(o)}>Open in email app</a>}
        <button className="btn" onClick={() => copy(`Subject: ${o.subject}\n\n${o.body}`, "Email")}>Copy email</button>
        <button className="btn" onClick={() => copy(o.linkedin, "LinkedIn note")}>Copy LinkedIn note</button>
        <a className="btn" href={linkedinSearch(o)} target="_blank" rel="noopener noreferrer">Find on LinkedIn</a>
        {dirty && <button className="btn" onClick={() => save()}>Save edits</button>}
        {o.status !== "sent" && <button className="link small" onClick={() => save({ status: "sent" })}>Mark sent</button>}
        <span className={`badge s-${o.status}`}>{o.status}</span>
      </div>
      {msg && <p className="small">{msg}</p>}
    </div>
  );
}
