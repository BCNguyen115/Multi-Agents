import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, clientIpHeaders } from "@/lib/backendAuth";
import { t } from "@/lib/i18n";
import { serverMsg } from "@/lib/serverMessages";

export const dynamic = 'force-dynamic';

const escapeHtml = (text: string): string => text.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string);

/** Where the browser really is (behind a proxy `req.nextUrl` is the internal address). */
function publicUrl(req: NextRequest, path: string): URL {
  const proto = req.headers.get('x-forwarded-proto') ?? req.nextUrl.protocol.replace(':', '');
  const host = req.headers.get('x-forwarded-host') ?? req.headers.get('host') ?? req.nextUrl.host;
  return new URL(path, `${proto}://${host}`);
}

function failure(req: NextRequest, detail: string, status: number): NextResponse {
  const lang = req.headers.get('x-ui-lang') === 'en' ? 'en' : 'vi';
  const html = `<!doctype html><html lang="${lang}"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHtml(t(lang, 'auth.sso.failed'))}</title>`
    + `<body style="font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem"><h1>${escapeHtml(t(lang, 'auth.sso.failed'))}</h1>`
    + `<p>${escapeHtml(detail)}</p><p><a href="/">${escapeHtml(t(lang, 'auth.sso.back'))}</a></p></body></html>`;
  return new NextResponse(html, { status, headers: { 'Content-Type': 'text/html; charset=utf-8' } });
}

/**
 * The identity provider redirects the browser here with `?code&state`. The backend spends the state, checks the id_token and
 * returns its own token, which is kept in the same httpOnly cookie a password sign-in uses.
 */
export async function GET(req: NextRequest) {
  const code = req.nextUrl.searchParams.get('code');
  const state = req.nextUrl.searchParams.get('state');
  if (!code || !state) return failure(req, req.nextUrl.searchParams.get('error_description') || req.nextUrl.searchParams.get('error') || serverMsg(req, 'proxy.loginFailed'), 400);
  const base = process.env.API_URL || 'http://backend:8000';
  try {
    const response = await fetch(`${base}/api/auth/oidc/callback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-UI-Lang': req.headers.get('x-ui-lang') ?? 'vi', ...clientIpHeaders(req) },
      body: JSON.stringify({ code, state }),
      cache: 'no-store',
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) return failure(req, typeof data.detail === 'string' ? data.detail : serverMsg(req, 'proxy.loginFailed'), response.status);
    const secure = req.nextUrl.protocol === 'https:' || req.headers.get('x-forwarded-proto') === 'https';
    const result = NextResponse.redirect(publicUrl(req, '/'), 302);
    result.cookies.set(SESSION_COOKIE, data.access_token, { httpOnly: true, sameSite: 'lax', secure, path: '/', maxAge: data.expires_in });
    return result;
  } catch (error: any) {
    return failure(req, error.message || serverMsg(req, 'proxy.unreachable'), 502);
  }
}
