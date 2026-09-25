"use client";
import { useActionState } from "react";
import { signIn } from "./actions";

export default function Login() {
  const [error, action, pending] = useActionState(signIn, null);
  return (
    <main className="login">
      <form action={action} className="card login-card">
        <div className="brand-lg">BConz <span>DIA</span></div>
        <p className="muted">Who needs your data — and the lawful way to reach them.</p>
        <label>Work email<input name="email" type="email" required autoComplete="email" /></label>
        <label>Access code<input name="code" type="password" required autoComplete="current-password" /></label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="btn primary" disabled={pending}>{pending ? "Signing in…" : "Sign in"}</button>
      </form>
    </main>
  );
}
