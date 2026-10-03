import type { NextRequest } from "next/server";

/** httpOnly cookie that holds the token issued by /api/auth/login (set by app/api/auth/login/route.ts). */
export const SESSION_COOKIE = "access_token";

/**
 * The caller's address as the proxy in front of this app reported it. Without it the backend sees only this app's own address
 * for every visitor. Sent only when the request already carries one; the backend believes it only from the proxies listed in
 * its FORWARDED_ALLOW_IPS (docker-compose.yml), so set that only when your proxy overwrites the header.
 */
export function clientIpHeaders(req: NextRequest): Record<string, string> {
  const forwarded = req.headers.get("x-forwarded-for");
  return forwarded ? { "X-Forwarded-For": forwarded } : {};
}

/**
 * Headers that carry the caller's identity to the backend.
 *
 * With AUTH_MODE=jwt the backend needs `Authorization: Bearer <token>` on every /api call. The token comes from, in order:
 *   1. an `Authorization` header already on the request (an identity-aware proxy in front of this app, or a script);
 *   2. the login cookie: the browser sends it by itself, and the page's JavaScript never sees the token.
 * With AUTH_MODE=off neither exists and nothing is added.
 */
export function authHeaders(req: NextRequest): Record<string, string> {
  const headers: Record<string, string> = { ...clientIpHeaders(req) };
  const lang = req.headers.get("x-ui-lang"); // the interface language: the backend writes its messages in it
  if (lang) headers["X-UI-Lang"] = lang;
  const token = req.headers.get("authorization");
  if (token) return { ...headers, Authorization: token };
  const cookie = req.cookies.get(SESSION_COOKIE)?.value;
  return cookie ? { ...headers, Authorization: `Bearer ${cookie}` } : headers;
}
