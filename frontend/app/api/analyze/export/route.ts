import { NextRequest, NextResponse } from 'next/server';
import { authHeaders } from '@/lib/backendAuth';

export const maxDuration = 60;
export const dynamic = 'force-dynamic';

/** Proxy for "CSV" on the dashboard grid: every row matching the grid's search, filters and sort, not just the visible page. */
export async function POST(req: NextRequest) {
  try {
    const backendUrl = process.env.API_URL ? `${process.env.API_URL}/api/analyze/export` : 'http://backend:8000/api/analyze/export';
    const response = await fetch(backendUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders(req) },
      body: JSON.stringify(await req.json()),
      signal: AbortSignal.timeout(55_000),
    });
    if (!response.ok) return NextResponse.json(await response.json().catch(() => ({})), { status: response.status });
    return new Response(response.body, { status: 200, headers: { 'Content-Type': 'text/csv; charset=utf-8' } });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Proxy connection error';
    return NextResponse.json({ detail: message }, { status: 502 });
  }
}
