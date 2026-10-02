import { NextRequest, NextResponse } from 'next/server';
import { authHeaders } from '@/lib/backendAuth';

export const maxDuration = 60;
export const dynamic = 'force-dynamic';

/** Proxy for cross-filtering: the backend recomputes and re-verifies every chart for the selected rows. */
export async function POST(req: NextRequest) {
  try {
    const backendUrl = process.env.API_URL ? `${process.env.API_URL}/api/analyze/filter` : 'http://backend:8000/api/analyze/filter';
    const response = await fetch(backendUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders(req) },
      body: JSON.stringify(await req.json()),
      signal: AbortSignal.timeout(55_000),
    });
    return NextResponse.json(await response.json(), { status: response.status });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Proxy connection error';
    return NextResponse.json({ detail: message }, { status: 502 });
  }
}
