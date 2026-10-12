import { NextRequest, NextResponse } from "next/server";
import { authHeaders } from "@/lib/backendAuth";
import { serverMsg } from "@/lib/serverMessages";

export const dynamic = 'force-dynamic';

type Context = { params: Promise<{ path?: string[] }> }; // Next 15: route params arrive as a Promise

const ID = '[A-Za-z0-9_.:-]{1,64}';

/** The administration console's routes: nothing else is forwarded. */
const ALLOWED = new RegExp(
  `^(users(/[^\\s/]{1,64}(/(sign-out|reset-credentials))?)?|usage|overview|health|org|audit(/export)?|approvals|jobs(/[A-Za-z0-9_-]{1,64}/cancel)?|config|alerts|backup|feedback|policies(/${ID}/(${ID}|\\*))?|tenants(/${ID}(/departments(/${ID})?)?)?)$`,
);

/** The login cookie becomes the Bearer header here (the generic `/api/*` rewrite does not do that). The query string goes along. */
async function forward(req: NextRequest, { params }: Context, init: RequestInit): Promise<NextResponse> {
  const segments = (await params).path ?? [];
  if (!ALLOWED.test(segments.join('/'))) return NextResponse.json({ detail: 'not found' }, { status: 404 });
  const base = process.env.API_URL || 'http://backend:8000';
  try {
    const response = await fetch(`${base}/api/admin/${segments.map(encodeURIComponent).join('/')}${req.nextUrl.search}`, {
      ...init,
      headers: { ...authHeaders(req), ...(init.headers as Record<string, string> | undefined) },
      cache: 'no-store',
    });
    if (response.status === 204) return new NextResponse(null, { status: 204 });
    const type = response.headers.get('content-type') ?? '';
    if (type.startsWith('text/csv')) {
      // the audit export: a file, not JSON
      return new NextResponse(response.body, {
        status: response.status,
        headers: { 'Content-Type': type, 'Content-Disposition': response.headers.get('content-disposition') ?? 'attachment', 'Cache-Control': 'no-store' },
      });
    }
    const data = await response.json().catch(() => ({}));
    return NextResponse.json(data, { status: response.status });
  } catch (error: any) {
    return NextResponse.json({ detail: error.message || serverMsg(req, 'proxy.unreachable') }, { status: 502 });
  }
}

const json = { 'Content-Type': 'application/json' };

export const GET = (req: NextRequest, ctx: Context) => forward(req, ctx, { method: 'GET' });
export const POST = async (req: NextRequest, ctx: Context) => forward(req, ctx, { method: 'POST', headers: json, body: await req.text() });
export const PUT = async (req: NextRequest, ctx: Context) => forward(req, ctx, { method: 'PUT', headers: json, body: await req.text() });
export const PATCH = async (req: NextRequest, ctx: Context) => forward(req, ctx, { method: 'PATCH', headers: json, body: await req.text() });
export const DELETE = (req: NextRequest, ctx: Context) => forward(req, ctx, { method: 'DELETE' });
