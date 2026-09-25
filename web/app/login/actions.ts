"use server";
import { timingSafeEqual } from "node:crypto";
import { redirect } from "next/navigation";
import { allowedEmails, createSession, destroySession } from "@/lib/session";

function same(a: string, b: string) {
  const x = Buffer.from(a), y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}

export async function signIn(_: string | null, form: FormData): Promise<string | null> {
  const email = String(form.get("email") ?? "").trim().toLowerCase();
  const code = String(form.get("code") ?? "");
  const expected = (process.env.DIA_ACCESS_CODE ?? "").trim();
  // One message for every failure, so the form does not reveal who is allowed.
  if (!expected || !allowedEmails().includes(email) || !same(code, expected)) {
    return "That email and access code do not match a BCONZ DIA account.";
  }
  await createSession(email);
  redirect("/");
}

export async function signOut() {
  await destroySession();
  redirect("/login");
}
