import "server-only";
import { SignJWT, jwtVerify } from "jose";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

const COOKIE = "atlas_session";
const MAX_AGE = 60 * 60 * 12; // 12 hours

function secret() {
  const s = (process.env.SESSION_SECRET ?? "").trim();
  if (s.length < 32) throw new Error("SESSION_SECRET must be at least 32 characters");
  return new TextEncoder().encode(s);
}

export function allowedEmails(): string[] {
  return (process.env.ATLAS_ALLOWED_EMAILS ?? "")
    .split(",").map((e) => e.trim().toLowerCase()).filter(Boolean);
}

export async function createSession(email: string) {
  const token = await new SignJWT({ email })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime(`${MAX_AGE}s`)
    .sign(secret());
  (await cookies()).set(COOKIE, token, {
    httpOnly: true, secure: process.env.NODE_ENV === "production",
    sameSite: "lax", path: "/", maxAge: MAX_AGE,
  });
}

export async function destroySession() {
  (await cookies()).delete(COOKIE);
}

/** The signed-in email, or null. Re-checks the allowlist so removing someone
 *  from ATLAS_ALLOWED_EMAILS takes effect without waiting for expiry. */
export async function currentUser(): Promise<string | null> {
  // Local development only: `next build` always sets NODE_ENV=production, so
  // this can never be active in a deployed build.
  if (process.env.NODE_ENV === "development" && process.env.ATLAS_DEV_USER) {
    return process.env.ATLAS_DEV_USER.toLowerCase();
  }
  const token = (await cookies()).get(COOKIE)?.value;
  if (!token) return null;
  try {
    const { payload } = await jwtVerify(token, secret());
    const email = String(payload.email ?? "").toLowerCase();
    return allowedEmails().includes(email) ? email : null;
  } catch {
    return null;
  }
}

export async function requireUser(): Promise<string> {
  const u = await currentUser();
  if (!u) redirect("/login");
  return u;
}
