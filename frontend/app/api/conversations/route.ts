import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/backendAuth";
import { serverMsg } from "@/lib/serverMessages";

export const dynamic = 'force-dynamic';

/** The signed-in user's conversations (summaries). Handled here so the login cookie becomes the Bearer header. */
export async function GET(req: NextRequest) {
  const backendUrl = process.env.API_URL ? `${process.env.API_URL}/api/conversations` : 'http://backend:8000/api/conversations';
  try {
    const response = await fetch(backendUrl, { headers: authHeaders(req), cache: 'no-store' });
    const data = await response.json().catch(() => ({}));
    return NextResponse.json(data, { status: response.status });
  } catch (error: any) {
    return NextResponse.json({ detail: error.message || serverMsg(req, 'proxy.unreachable') }, { status: 502 });
  }
}
