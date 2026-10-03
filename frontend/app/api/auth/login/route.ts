import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, clientIpHeaders } from "@/lib/backendAuth";
import { serverMsg } from "@/lib/serverMessages";

export const dynamic = 'force-dynamic';

/**
 * Sign in: forward the credentials to the backend and keep the token it returns in an httpOnly cookie, so the browser's
 * JavaScript never sees it. Every other route handler turns the cookie back into the Bearer header (see authHeaders).
 */
export async function POST(req: NextRequest) {
  const backendUrl = process.env.API_URL ? `${process.env.API_URL}/api/auth/login` : 'http://backend:8000/api/auth/login';
  try {
    const response = await fetch(backendUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-UI-Lang": req.headers.get("x-ui-lang") ?? "vi", ...clientIpHeaders(req) },
      body: JSON.stringify(await req.json()),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      return NextResponse.json({ detail: data.detail || serverMsg(req, 'proxy.loginFailed') }, { status: response.status });
    }
    const secure = req.nextUrl.protocol === 'https:' || req.headers.get('x-forwarded-proto') === 'https';
    const result = NextResponse.json({ user: data.user });
    result.cookies.set(SESSION_COOKIE, data.access_token, {
      httpOnly: true,
      sameSite: 'lax',
      secure,
      path: '/',
      maxAge: data.expires_in,
    });
    return result;
  } catch (error: any) {
    return NextResponse.json({ detail: error.message || serverMsg(req, 'proxy.unreachable') }, { status: 502 });
  }
}
