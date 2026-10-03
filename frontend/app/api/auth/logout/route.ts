import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, authHeaders } from "@/lib/backendAuth";

export const dynamic = 'force-dynamic';

/** Sign out: the backend revokes the token (so a copy of it stops working too), then the cookie is cleared either way. */
export async function POST(req: NextRequest) {
  const backendUrl = process.env.API_URL ? `${process.env.API_URL}/api/auth/logout` : 'http://backend:8000/api/auth/logout';
  try {
    await fetch(backendUrl, { method: "POST", headers: authHeaders(req) });
  } catch {
    /* backend unreachable: the cookie is still cleared, the token expires by itself */
  }
  const result = NextResponse.json({ ok: true });
  result.cookies.set(SESSION_COOKIE, '', { httpOnly: true, sameSite: 'lax', path: '/', maxAge: 0 });
  return result;
}
