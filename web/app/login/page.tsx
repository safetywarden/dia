"use client";
import { useActionState } from "react";
import Brand from "@/components/brand";
import { signIn } from "./actions";

export default function Login() {
  const [error, action, pending] = useActionState(signIn, null);
  return (
    <main className="login">
      <form action={action} className="card login-card">
        <Brand large />
        <p className="eyebrow">Demand intelligence</p>
        <p className="muted" style={{ marginTop: 0 }}>Who needs healthcare data — and the lawful way to reach them.</p>
        <label>Work email<input name="email" type="email" required autoComplete="email" /></label>
        <label>Access code<input name="code" type="password" required autoComplete="current-password" /></label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="btn primary" disabled={pending}>{pending ? "Signing in…" : "Sign in"}</button>
      </form>
    </main>
  );
}
