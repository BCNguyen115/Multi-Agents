import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/backendAuth";
import { serverMsg } from "@/lib/serverMessages";

export const dynamic = 'force-dynamic';

type Context = { params: Promise<{ id: string }> }; // Next 15: route params arrive as a Promise

/** The outcome of an action somebody else approved, for the person who asked (two-person approval): they poll it. */
export async function GET(req: NextRequest, { params }: Context) {
  const { id } = await params;
  const base = process.env.API_URL || 'http://backend:8000';
  try {
    const response = await fetch(`${base}/api/chat/approve/${encodeURIComponent(id)}/result`, { headers: authHeaders(req), cache: 'no-store' });
    const data = await response.json().catch(() => ({}));
    return NextResponse.json(data, { status: response.status });
  } catch (error: any) {
    return NextResponse.json({ detail: error.message || serverMsg(req, 'proxy.unreachable') }, { status: 502 });
  }
}
