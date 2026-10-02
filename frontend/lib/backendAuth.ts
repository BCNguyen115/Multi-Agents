import type { NextRequest } from "next/server";

/** httpOnly cookie that holds the token issued by /api/auth/login (set by app/api/auth/login/route.ts). */
export const SESSION_COOKIE = "access_token";

/**
 * Headers that carry the caller's identity to the backend.
 *
 * With AUTH_MODE=jwt the backend needs `Authorization: Bearer <token>` on every /api call. The token comes from, in order:
 *   1. an `Authorization` header already on the request (an identity-aware proxy in front of this app, or a script);
 *   2. the login cookie: the browser sends it by itself, and the page's JavaScript never sees the token.
 * With AUTH_MODE=off neither exists and nothing is added.
 */
export function authHeaders(req: NextRequest): Record<string, string> {
  const headers: Record<string, string> = {};
  const lang = req.headers.get("x-ui-lang"); // the interface language: the backend writes its messages in it
  if (lang) headers["X-UI-Lang"] = lang;
  const token = req.headers.get("authorization");
  if (token) return { ...headers, Authorization: token };
  const cookie = req.cookies.get(SESSION_COOKIE)?.value;
  return cookie ? { ...headers, Authorization: `Bearer ${cookie}` } : headers;
}
