import { NextRequest, NextResponse } from "next/server";
import { clientIpHeaders } from "@/lib/backendAuth";
import { serverMsg } from "@/lib/serverMessages";

export const dynamic = 'force-dynamic';

/** Start the SSO sign-in: ask the backend where the identity provider wants the browser, and send it there. */
export async function GET(req: NextRequest) {
  const base = process.env.API_URL || 'http://backend:8000';
  try {
    const response = await fetch(`${base}/api/auth/oidc/login`, {
      headers: { "X-UI-Lang": req.headers.get("x-ui-lang") ?? "vi", ...clientIpHeaders(req) },
      cache: 'no-store',
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || typeof data.url !== 'string') {
      return NextResponse.json({ detail: data.detail || serverMsg(req, 'proxy.loginFailed') }, { status: response.status || 502 });
    }
    return NextResponse.redirect(data.url, 302);
  } catch (error: any) {
    return NextResponse.json({ detail: error.message || serverMsg(req, 'proxy.unreachable') }, { status: 502 });
  }
}
