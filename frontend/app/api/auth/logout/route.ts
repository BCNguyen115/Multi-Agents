import { NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/lib/backendAuth";

export const dynamic = 'force-dynamic';

export async function POST() {
  const result = NextResponse.json({ ok: true });
  result.cookies.set(SESSION_COOKIE, '', { httpOnly: true, sameSite: 'lax', path: '/', maxAge: 0 });
  return result;
}
