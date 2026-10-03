import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, clientIpHeaders } from "@/lib/backendAuth";
import { serverMsg } from "@/lib/serverMessages";

export const dynamic = 'force-dynamic';

/** Sign up: the backend creates the account and returns a token; it is kept in the same httpOnly cookie as a sign-in. */
export async function POST(req: NextRequest) {
  const backendUrl = process.env.API_URL ? `${process.env.API_URL}/api/auth/register` : 'http://backend:8000/api/auth/register';
  try {
    const response = await fetch(backendUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-UI-Lang": req.headers.get("x-ui-lang") ?? "vi", ...clientIpHeaders(req) },
      body: JSON.stringify(await req.json()),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = Array.isArray(data.detail) ? data.detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join('; ') : data.detail;
      return NextResponse.json({ detail: detail || serverMsg(req, 'proxy.loginFailed') }, { status: response.status });
    }
    const secure = req.nextUrl.protocol === 'https:' || req.headers.get('x-forwarded-proto') === 'https';
    const result = NextResponse.json({ user: data.user, recovery_key: data.recovery_key }); // shown to the user once
    result.cookies.set(SESSION_COOKIE, data.access_token, { httpOnly: true, sameSite: 'lax', secure, path: '/', maxAge: data.expires_in });
    return result;
  } catch (error: any) {
    return NextResponse.json({ detail: error.message || serverMsg(req, 'proxy.unreachable') }, { status: 502 });
  }
}
