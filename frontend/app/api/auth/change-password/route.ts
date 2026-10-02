import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/backendAuth";
import { serverMsg } from "@/lib/serverMessages";

export const dynamic = 'force-dynamic';

/** Change the signed-in user's password: the session cookie becomes the Bearer header, the current password is the proof. */
export async function POST(req: NextRequest) {
  const backendUrl = process.env.API_URL ? `${process.env.API_URL}/api/auth/change-password` : 'http://backend:8000/api/auth/change-password';
  try {
    const response = await fetch(backendUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders(req) },
      body: JSON.stringify(await req.json()),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = Array.isArray(data.detail) ? data.detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join('; ') : data.detail;
      return NextResponse.json({ detail: detail || serverMsg(req, 'proxy.loginFailed') }, { status: response.status });
    }
    return NextResponse.json(data);
  } catch (error: any) {
    return NextResponse.json({ detail: error.message || serverMsg(req, 'proxy.unreachable') }, { status: 502 });
  }
}
