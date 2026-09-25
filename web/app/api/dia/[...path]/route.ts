import { NextRequest } from "next/server";
import { currentUser } from "@/lib/session";

/** Authenticated pass-through to the Railway API. The API token never reaches
 *  the browser; the signed-in email is forwarded for the audit trail. */
async function forward(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const user = await currentUser();
  if (!user) return Response.json({ detail: "not signed in" }, { status: 401 });

  const { path } = await ctx.params;
  const base = (process.env.DIA_API_URL ?? "").trim().replace(/\/$/, "");
  const url = `${base}/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const init: RequestInit = {
    method: req.method,
    headers: {
      Authorization: `Bearer ${(process.env.DIA_API_TOKEN ?? "").trim()}`,
      "X-DIA-User": user,
      "Content-Type": req.headers.get("content-type") ?? "application/json",
    },
    cache: "no-store",
  };
  if (!["GET", "HEAD"].includes(req.method)) init.body = await req.text();

  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    return Response.json({ detail: "API unreachable" }, { status: 502 });
  }
  const headers = new Headers();
  for (const h of ["content-type", "content-disposition", "x-exported-rows", "x-excluded-rows"]) {
    const v = res.headers.get(h);
    if (v) headers.set(h, v);
  }
  headers.set("Cache-Control", "no-store");
  return new Response(res.status === 204 ? null : res.body, { status: res.status, headers });
}

export const GET = forward;
export const POST = forward;
export const DELETE = forward;
