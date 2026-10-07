import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/backendAuth";
import { serverMsg } from "@/lib/serverMessages";

export const dynamic = 'force-dynamic';

/** Thumbs on an answer: the session cookie becomes the Bearer header, the backend keeps the rating (table rag_feedback). */
export async function POST(req: NextRequest) {
  const backendUrl = process.env.API_URL ? `${process.env.API_URL}/api/chat/feedback` : 'http://backend:8000/api/chat/feedback';
  try {
    const response = await fetch(backendUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders(req) },
      body: JSON.stringify(await req.json()),
    });
    if (response.status === 204) return new NextResponse(null, { status: 204 });
    const data = await response.json().catch(() => ({}));
    const detail = Array.isArray(data.detail) ? data.detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join('; ') : data.detail;
    return NextResponse.json({ detail: detail || serverMsg(req, 'proxy.unreachable') }, { status: response.status });
  } catch (error: any) {
    return NextResponse.json({ detail: error.message || serverMsg(req, 'proxy.unreachable') }, { status: 502 });
  }
}
