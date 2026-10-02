import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/backendAuth";
import { serverMsg } from "@/lib/serverMessages";

export const dynamic = 'force-dynamic';

/** Who the backend thinks the caller is. 401 means: show the login screen. */
export async function GET(req: NextRequest) {
  const backendUrl = process.env.API_URL ? `${process.env.API_URL}/api/auth/me` : 'http://backend:8000/api/auth/me';
  try {
    const response = await fetch(backendUrl, { headers: authHeaders(req), cache: 'no-store' });
    const data = await response.json().catch(() => ({}));
    return NextResponse.json(data, { status: response.status });
  } catch (error: any) {
    return NextResponse.json({ detail: error.message || serverMsg(req, 'proxy.unreachable') }, { status: 502 });
  }
}
