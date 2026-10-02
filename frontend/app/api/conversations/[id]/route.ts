import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/backendAuth";
import { serverMsg } from "@/lib/serverMessages";

export const dynamic = 'force-dynamic';

type Context = { params: Promise<{ id: string }> }; // Next 15: route params arrive as a Promise

function backendUrl(id: string): string {
  const base = process.env.API_URL || 'http://backend:8000';
  return `${base}/api/conversations/${encodeURIComponent(id)}`;
}

async function forward(req: NextRequest, id: string, init: RequestInit): Promise<NextResponse> {
  try {
    const response = await fetch(backendUrl(id), { ...init, headers: { ...authHeaders(req), ...(init.headers as Record<string, string> | undefined) }, cache: 'no-store' });
    if (response.status === 204) return new NextResponse(null, { status: 204 });
    const data = await response.json().catch(() => ({}));
    return NextResponse.json(data, { status: response.status }); // 409 carries the newer server version
  } catch (error: any) {
    return NextResponse.json({ detail: error.message || serverMsg(req, 'proxy.unreachable') }, { status: 502 });
  }
}

export async function GET(req: NextRequest, { params }: Context) {
  return forward(req, (await params).id, { method: 'GET' });
}

export async function PUT(req: NextRequest, { params }: Context) {
  return forward(req, (await params).id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: await req.text() });
}

export async function DELETE(req: NextRequest, { params }: Context) {
  return forward(req, (await params).id, { method: 'DELETE' });
}
