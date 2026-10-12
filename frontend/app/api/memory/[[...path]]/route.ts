import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/backendAuth";
import { serverMsg } from "@/lib/serverMessages";

export const dynamic = 'force-dynamic';

type Context = { params: Promise<{ path?: string[] }> }; // Next 15: route params arrive as a Promise

/** `/api/memory` and `/api/memory/<id>`: nothing else is forwarded. */
const ALLOWED = /^([A-Za-z0-9_-]{1,80})?$/;

/** The login cookie becomes the Bearer header here (the generic `/api/*` rewrite does not do that). */
async function forward(req: NextRequest, { params }: Context, init: RequestInit): Promise<NextResponse> {
  const path = ((await params).path ?? []).join('/');
  if (!ALLOWED.test(path)) return NextResponse.json({ detail: 'not found' }, { status: 404 });
  const base = process.env.API_URL || 'http://backend:8000';
  try {
    const response = await fetch(`${base}/api/memory${path ? `/${path}` : ''}`, {
      ...init,
      headers: { ...authHeaders(req), ...(init.headers as Record<string, string> | undefined) },
      cache: 'no-store',
    });
    if (response.status === 204) return new NextResponse(null, { status: 204 });
    const data = await response.json().catch(() => ({}));
    return NextResponse.json(data, { status: response.status });
  } catch (error: any) {
    return NextResponse.json({ detail: error.message || serverMsg(req, 'proxy.unreachable') }, { status: 502 });
  }
}

export const GET = (req: NextRequest, ctx: Context) => forward(req, ctx, { method: 'GET' });
export const DELETE = (req: NextRequest, ctx: Context) => forward(req, ctx, { method: 'DELETE' });
